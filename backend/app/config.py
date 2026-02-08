from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Nebula API"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    request_id_header: str = "X-Request-ID"

    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.amazon.nova-pro-v1:0"
    bedrock_lite_model_id: str = "us.amazon.nova-lite-v1:0"
    agent_temperature: float = 0.1
    agent_max_tokens: int = 2048
    enable_agentic_orchestration_pilot: bool = False
    s3_bucket: str = "nebula-dev"
    vector_store: str = "local"
    database_url: str = "sqlite:///./nebula.db"
    storage_root: str = "data/uploads"
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200
    embedding_dim: int = 128
    retrieval_top_k_default: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
