"""Evaluation Criteria model for storing assessment rules.

This content is configurable via admin web page and injected into
the system prompt for all judges during analysis.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from app.models.record import Base


class EvaluationCriteria(Base):
    """Evaluation criteria content for AI judges.

    Stores the scoring rules, dimensions, and guidelines.
    Admin can edit this content through the web interface.
    """

    __tablename__ = "evaluation_criteria"

    id = Column(Integer, primary_key=True, index=True)

    # Section name (e.g., "评分等级", "评分维度", "邮件模板")
    section_name = Column(String(100), nullable=False, unique=True)

    # The actual content (markdown format)
    content = Column(Text, nullable=False)

    # Description for admin UI
    description = Column(String(500), nullable=True)

    # Sort order for display
    sort_order = Column(Integer, default=0)

    # Is this section active?
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<EvaluationCriteria(id={self.id}, section={self.section_name})>"

    def to_prompt_text(self) -> str:
        """Format as text for prompt injection."""
        return f"### {self.section_name}\n{self.content}"