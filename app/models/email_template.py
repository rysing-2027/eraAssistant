"""Email Template model for customizing evaluation emails.

This content is configurable via admin web page and injected into
the main judge system prompt for email generation.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.sql import func
from app.models.record import Base


class EmailTemplate(Base):
    """Email template for evaluation result emails.

    Admin can customize the email format through the web interface.
    Supports markdown format with placeholders.
    """

    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, index=True)

    # Template name (e.g., "default", "quarterly_review")
    name = Column(String(100), nullable=False, unique=True)

    # Template content (markdown with placeholders)
    # Supported placeholders: {员工名}, {总分}, {等级}, {各维度评分}, {主要问题}, {改进建议}
    content = Column(Text, nullable=False)

    # Description for admin UI
    description = Column(String(500), nullable=True)

    # Is this the active template?
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<EmailTemplate(id={self.id}, name={self.name})>"

    def to_prompt_text(self) -> str:
        """Format as text for prompt injection."""
        return self.content