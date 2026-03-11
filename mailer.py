"""
mailer.py — Compose and send an email via Gmail SMTP.

Supports:
  • Plain-text or HTML body
  • Multiple file attachments (MIME type auto-detected)
  • Loading a complete message from an .eml file
"""

import mimetypes
import re
import smtplib
import ssl
from email import encoders, message_from_bytes, policy
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 587  # STARTTLS


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def build_message(
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    attachments: list[str] | None = None,
    html_body: bool = False,
) -> MIMEMultipart:
    """
    Build a MIME email message from individual components.

    Args:
        from_email:   Sender address.
        to_email:     Recipient address.
        subject:      Email subject line.
        body:         Email body (plain text or HTML string).
        attachments:  Optional list of local file paths to attach.
        html_body:    Set to True when *body* contains HTML markup.

    Returns:
        A fully assembled MIMEMultipart message object.
    """
    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject

    subtype = "html" if html_body else "plain"
    msg.attach(MIMEText(body, subtype, "utf-8"))

    for path_str in (attachments or []):
        path = Path(path_str)
        if not path.is_file():
            print(f"  [warning] Attachment not found, skipping: {path_str}")
            continue
        _attach_file(msg, path)

    return msg


_DEAR_RE = re.compile(r"(Dear\s+)[^,\r\n]+(?=[,])", re.IGNORECASE)


def build_message_from_eml(
    from_email: str,
    to_email: str,
    eml_path: str,
    company_name: str | None = None,
    extra_attachments: list[str] | None = None,
) -> MIMEMultipart:
    """
    Re-compose a message from an .eml file, replacing From/To headers.

    The original Subject, body, and all attachments are preserved.
    If *company_name* is given, the greeting line ``Dear <old name>,`` is
    replaced with ``Dear <company_name>,`` in both the plain-text and HTML
    body parts.
    Any *extra_attachments* (local file paths) are appended after the .eml's
    own attachments.

    Args:
        from_email:        New sender address (replaces whatever is in the .eml).
        to_email:          Recipient address.
        eml_path:          Path to the .eml file on disk.
        company_name:      Company name to substitute into the greeting.
        extra_attachments: Optional list of local file paths to attach.

    Returns:
        A MIMEMultipart message ready to send.
    """
    eml_bytes = Path(eml_path).read_bytes()
    original = message_from_bytes(eml_bytes, policy=policy.default)

    subject = str(original.get("Subject", "(no subject)"))
    body = ""
    body_html = False
    attachment_parts: list[tuple[str, bytes, str]] = []  # (filename, data, mime)

    for part in original.walk():
        content_disp = str(part.get("Content-Disposition", ""))
        content_type = part.get_content_type()

        if part.is_multipart():
            continue

        if "attachment" in content_disp:
            filename = part.get_filename() or "attachment"
            data = part.get_payload(decode=True) or b""
            attachment_parts.append((filename, data, content_type))
        elif content_type == "text/html" and not body:
            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
            body_html = True
        elif content_type == "text/plain" and not body:
            body = part.get_payload(decode=True).decode("utf-8", errors="replace")

    if company_name:
        body = _DEAR_RE.sub(lambda m: f"{m.group(1)}{company_name}", body)

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject

    subtype = "html" if body_html else "plain"
    msg.attach(MIMEText(body, subtype, "utf-8"))

    for filename, data, mime_type in attachment_parts:
        maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    for path_str in (extra_attachments or []):
        path = Path(path_str)
        if not path.is_file():
            print(f"  [warning] Attachment not found, skipping: {path_str}")
            continue
        _attach_file(msg, path)

    return msg


def send_message(
    from_email: str,
    password: str,
    to_email: str,
    msg: MIMEMultipart,
) -> None:
    """
    Authenticate with Gmail SMTP and deliver *msg*.

    Requires a Gmail App Password (not your regular Google password):
    https://myaccount.google.com/apppasswords
    (Google Account → Security → 2-Step Verification → App passwords)
    """
    context = ssl.create_default_context()
    try:
        smtp_conn = smtplib.SMTP(GMAIL_HOST, GMAIL_PORT, timeout=15)
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"Could not connect to {GMAIL_HOST}:{GMAIL_PORT} — "
            "port 587 may be blocked by your network. "
            "Try on a different network (e.g. personal Wi-Fi or mobile hotspot)."
        ) from exc
    with smtp_conn:
        smtp_conn.ehlo()
        smtp_conn.starttls(context=context)
        smtp_conn.ehlo()
        smtp_conn.login(from_email, password)
        smtp_conn.sendmail(from_email, to_email, msg.as_string())


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _attach_file(msg: MIMEMultipart, path: Path) -> None:
    """Detect MIME type and attach a file to *msg*."""
    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    with path.open("rb") as fh:
        part = MIMEBase(maintype, subtype)
        part.set_payload(fh.read())

    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=path.name)
    msg.attach(part)
