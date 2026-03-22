"""Email Service for ERA Assistant.

This module handles sending emails via SMTP:
- Send evaluation results to employees
- Support HTML email content
- Convert Markdown to HTML
"""
import smtplib
import markdown
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from dataclasses import dataclass


@dataclass
class EmailResult:
    """Result of sending an email."""
    success: bool
    error_message: Optional[str] = None


class EmailService:
    """Service for sending emails via SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_pass: str,
        from_email: str
    ):
        """Initialize Email service with SMTP credentials.

        Args:
            smtp_host: SMTP server host (e.g., smtp.gmail.com)
            smtp_port: SMTP server port (e.g., 587)
            smtp_user: SMTP username (usually email address)
            smtp_pass: SMTP password or app password
            from_email: Sender email address
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_email = from_email

    def send_email(
        self,
        to_email: str,
        subject: str,
        content: str,
        content_type: str = "html"
    ) -> EmailResult:
        """Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            content: Email body content
            content_type: "html" or "plain"

        Returns:
            EmailResult with success status
        """
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = subject

            # Attach content
            mime_type = "html" if content_type == "html" else "plain"
            msg.attach(MIMEText(content, mime_type, "utf-8"))

            # Connect and send (SSL for port 465)
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.from_email, to_email, msg.as_string())

            return EmailResult(success=True)

        except smtplib.SMTPAuthenticationError as e:
            return EmailResult(
                success=False,
                error_message=f"SMTP authentication failed: {str(e)}"
            )
        except smtplib.SMTPException as e:
            return EmailResult(
                success=False,
                error_message=f"SMTP error: {str(e)}"
            )
        except Exception as e:
            return EmailResult(
                success=False,
                error_message=f"Failed to send email: {str(e)}"
            )

    def send_evaluation_email(
        self,
        to_email: str,
        employee_name: str,
        email_content: str
    ) -> EmailResult:
        """Send evaluation result email to employee.

        Args:
            to_email: Employee's email address
            employee_name: Employee's name
            email_content: Generated email content from AI (Markdown)

        Returns:
            EmailResult with success status
        """
        subject = f"产品体验报告评估结果 - {employee_name}"

        # Convert Markdown to HTML with nice styling
        html_content = markdown.markdown(
            email_content,
            extensions=["tables", "fenced_code"]
        )

        # Wrap with basic styling
        styled_html = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                h3 {{
                    color: #2c3e50;
                    border-bottom: 2px solid #3498db;
                    padding-bottom: 8px;
                }}
                h4 {{
                    color: #34495e;
                }}
                ul, ol {{
                    padding-left: 20px;
                }}
                li {{
                    margin-bottom: 8px;
                }}
                strong {{
                    color: #2c3e50;
                }}
                hr {{
                    border: none;
                    border-top: 1px solid #eee;
                    margin: 20px 0;
                }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

        return self.send_email(
            to_email=to_email,
            subject=subject,
            content=styled_html,
            content_type="html"
        )