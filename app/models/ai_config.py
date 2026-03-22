"""AI Model Configuration model."""
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.models.record import Base


class AIConfig(Base):
    """Configuration for each AI judge (Judge 1, Judge 2, Judge 3)."""

    __tablename__ = "ai_configs"

    id = Column(Integer, primary_key=True, index=True)

    # Judge identifier: "Judge 1", "Judge 2", "Judge 3"
    name = Column(String(50), unique=True, nullable=False)

    # Provider: "anthropic", "openai", etc.
    provider = Column(String(50), nullable=False)

    # Model name: "claude-3-sonnet", "gpt-4", etc.
    model_name = Column(String(100), nullable=False)

    # API Key (stored encrypted in production, plain for now)
    api_key = Column(Text, nullable=False)

    # System prompt for this judge
    system_prompt = Column(Text, nullable=False)

    # Temperature (0-1): lower = more consistent, higher = more creative
    temperature = Column(Float, default=0.3)

    # Is this config active?
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<AIConfig(name={self.name}, provider={self.provider}, model={self.model_name})>"
