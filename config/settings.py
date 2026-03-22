"""Application configuration settings."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "sqlite:///./data/era.db"

    # Feishu API
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_base_token: str = ""
    feishu_table_id: str = ""
    feishu_folder_token: str = ""  # Target folder for uploading xlsx files

    # Email (SMTP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_email: str = ""
    email_cc: str = ""  # 抄送邮箱，多个用逗号分隔

    # AI Model API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    dashscope_api_key: str = ""  # DashScope API key for Qwen models
    deepseek_api_key: str = ""
    ark_api_key: str = ""  # 火山方舟 API key for Doubao models

    # Webhook Security
    webhook_token: str = ""  # Token for Feishu automation webhook verification

    # Admin Panel
    admin_username: str = "admin"
    admin_password: str = ""  # Set in .env
    admin_secret_key: str = ""  # For session signing, generate random string

    # LangSmith (LangChain monitoring)
    langsmith_tracing: bool = True
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""  # Get from https://smith.langchain.com
    langsmith_project: str = "era"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False  # Allow FEISHU_APP_ID or feishu_app_id


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance.

    Using lru_cache ensures we only load .env file once.
    """
    return Settings()
