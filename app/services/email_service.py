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
        from_email: str,
        from_name: str = None
    ):
        """Initialize Email service with SMTP credentials.

        Args:
            smtp_host: SMTP server host (e.g., smtp.gmail.com)
            smtp_port: SMTP server port (e.g., 587)
            smtp_user: SMTP username (usually email address)
            smtp_pass: SMTP password or app password
            from_email: Sender email address
            from_name: Sender display name (optional)
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.from_email = from_email
        self.from_name = from_name

    def send_email(
        self,
        to_email: str,
        subject: str,
        content: str,
        content_type: str = "html",
        cc: str = None
    ) -> EmailResult:
        """Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            content: Email body content
            content_type: "html" or "plain"
            cc: Carbon copy recipients, comma-separated

        Returns:
            EmailResult with success status
        """
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            # Format sender with display name if provided
            if self.from_name:
                msg["From"] = f"{self.from_name} <{self.from_email}>"
            else:
                msg["From"] = self.from_email
            msg["To"] = to_email
            msg["Subject"] = subject

            # Add CC if provided
            recipients = [to_email]
            if cc:
                msg["Cc"] = cc
                # Parse CC emails and add to recipients
                cc_emails = [email.strip() for email in cc.split(",") if email.strip()]
                recipients.extend(cc_emails)

            # Attach content
            mime_type = "html" if content_type == "html" else "plain"
            msg.attach(MIMEText(content, mime_type, "utf-8"))

            # Connect and send (SSL for port 465)
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.from_email, recipients, msg.as_string())

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
        email_content: str,
        doc_link: str = None,
        cc: str = None,
        view_token: str = None
    ) -> EmailResult:
        """Send evaluation result email to employee.

        Args:
            to_email: Employee's email address
            employee_name: Employee's name
            email_content: Generated email content from AI (Markdown)
            doc_link: Optional Feishu document link to include
            cc: Carbon copy recipients, comma-separated
            view_token: Optional view token for report viewer link

        Returns:
            EmailResult with success status
        """
        subject = f"产品体验报告评估结果 - {employee_name}"

        # Convert Markdown to HTML with nice styling
        html_content = markdown.markdown(
            email_content,
            extensions=["tables", "fenced_code"]
        )

        # Build report viewer link if view_token provided
        report_link_html = ""
        if view_token:
            from config.settings import get_settings
            settings = get_settings()
            base_url = settings.app_base_url.rstrip("/")
            if base_url and not base_url.startswith(("http://", "https://")):
                base_url = f"https://{base_url}"
            report_url = f"{base_url}/report/{view_token}"
            report_link_html = f"""
            <div style="margin-bottom: 24px; padding: 16px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; text-align: center;">
                <a href="{report_url}" style="color: #fff; text-decoration: none; font-size: 16px; font-weight: 600;">📊 点击查看完整分析报告</a>
            </div>
            """

        # Add document link section if provided
        doc_link_html = ""
        if doc_link:
            doc_link_html = f"""
            <div style="margin-top: 30px; padding: 15px; background-color: #f8f9fa; border-radius: 8px; border-left: 4px solid #3498db;">
                <p style="margin: 0; color: #2c3e50; font-weight: 500;">📎 原始报告文件：</p>
                <p style="margin: 10px 0 0 0;">
                    <a href="{doc_link}" style="color: #3498db; text-decoration: none;">点击查看飞书文档 →</a>
                </p>
            </div>
            """

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
            {report_link_html}
            {html_content}
            {doc_link_html}
            <div style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #eee; color: #999; font-size: 12px;">
                评估由多个AI大模型基于评估规则产生，供参考。
            </div>
        </body>
        </html>
        """

        return self.send_email(
            to_email=to_email,
            subject=subject,
            content=styled_html,
            content_type="html",
            cc=cc
        )