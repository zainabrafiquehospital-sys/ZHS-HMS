"""Outbound transactional email — SMTP send plus the plain-HTML templates
this build's self-service signup/approval/password-reset flows need.
Lives in `app/shared`, not inside the `auth` module, mirroring
`app/shared/printing/service.py`'s exact rationale: this is cross-cutting
infrastructure a later module could equally need (appointment reminders,
etc.), not an auth-specific concern — auth is simply its first caller.

Same authorization boundary as the Central Print Service: this module
decides nothing about *whether* an email should be sent (that's each
caller's business logic) or *what* it says beyond rendering — it only
ever turns already-decided content into a sent message.

No third-party email SDK — the stdlib `smtplib`/`email.message` is
sufficient for sending a handful of transactional emails via Gmail SMTP
and avoids adding a new dependency for it. `smtplib` is blocking I/O, so
`EmailService.send` offloads it via `asyncio.to_thread`, the same pattern
`PasswordService` already uses for Argon2id (see that module's docstring)."""

import asyncio
import html
import smtplib
from email.message import EmailMessage

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


_SHELL_STYLE = """
  body { margin:0; padding:0; background:#f4f4f5; font-family:Arial,Helvetica,sans-serif; }
  .wrap { background:#f4f4f5; padding:32px 0; }
  .card { background:#ffffff; border-radius:8px; overflow:hidden; border:1px solid #e4e4e7; }
  .header { background:#111827; padding:20px 28px; }
  .header span { color:#ffffff; font-size:16px; font-weight:bold; }
  .body { padding:28px; color:#18181b; font-size:14px; line-height:1.6; }
  .footer { padding:16px 28px; background:#fafafa; border-top:1px solid #e4e4e7; }
  .footer span { color:#71717a; font-size:12px; }
  p { margin:0 0 16px; }
  .code { display:inline-block; padding:12px 24px; background:#f4f4f5; border-radius:6px;
    font-size:28px; font-weight:bold; letter-spacing:6px; color:#111827; }
  .button { display:inline-block; padding:10px 20px; background:#111827; color:#ffffff;
    text-decoration:none; border-radius:6px; font-weight:bold; }
"""


def _email_shell(hospital_name: str, body_html: str) -> str:
    """Wraps `body_html` in a minimal, self-contained layout shared by
    every template below — plain HTML/CSS only (no external stylesheet,
    no images, no tracking pixel), matching this project's "no PDF/
    email SDK dependency" scope decision for the Central Print Service's
    own templates. The `<style>` block is safe (not sanitized against
    user input) because it is 100% fixed, developer-authored CSS — no
    caller-supplied value is ever interpolated into it, only into
    `body_html`, which is built entirely from `_escape`d values by every
    caller below."""
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><style>{_SHELL_STYLE}</style></head>
<body>
  <table role="presentation" width="100%" class="wrap"><tr><td align="center">
    <table role="presentation" width="480" class="card">
      <tr><td class="header"><span>{_escape(hospital_name)}</span></td></tr>
      <tr><td class="body">{body_html}</td></tr>
      <tr><td class="footer">
        <span>This is an automated message — please do not reply directly to this email.</span>
      </td></tr>
    </table>
  </td></tr></table>
</body>
</html>"""


def render_otp_email(
    *,
    hospital_name: str,
    recipient_name: str,
    code: str,
    purpose_label: str,
    expires_in_minutes: int,
) -> str:
    """`purpose_label` is a short human phrase ("verify your email",
    "reset your password") distinguishing the two flows OtpPurpose
    covers — the code and expiry mechanics are identical either way, so
    one template serves both rather than duplicating it."""
    body = f"""
      <p>Hi {_escape(recipient_name)},</p>
      <p>Use the code below to {_escape(purpose_label)}:</p>
      <p style="text-align:center;"><span class="code">{_escape(code)}</span></p>
      <p>This code expires in {expires_in_minutes} minutes. If you didn't request this,
        you can safely ignore this email.</p>
    """
    return _email_shell(hospital_name, body)


def render_signup_approved_email(*, hospital_name: str, recipient_name: str, login_url: str) -> str:
    body = f"""
      <p>Hi {_escape(recipient_name)},</p>
      <p>Your {_escape(hospital_name)} account has been approved by an administrator —
        you can now sign in.</p>
      <p style="text-align:center;">
        <a href="{_escape(login_url)}" class="button">Sign In</a>
      </p>
    """
    return _email_shell(hospital_name, body)


class EmailService:
    """Constructed fresh per request from `Depends(get_settings)` — same
    reasoning as `TokenService` (see auth/dependencies.py): no expensive
    setup to amortize via `@lru_cache`, and `Settings` isn't hashable
    anyway, which would break `lru_cache`'s cache-key computation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        """Sends via SMTP if `smtp_host` is configured; otherwise logs the
        email's content at INFO level and returns — the documented dev
        fallback so the rest of the signup/OTP/reset flows are fully
        testable before real Gmail App Password credentials exist (see
        core/config.py's `smtp_host` docstring)."""
        if not self._settings.smtp_host:
            logger.info(
                "email_not_sent_smtp_unconfigured",
                to=to,
                subject=subject,
                html_body=html_body,
            )
            return
        await asyncio.to_thread(self._send_sync, to, subject, html_body)

    def _send_sync(self, to: str, subject: str, html_body: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{self._settings.smtp_from_name} <{self._settings.smtp_from_email}>"
        message["To"] = to
        message.set_content("This email requires an HTML-capable email client to view.")
        message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=10) as smtp:
            if self._settings.smtp_use_tls:
                smtp.starttls()
            if self._settings.smtp_username and self._settings.smtp_password:
                smtp.login(self._settings.smtp_username, self._settings.smtp_password)
            smtp.send_message(message)
