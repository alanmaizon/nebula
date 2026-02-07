from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Nebula API"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    aws_region: str = "us-east-1"
    bedrock_model_id: str = ""
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
