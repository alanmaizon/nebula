from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Nebula API"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    cors_allow_credentials: bool = True
    log_level: str = "INFO"
    request_id_header: str = "X-Request-ID"
    auth_enabled: bool = False
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_issuer: str = ""

    aws_region: str = "us-east-1"
    # Default to region-agnostic foundation model IDs. In some regions/accounts, on-demand Bedrock
    # invocation may require an inference profile ID/ARN (e.g. `eu.amazon.nova-pro-v1:0`).
    bedrock_model_id: str = "amazon.nova-pro-v1:0"
    bedrock_lite_model_id: str = "amazon.nova-lite-v1:0"
    bedrock_validate_model_ids_on_startup: bool = False
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_mode: str = "hash"
    agent_temperature: float = 0.1
    agent_max_tokens: int = 2048
    enable_agentic_orchestration_pilot: bool = False
    storage_backend: str = "local"  # local|s3
    s3_bucket: str = "nebula-dev"
    s3_prefix: str = "nebula"
    vector_store: str = "local"
    # MVP default is sqlite; production should use RDS Postgres (e.g. postgresql://...).
    database_url: str = "sqlite:///./nebula.db"
    storage_root: str = "data/uploads"
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    embedding_dim: int = 128
    retrieval_top_k_default: int = 5
    extraction_context_max_chunks: int = 20
    extraction_context_max_chars_per_chunk: int = 600
    extraction_context_max_total_chars: int = 4200
    extraction_window_size_chunks: int = 14
    extraction_window_overlap_chunks: int = 4
    extraction_window_max_passes: int = 4
    judge_eval_min_overall_score: float = 0.65
    judge_eval_min_dimension_score: float = 0.55
    judge_eval_block_on_fail: bool = False
    max_upload_files: int = 20
    max_upload_file_bytes: int = 10 * 1024 * 1024
    max_upload_batch_bytes: int = 25 * 1024 * 1024

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
