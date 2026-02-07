from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.db import (
    create_chunks,
    create_document,
    create_project,
    get_project,
    init_db,
    list_chunks,
    list_documents,
)
from app.retrieval import chunk_pages, cosine_similarity, embed_text, extract_text_pages


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    Path(settings.storage_root).mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": "grantsmith-backend", "status": "running"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/projects")
    def create_project_endpoint(payload: ProjectCreateRequest) -> dict[str, str]:
        return create_project(payload.name)

    @app.post("/projects/{project_id}/upload")
    async def upload_documents(project_id: str, files: list[UploadFile] = File(...)) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        saved_documents: list[dict[str, object]] = []
        project_folder = Path(settings.storage_root) / project_id
        project_folder.mkdir(parents=True, exist_ok=True)

        for upload in files:
            incoming_name = upload.filename or "upload.bin"
            safe_name = Path(incoming_name).name
            content = await upload.read()
            destination = project_folder / f"{uuid4()}_{safe_name}"
            destination.write_bytes(content)

            document = create_document(
                project_id=project_id,
                file_name=safe_name,
                content_type=upload.content_type or "application/octet-stream",
                storage_path=str(destination),
                size_bytes=len(content),
            )
            pages = extract_text_pages(
                content=content,
                content_type=str(document["content_type"]),
                file_name=safe_name,
            )
            chunks = chunk_pages(
                pages=pages,
                chunk_size_chars=settings.chunk_size_chars,
                chunk_overlap_chars=settings.chunk_overlap_chars,
                embedding_dim=settings.embedding_dim,
            )
            create_chunks(
                project_id=project_id,
                document_id=str(document["id"]),
                chunks=[
                    {
                        "chunk_index": chunk.chunk_index,
                        "page": chunk.page,
                        "text": chunk.text,
                        "embedding": chunk.embedding,
                    }
                    for chunk in chunks
                ],
            )
            saved_documents.append(
                {
                    **document,
                    "pages_extracted": len(pages),
                    "chunks_indexed": len(chunks),
                }
            )

        return {"project_id": project_id, "documents": saved_documents}

    @app.get("/projects/{project_id}/documents")
    def list_project_documents(project_id: str) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"project_id": project_id, "documents": list_documents(project_id)}

    @app.post("/projects/{project_id}/retrieve")
    def retrieve_project_chunks(project_id: str, payload: RetrievalRequest) -> dict[str, object]:
        project = get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        chunks = list_chunks(project_id)
        if not chunks:
            return {"project_id": project_id, "query": payload.query, "results": []}

        query_embedding = embed_text(payload.query, settings.embedding_dim)
        scored_results: list[dict[str, object]] = []
        for chunk in chunks:
            scored_results.append(
                {
                    "chunk_id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "file_name": chunk["file_name"],
                    "page": chunk["page"],
                    "text": chunk["text"],
                    "score": cosine_similarity(query_embedding, chunk["embedding"]),
                }
            )

        top_k = payload.top_k or settings.retrieval_top_k_default
        scored_results.sort(key=lambda item: float(item["score"]), reverse=True)
        return {"project_id": project_id, "query": payload.query, "results": scored_results[:top_k]}

    return app


app = create_app()
