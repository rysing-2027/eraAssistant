"""Product Knowledge model for AI evaluation context."""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from app.models.record import Base


class ProductKnowledge(Base):
    """Product knowledge content for AI evaluation.

    This content is loaded and injected into the system prompt
    for all judges during analysis.
    """

    __tablename__ = "product_knowledge"

    id = Column(Integer, primary_key=True, index=True)

    # Product line identifier (e.g., "时空壶X1", "PolyPal", "时空壶W4Pro")
    product_line = Column(String(100), nullable=False, index=True)

    # Knowledge title/section (e.g., "产品特点", "用户画像", "常见问题")
    title = Column(String(200), nullable=False)

    # The actual knowledge content
    content = Column(Text, nullable=False)

    # Sort order within product line
    sort_order = Column(Integer, default=0)

    # Is this knowledge active?
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<ProductKnowledge(id={self.id}, product_line={self.product_line}, title={self.title})>"

    def to_prompt_text(self) -> str:
        """Format as text for prompt injection."""
        return f"### {self.title}\n{self.content}"