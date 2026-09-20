"""Email dispatch service for QMAFIB reports.

Packages all files and folders in backend/output/ into an email with both
a consolidated ZIP archive (preserving directory structure) and individual
file attachments, validated with RegExp, and sent via Python smtplib.
"""
from __future__ import annotations

import email.utils
import io
import mimetypes
import os
import re
import smtplib
import ssl
import zipfile
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Search and load .env from backend directory or workspace root
_CURRENT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _CURRENT_DIR.parent
_WORKSPACE_DIR = _BACKEND_DIR.parent

load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_WORKSPACE_DIR / ".env")
load_dotenv()

# Standard RFC 5322 compatible email regular expression with strict domain label validation
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9]+([.-][a-zA-Z0-9]+)*\.[a-zA-Z]{2,}$"
)


def validate_email(email_address: str) -> bool:
    """Validate an email address against standard regular expression."""
    if not email_address or not isinstance(email_address, str):
        return False
    return bool(EMAIL_REGEX.match(email_address.strip()))


def get_output_dir() -> Path:
    """Return the path to the backend/output directory."""
    output_dir = _BACKEND_DIR / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def collect_output_files(output_dir: Path) -> list[dict[str, Any]]:
    """Scan backend/output for all files and folders.

    Excludes the internal 'emails/' directory (used for storing email logs)
    and temporary files.
    """
    collected: list[dict[str, Any]] = []
    if not output_dir.exists():
        return collected

    for root, _, filenames in os.walk(output_dir):
        rel_root = os.path.relpath(root, output_dir)
        # Skip internal emails storage directory
        if rel_root == "emails" or rel_root.startswith("emails" + os.sep):
            continue

        for filename in sorted(filenames):
            # Skip hidden and temporary files
            if filename.startswith(".") or filename.endswith(".tmp"):
                continue

            full_path = Path(root) / filename
            rel_path = os.path.relpath(full_path, output_dir)
            size_bytes = full_path.stat().st_size

            collected.append({
                "filename": filename,
                "rel_path": rel_path.replace("\\", "/"),
                "full_path": full_path,
                "size_bytes": size_bytes,
                "size_display": _format_size(size_bytes),
            })

    return collected


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable units."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def build_zip_archive(output_dir: Path, files: list[dict[str, Any]]) -> bytes:
    """Package all output files and folder hierarchy into an in-memory ZIP archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f["full_path"], arcname=f["rel_path"])
    buffer.seek(0)
    return buffer.getvalue()


def create_report_email(
    to_email: str,
    files: list[dict[str, Any]],
    zip_data: bytes,
    from_email: str,
) -> MIMEMultipart:
    """Assemble a rich multipart MIME email with HTML body, ZIP, and attachments."""
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"QMAFIB Market Regime & Backtest Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="qmafib.local")

    # Alternative container for plain text and HTML versions
    alt_part = MIMEMultipart("alternative")

    # Plain text version
    file_list_txt = "\n".join([f" - {f['rel_path']} ({f['size_display']})" for f in files])
    text_content = (
        f"QMAFIB Quantitative Analytics & Market Regime Report\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"Attached are all generated output files, plots, and models from the QMAFIB platform.\n"
        f"All files and directory hierarchies are also consolidated into the attached 'output_report.zip'.\n\n"
        f"Files included ({len(files)} total):\n"
        f"{file_list_txt}\n\n"
        f"—\n"
        f"QMAFIB Platform | Quantitative Multi-Asset Financial Intelligence & Backtesting\n"
    )
    alt_part.attach(MIMEText(text_content, "plain", "utf-8"))

    # HTML version
    file_rows_html = "".join([
        f"<tr>"
        f"<td style='padding: 8px 12px; border-bottom: 1px solid #1f2c45; font-family: monospace; color: #4f9cf9;'>{f['rel_path']}</td>"
        f"<td style='padding: 8px 12px; border-bottom: 1px solid #1f2c45; text-align: right; color: #94a3b8;'>{f['size_display']}</td>"
        f"</tr>"
        for f in files
    ])

    html_content = f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0b1120; color: #e2e8f0; margin: 0; padding: 20px; }}
  .card {{ background-color: #111a2e; border: 1px solid #1f2c45; border-radius: 10px; max-width: 640px; margin: 0 auto; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
  .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 24px; border-bottom: 1px solid #1f2c45; }}
  .title {{ margin: 0; font-size: 20px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px; }}
  .subtitle {{ margin: 6px 0 0; font-size: 13px; color: #94a3b8; }}
  .content {{ padding: 24px; }}
  .badge {{ display: inline-block; background: rgba(79, 156, 249, 0.15); color: #4f9cf9; border: 1px solid rgba(79, 156, 249, 0.35); padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }}
  th {{ background: #0f172a; color: #94a3b8; text-align: left; padding: 8px 12px; border-bottom: 1px solid #1f2c45; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .footer {{ padding: 16px 24px; border-top: 1px solid #1f2c45; font-size: 11px; color: #64748b; text-align: center; background: #0f172a; }}
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1 class="title">QMAFIB Platform Report</h1>
      <p class="subtitle">Quantitative Multi-Asset Financial Intelligence &amp; Backtesting</p>
    </div>
    <div class="content">
      <span class="badge">Report Archive Generated</span>
      <p style="margin-top: 0; font-size: 14px; line-height: 1.6; color: #cbd5e1;">
        All files and folders from the <code>backend/output</code> folder are attached to this email.
        A complete archive is also bundled as <strong>output_report.zip</strong> preserving full folder hierarchy.
      </p>
      <table>
        <thead>
          <tr>
            <th>File / Relative Path</th>
            <th style="text-align: right;">Size</th>
          </tr>
        </thead>
        <tbody>
          {file_rows_html}
        </tbody>
      </table>
    </div>
    <div class="footer">
      Generated automatically by QMAFIB Platform &bull; Research &amp; Historical Analysis
    </div>
  </div>
</body>
</html>
"""
    alt_part.attach(MIMEText(html_content, "html", "utf-8"))
    msg.attach(alt_part)

    # 1. Attach the consolidated ZIP archive
    zip_part = MIMEApplication(zip_data, _subtype="zip")
    zip_part.add_header("Content-Disposition", "attachment", filename="output_report.zip")
    msg.attach(zip_part)

    # 2. Attach individual files directly
    for f in files:
        file_path = f["full_path"]
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        maintype, subtype = mime_type.split("/", 1)
        try:
            with open(file_path, "rb") as fp:
                file_bytes = fp.read()

            if maintype == "text":
                part = MIMEText(file_bytes.decode("utf-8", errors="replace"), _subtype=subtype)
            elif maintype == "image":
                part = MIMEBase(maintype, subtype)
                part.set_payload(file_bytes)
                email.encoders.encode_base64(part)
            else:
                part = MIMEApplication(file_bytes, _subtype=subtype)

            # Sanitize attachment filename (flatten folder names if in subfolder)
            attachment_name = f["rel_path"].replace("/", "_").replace("\\", "_")
            part.add_header("Content-Disposition", "attachment", filename=attachment_name)
            msg.attach(part)
        except Exception:
            # If an individual file fails to attach, the ZIP archive already contains it
            continue

    return msg


def _display_path(path: Path) -> str:
    """Render a saved path relative to ``backend/`` when it lives there.

    ``relative_to`` raises ``ValueError`` for anything outside that tree, which
    reached the route as a 400 and reported "invalid email address" for a
    perfectly valid one. The tidier relative form is a presentation detail and
    should never be able to fail the send that already happened.
    """
    try:
        return str(path.relative_to(_BACKEND_DIR))
    except ValueError:
        return str(path)


def send_report_email(to_email: str) -> dict[str, Any]:
    """Validate email, package backend/output files, and send via SMTP.

    The recipient is checked against the allowlist here as well as in the route.
    That is deliberate duplication: this function is exported, it attaches
    everything under ``backend/output``, and the next caller to import it will
    not have the route's dependencies in front of it.
    """
    from .security import recipient_allowed

    clean_email = to_email.strip()
    if not validate_email(clean_email):
        raise ValueError(f"Invalid email address: '{to_email}'. Must match regex format.")
    if not recipient_allowed(clean_email):
        raise PermissionError(
            f"'{clean_email}' is not an approved report recipient. "
            "Set REPORT_EMAIL_ALLOWLIST to authorise it."
        )

    output_dir = get_output_dir()
    files = collect_output_files(output_dir)
    zip_data = build_zip_archive(output_dir, files)

    # SMTP configuration
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_from = os.environ.get("SMTP_FROM", "").strip() or smtp_user or "noreply@qmafib.local"
    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
    smtp_use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() in ("true", "1", "yes") or smtp_port == 465

    msg = create_report_email(clean_email, files, zip_data, from_email=smtp_from)

    # Dispatch via SMTP
    sent_via_smtp = False
    smtp_error = None

    if smtp_host:
        try:
            if smtp_use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as server:
                    if smtp_user and smtp_password:
                        server.login(smtp_user, smtp_password)
                    server.send_message(msg)
                    sent_via_smtp = True
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    if smtp_use_tls:
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                    if smtp_user and smtp_password:
                        server.login(smtp_user, smtp_password)
                    server.send_message(msg)
                    sent_via_smtp = True
        except (smtplib.SMTPException, OSError) as e:
            smtp_error = str(e)

    # Always save a local copy in backend/output/emails/ for auditing
    emails_log_dir = output_dir / "emails"
    emails_log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sanitized_email = re.sub(r"[^a-zA-Z0-9_.-]", "_", clean_email)
    eml_path = emails_log_dir / f"{timestamp}_{sanitized_email}.eml"
    with open(eml_path, "wb") as f:
        f.write(msg.as_bytes())

    if not sent_via_smtp and smtp_error:
        raise RuntimeError(f"SMTP dispatch failed ({smtp_host}:{smtp_port}): {smtp_error}")

    return {
        "status": "success",
        "message": f"Report successfully sent to {clean_email}",
        "recipient": clean_email,
        "files_count": len(files),
        "files": [f["rel_path"] for f in files],
        "zip_size_bytes": len(zip_data),
        "saved_local_copy": _display_path(eml_path),
    }
