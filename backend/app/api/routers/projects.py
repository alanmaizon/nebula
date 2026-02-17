from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.contracts import ProjectCreateRequest, RetrievalRequest
from app.api.services.runtime import (
    EmbeddingServiceGetter,
    rank_chunks_by_query,
    require_project,
    resolve_project_upload_batch,
    serialize_document_for_api,
)
from app.config import settings
from app.db import (
    create_chunks,
    create_document,
    create_project,
    delete_chunks,
    list_chunks,
    list_documents,
)
from app.retrieval import build_parse_report, chunk_pages, extract_text_pages


def build_projects_router(*, get_embedding_service: EmbeddingServiceGetter) -> APIRouter:
    router = APIRouter()

    @router.post("/projects")
    def create_project_endpoint(payload: ProjectCreateRequest) -> dict[str, str]:
        return create_project(payload.name)

    @router.post("/projects/{project_id}/upload")
    async def upload_documents(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
        require_project(project_id)

        if len(files) > settings.max_upload_files:
            raise HTTPException(
                status_code=413,
                detail=f"Too many files in one upload batch (max {settings.max_upload_files}).",
            )

        upload_batch_id = str(uuid4())
        saved_documents: list[dict[str, object]] = []
        quality_counts: dict[str, int] = {"good": 0, "low": 0, "none": 0}
        embedding_warnings: list[dict[str, object]] = []
        embedding_service = get_embedding_service()
        project_folder = Path(settings.storage_root) / project_id
        project_folder.mkdir(parents=True, exist_ok=True)

        buffered_uploads: list[tuple[UploadFile, str, bytes]] = []
        total_bytes = 0
        for upload in files:
            incoming_name = upload.filename or "upload.bin"
            safe_name = Path(incoming_name).name or "upload.bin"
            content = await upload.read(settings.max_upload_file_bytes + 1)
            if len(content) > settings.max_upload_file_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{safe_name}' exceeds max size of {settings.max_upload_file_bytes} bytes.",
                )
            total_bytes += len(content)
            if total_bytes > settings.max_upload_batch_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload batch exceeds max size of {settings.max_upload_batch_bytes} bytes.",
                )
            buffered_uploads.append((upload, safe_name, content))

        for upload, safe_name, content in buffered_uploads:
            destination = project_folder / f"{uuid4()}_{safe_name}"
            destination.write_bytes(content)

            document = create_document(
                project_id=project_id,
                file_name=safe_name,
                content_type=upload.content_type or "application/octet-stream",
                storage_path=str(destination),
                size_bytes=len(content),
                upload_batch_id=upload_batch_id,
            )
            extraction = extract_text_pages(
                content=content,
                content_type=str(document["content_type"]),
                file_name=safe_name,
            )
            chunks = chunk_pages(
                pages=extraction.pages,
                chunk_size_chars=settings.chunk_size_chars,
                chunk_overlap_chars=settings.chunk_overlap_chars,
                embedding_dim=settings.embedding_dim,
                embedding_service=embedding_service,
                embedding_warnings=embedding_warnings,
            )
            parse_report = build_parse_report(
                content=content,
                content_type=str(document["content_type"]),
                file_name=safe_name,
                extraction=extraction,
                chunks=chunks,
            )
            quality = str(parse_report.get("quality", "none"))
            if quality not in quality_counts:
                quality = "none"
            quality_counts[quality] += 1
            create_chunks(
                project_id=project_id,
                document_id=str(document["id"]),
                upload_batch_id=upload_batch_id,
                chunks=[
                    {
                        "chunk_index": chunk.chunk_index,
                        "page": chunk.page,
                        "text": chunk.text,
                        "embedding": chunk.embedding,
                        "embedding_provider": chunk.embedding_provider,
                    }
                    for chunk in chunks
                ],
            )
            public_document = serialize_document_for_api(document)
            saved_documents.append(
                {
                    **public_document,
                    "pages_extracted": len(extraction.pages),
                    "chunks_indexed": len(chunks),
                    "parse_report": parse_report,
                }
            )

        return {
            "project_id": project_id,
            "upload_batch_id": upload_batch_id,
            "documents": saved_documents,
            "parse_report": {
                "documents_total": len(saved_documents),
                "quality_counts": quality_counts,
            },
            "embedding": {
                **embedding_service.describe(),
                "warnings": embedding_warnings,
            },
        }

    @router.get("/projects/{project_id}/documents")
    def list_project_documents(
        project_id: str,
        document_scope: str = Query(default="all", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "documents": [
                serialize_document_for_api(document)
                for document in list_documents(project_id, upload_batch_id=selected_batch_id)
            ],
        }

    @router.post("/projects/{project_id}/retrieve")
    def retrieve_project_chunks(
        project_id: str,
        payload: RetrievalRequest,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        chunks = list_chunks(project_id, upload_batch_id=selected_batch_id)
        if not chunks:
            return {"project_id": project_id, "upload_batch_id": selected_batch_id, "query": payload.query, "results": []}

        top_k = payload.top_k or settings.retrieval_top_k_default
        results, ranking_warnings = rank_chunks_by_query(
            chunks,
            payload.query,
            top_k,
            get_embedding_service=get_embedding_service,
        )
        embedding_service = get_embedding_service()
        response: dict[str, object] = {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "query": payload.query,
            "results": results,
            "embedding": embedding_service.describe(),
        }
        if ranking_warnings:
            response["warnings"] = ranking_warnings
        return response

    @router.post("/projects/{project_id}/reindex")
    def reindex_project_chunks(
        project_id: str,
        document_scope: str = Query(default="latest", pattern="^(latest|all)$"),
        upload_batch_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        _, selected_batch_id = resolve_project_upload_batch(
            project_id=project_id,
            document_scope=document_scope,
            upload_batch_id=upload_batch_id,
        )
        documents = list_documents(project_id, upload_batch_id=selected_batch_id)
        if not documents:
            raise HTTPException(status_code=404, detail="No documents found for requested re-index scope.")

        deleted_chunks = delete_chunks(project_id, upload_batch_id=selected_batch_id)
        embedding_service = get_embedding_service()
        embedding_warnings: list[dict[str, object]] = []
        quality_counts: dict[str, int] = {"good": 0, "low": 0, "none": 0}
        reindexed_documents: list[dict[str, object]] = []
        chunks_indexed_total = 0

        for document in documents:
            file_name = str(document.get("file_name") or "").strip()
            content_type = str(document.get("content_type") or "application/octet-stream")
            storage_path = str(document.get("storage_path") or "").strip()
            if not storage_path:
                raise HTTPException(status_code=422, detail=f"Missing storage path for document '{file_name}'.")

            path = Path(storage_path)
            if not path.exists():
                raise HTTPException(
                    status_code=422,
                    detail=f"Stored file for document '{file_name}' was not found at '{storage_path}'.",
                )

            content = path.read_bytes()
            extraction = extract_text_pages(content=content, content_type=content_type, file_name=file_name)
            chunks = chunk_pages(
                pages=extraction.pages,
                chunk_size_chars=settings.chunk_size_chars,
                chunk_overlap_chars=settings.chunk_overlap_chars,
                embedding_dim=settings.embedding_dim,
                embedding_service=embedding_service,
                embedding_warnings=embedding_warnings,
            )
            parse_report = build_parse_report(
                content=content,
                content_type=content_type,
                file_name=file_name,
                extraction=extraction,
                chunks=chunks,
            )
            quality = str(parse_report.get("quality", "none"))
            if quality not in quality_counts:
                quality = "none"
            quality_counts[quality] += 1

            document_upload_batch_id = selected_batch_id or str(document.get("upload_batch_id") or "legacy")
            create_chunks(
                project_id=project_id,
                document_id=str(document["id"]),
                upload_batch_id=document_upload_batch_id,
                chunks=[
                    {
                        "chunk_index": chunk.chunk_index,
                        "page": chunk.page,
                        "text": chunk.text,
                        "embedding": chunk.embedding,
                        "embedding_provider": chunk.embedding_provider,
                    }
                    for chunk in chunks
                ],
            )
            chunks_indexed_total += len(chunks)
            public_document = serialize_document_for_api(document)
            reindexed_documents.append(
                {
                    **public_document,
                    "pages_extracted": len(extraction.pages),
                    "chunks_indexed": len(chunks),
                    "parse_report": parse_report,
                }
            )

        return {
            "project_id": project_id,
            "upload_batch_id": selected_batch_id,
            "documents": reindexed_documents,
            "chunks_deleted": deleted_chunks,
            "chunks_indexed": chunks_indexed_total,
            "parse_report": {
                "documents_total": len(reindexed_documents),
                "quality_counts": quality_counts,
            },
            "embedding": {
                **embedding_service.describe(),
                "warnings": embedding_warnings,
            },
        }

    return router
