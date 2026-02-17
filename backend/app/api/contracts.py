from typing import TypedDict

from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)


class GenerateSectionRequest(BaseModel):
    section_key: str = Field(..., min_length=1, max_length=120)
    top_k: int | None = Field(default=None, ge=1, le=20)


class CoverageComputeRequest(BaseModel):
    section_key: str = Field(default="Need Statement", min_length=1, max_length=120)


class GenerateFullDraftRequest(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=20)
    max_revision_rounds: int = Field(default=1, ge=0, le=3)
    context_brief: str | None = Field(default=None, max_length=2000)


class ExportContext(TypedDict):
    drafts: dict[str, dict[str, object]]
    requirements_payload: dict[str, object] | None
    coverage_payload: dict[str, object] | None
    documents_payload: list[dict[str, object]]
    artifacts_used: list[dict[str, object]]
    artifact_timestamps: list[str]
