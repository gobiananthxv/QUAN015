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
        if rel_root == "emails" or rel_root.startswith("emails" + os.sep):
            continue

        for filename in sorted(filenames):
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


def collect_csv_files(output_dir: Path) -> list[dict[str, Any]]:
    """Scan output_dir for all CSV files."""
    collected: list[dict[str, Any]] = []
    if not output_dir.exists():
        return collected

    for root, _, filenames in os.walk(output_dir):
        rel_root = os.path.relpath(root, output_dir)
        if rel_root == "emails" or rel_root.startswith("emails" + os.sep):
            continue

        for filename in sorted(filenames):
            if filename.startswith(".") or filename.endswith(".tmp"):
                continue
            if not filename.lower().endswith(".csv"):
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


def collect_image_files(output_dir: Path) -> list[dict[str, Any]]:
    """Scan output_dir for all image and plot files."""
    image_extensions = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp"}
    collected: list[dict[str, Any]] = []
    if not output_dir.exists():
        return collected

    for root, _, filenames in os.walk(output_dir):
        rel_root = os.path.relpath(root, output_dir)
        if rel_root == "emails" or rel_root.startswith("emails" + os.sep):
            continue

        for filename in sorted(filenames):
            if filename.startswith(".") or filename.endswith(".tmp"):
                continue

            ext = Path(filename).suffix.lower()
            is_in_image_folder = rel_root in ("plots", "images") or rel_root.startswith(
                ("plots" + os.sep, "images" + os.sep)
            )
            if ext in image_extensions or (is_in_image_folder and ext in (".png", ".jpg", ".jpeg", ".svg")):
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


def get_report_pdf(output_dir: Path) -> dict[str, Any] | None:
    """Find Report.pdf in output_dir if present."""
    if not output_dir.exists():
        return None

    # Check for direct match
    direct_pdf = output_dir / "Report.pdf"
    if direct_pdf.is_file():
        size_bytes = direct_pdf.stat().st_size
        return {
            "filename": "Report.pdf",
            "rel_path": "Report.pdf",
            "full_path": direct_pdf,
            "size_bytes": size_bytes,
            "size_display": _format_size(size_bytes),
        }

    # Search for any PDF in output_dir (excluding emails)
    for root, _, filenames in os.walk(output_dir):
        rel_root = os.path.relpath(root, output_dir)
        if rel_root == "emails" or rel_root.startswith("emails" + os.sep):
            continue
        for filename in sorted(filenames):
            if filename.lower().endswith(".pdf"):
                full_path = Path(root) / filename
                rel_path = os.path.relpath(full_path, output_dir)
                size_bytes = full_path.stat().st_size
                return {
                    "filename": filename,
                    "rel_path": rel_path.replace("\\", "/"),
                    "full_path": full_path,
                    "size_bytes": size_bytes,
                    "size_display": _format_size(size_bytes),
                }

    return None


def build_zip_archive(output_dir: Path, files: list[dict[str, Any]]) -> bytes:
    """Package given files into an in-memory ZIP archive preserving relative paths."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f["full_path"], arcname=f["rel_path"])
    buffer.seek(0)
    return buffer.getvalue()


def build_csv_zip(output_dir: Path, csv_files: list[dict[str, Any]] | None = None) -> bytes:
    """Package all CSV files into an in-memory ZIP archive."""
    if csv_files is None:
        csv_files = collect_csv_files(output_dir)
    return build_zip_archive(output_dir, csv_files)


def build_images_zip(output_dir: Path, image_files: list[dict[str, Any]] | None = None) -> bytes:
    """Package all image and plot files into an in-memory ZIP archive."""
    if image_files is None:
        image_files = collect_image_files(output_dir)
    return build_zip_archive(output_dir, image_files)


def extract_report_findings(output_dir: Path) -> dict[str, Any]:
    """Extract quantitative findings and regime metrics from output files."""
    findings: dict[str, Any] = {
        "current_regime": "Unknown",
        "current_regime_model": "N/A",
        "regime_date": None,
        "strategy_recommendation": None,
        "backtest_summary": None,
        "forecast_summary": None,
        "details": [],
    }

    if not output_dir.exists():
        return findings

    # 1. Check HMM / GMM regimes for current active regime
    for model_name, filename in [("HMM", "SPY_hmm_regimes.csv"), ("GMM", "SPY_gmm_regimes.csv")]:
        regimes_path = output_dir / filename
        if regimes_path.is_file():
            try:
                with open(regimes_path, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                if len(lines) > 1:
                    last_line = lines[-1].split(",")
                    regime_date = last_line[0]
                    regime_name = last_line[1]
                    findings["current_regime"] = regime_name
                    findings["current_regime_model"] = model_name
                    findings["regime_date"] = regime_date
                    findings["details"].append(
                        f"Latest {model_name} Market Regime ({regime_date}): {regime_name}"
                    )
                    break
            except Exception:
                pass

    # 2. Strategy Parameters
    strat_path = output_dir / "strategy_params.csv"
    if strat_path.is_file():
        try:
            with open(strat_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            if len(lines) > 1:
                header = [c.strip() for c in lines[0].split(",")]
                active_regime = findings["current_regime"]
                matched_row = None
                for line in lines[1:]:
                    parts = [p.strip().strip('"') for p in line.split(",")]
                    if len(parts) >= len(header) and parts[0].lower() == active_regime.lower():
                        matched_row = parts
                        break
                if matched_row:
                    strat_info = {
                        "regime": matched_row[0],
                        "position_size": matched_row[1],
                        "stop_loss": matched_row[2],
                        "take_profit": matched_row[3],
                        "signal_filter": matched_row[4],
                        "description": matched_row[5] if len(matched_row) > 5 else "",
                    }
                    findings["strategy_recommendation"] = strat_info
                    findings["details"].append(
                        f"Adaptive Strategy ({active_regime}): Position Size {strat_info['position_size']}, "
                        f"Stop Loss {strat_info['stop_loss']}, Take Profit {strat_info['take_profit']}, "
                        f"Filter: {strat_info['signal_filter']}"
                    )
        except Exception:
            pass

    # 3. Backtest performance highlights
    folds_path = output_dir / "SPY_hmm_folds.csv"
    if not folds_path.is_file():
        folds_path = output_dir / "SPY_gmm_folds.csv"
    if folds_path.is_file():
        try:
            with open(folds_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            if len(lines) > 1:
                header = [c.strip() for c in lines[0].split(",")]
                outperf_idx = header.index("outperformance_%") if "outperformance_%" in header else -1
                if outperf_idx != -1:
                    outperfs = []
                    for line in lines[1:]:
                        parts = line.split(",")
                        if len(parts) > outperf_idx:
                            try:
                                outperfs.append(float(parts[outperf_idx]))
                            except ValueError:
                                pass
                    if outperfs:
                        avg_outperf = sum(outperfs) / len(outperfs)
                        win_rate = sum(1 for x in outperfs if x > 0) / len(outperfs) * 100
                        findings["backtest_summary"] = {
                            "total_folds": len(outperfs),
                            "avg_outperformance_pct": round(avg_outperf, 2),
                            "win_rate_pct": round(win_rate, 1),
                        }
                        findings["details"].append(
                            f"Walk-Forward Backtest: {len(outperfs)} folds, "
                            f"Avg Outperformance: {avg_outperf:+.2f}%, Win Rate: {win_rate:.1f}%"
                        )
        except Exception:
            pass

    # 4. 60-Day Forecast
    forecast_path = output_dir / "SPY_forecast_60d.csv"
    if not forecast_path.is_file():
        forecast_path = output_dir / "SPY_hmm_forecast.csv"
    if forecast_path.is_file():
        try:
            with open(forecast_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            if len(lines) > 1:
                header = [c.strip() for c in lines[0].split(",")]
                regime_cols = header[1:]
                # Day 1
                day1_vals = [float(x) for x in lines[1].split(",")[1:]]
                max_d1_idx = day1_vals.index(max(day1_vals))
                d1_regime = regime_cols[max_d1_idx]
                d1_prob = day1_vals[max_d1_idx] * 100

                # Last day
                last_vals = [float(x) for x in lines[-1].split(",")[1:]]
                max_last_idx = last_vals.index(max(last_vals))
                last_regime = regime_cols[max_last_idx]
                last_prob = last_vals[max_last_idx] * 100

                findings["forecast_summary"] = {
                    "day_1_regime": d1_regime,
                    "day_1_prob_pct": round(d1_prob, 1),
                    "day_60_regime": last_regime,
                    "day_60_prob_pct": round(last_prob, 1),
                }
                findings["details"].append(
                    f"60-Day Forecast: Day 1 most likely {d1_regime} ({d1_prob:.1f}%), "
                    f"Day 60 terminal state {last_regime} ({last_prob:.1f}%)"
                )
        except Exception:
            pass

    return findings


def create_report_email(
    to_email: str,
    from_email: str = "noreply@qmafib.local",
    csv_zip_data: bytes | None = None,
    csv_files: list[dict[str, Any]] | None = None,
    images_zip_data: bytes | None = None,
    image_files: list[dict[str, Any]] | None = None,
    pdf_info: dict[str, Any] | None = None,
    findings: dict[str, Any] | None = None,
    # Backward compatibility arguments
    files: list[dict[str, Any]] | None = None,
    zip_data: bytes | None = None,
) -> MIMEMultipart:
    """Assemble a multipart MIME email containing only the zipped CSVs, zipped images, and Report.pdf.

    The email body details attachment metadata and key findings.
    """
    # Handle backward-compatible positional or kwargs invocation where files was passed
    if csv_files is None and files is not None:
        csv_files = [f for f in files if f["filename"].lower().endswith(".csv")]
    if image_files is None and files is not None:
        image_files = [
            f for f in files
            if Path(f["filename"]).suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp")
            or f["rel_path"].startswith(("plots/", "images/"))
        ]
    if pdf_info is None and files is not None:
        pdfs = [f for f in files if f["filename"].lower().endswith(".pdf")]
        if pdfs:
            pdf_info = pdfs[0]

    csv_files = csv_files or []
    image_files = image_files or []
    findings = findings or {}

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"QMAFIB Market Regime & Backtest Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="qmafib.local")

    alt_part = MIMEMultipart("alternative")

    # Build Plain Text Attachment Metadata
    attachments_meta_txt = []
    if csv_zip_data is not None or csv_files:
        csv_size = _format_size(len(csv_zip_data)) if csv_zip_data else "N/A"
        csv_names = "\n".join([f"     - {f['rel_path']} ({f['size_display']})" for f in csv_files]) or "     (none)"
        attachments_meta_txt.append(
            f"  1. csv_files.zip ({len(csv_files)} CSV files, {csv_size})\n{csv_names}"
        )
    if images_zip_data is not None or image_files:
        img_size = _format_size(len(images_zip_data)) if images_zip_data else "N/A"
        img_names = "\n".join([f"     - {f['rel_path']} ({f['size_display']})" for f in image_files]) or "     (none)"
        attachments_meta_txt.append(
            f"  2. images.zip ({len(image_files)} image/plot files, {img_size})\n{img_names}"
        )
    if pdf_info:
        attachments_meta_txt.append(
            f"  3. {pdf_info['filename']} ({pdf_info['size_display']})\n     - Executive summary report (PDF)"
        )
    meta_txt_str = "\n".join(attachments_meta_txt) if attachments_meta_txt else "  No attachments packaged."

    # Build Plain Text Findings
    findings_txt_lines = []
    if findings.get("current_regime") and findings.get("current_regime") != "Unknown":
        findings_txt_lines.append(
            f"  • Current Market Regime: {findings['current_regime']} "
            f"(Model: {findings.get('current_regime_model', 'N/A')}, Date: {findings.get('regime_date', 'N/A')})"
        )
    strat = findings.get("strategy_recommendation")
    if strat:
        findings_txt_lines.append(
            f"  • Adaptive Strategy Recommendation ({strat.get('regime')}):\n"
            f"      Position Size: {strat.get('position_size')} | Stop Loss: {strat.get('stop_loss')} | "
            f"Take Profit: {strat.get('take_profit')} | Signal Filter: {strat.get('signal_filter')}\n"
            f"      Guidance: {strat.get('description')}"
        )
    bt = findings.get("backtest_summary")
    if bt:
        findings_txt_lines.append(
            f"  • Walk-Forward Backtest ({bt.get('total_folds')} folds):\n"
            f"      Avg Outperformance: {bt.get('avg_outperformance_pct'):+.2f}% | Win Rate: {bt.get('win_rate_pct'):.1f}%"
        )
    fc = findings.get("forecast_summary")
    if fc:
        findings_txt_lines.append(
            f"  • 60-Day Regime Forecast:\n"
            f"      Near-Term (Day 1): {fc.get('day_1_regime')} ({fc.get('day_1_prob_pct'):.1f}%)\n"
            f"      Horizon (Day 60): {fc.get('day_60_regime')} ({fc.get('day_60_prob_pct'):.1f}%)"
        )
    if not findings_txt_lines:
        findings_txt_lines.append("  • Analytical data and model outputs have been successfully generated.")
    findings_txt_str = "\n".join(findings_txt_lines)

    text_content = (
        f"QMAFIB Quantitative Analytics & Market Regime Report\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"Here are the report files and model outputs attached for your review:\n\n"
        f"ATTACHMENTS METADATA:\n"
        f"--------------------------------------------------\n"
        f"{meta_txt_str}\n\n"
        f"KEY FINDINGS & ANALYTICS SUMMARY:\n"
        f"--------------------------------------------------\n"
        f"{findings_txt_str}\n\n"
        f"—\n"
        f"QMAFIB Platform | Quantitative Multi-Asset Financial Intelligence & Backtesting\n"
    )
    alt_part.attach(MIMEText(text_content, "plain", "utf-8"))

    # Build HTML Version
    attachments_html_rows = []
    if csv_zip_data is not None or csv_files:
        csv_size = _format_size(len(csv_zip_data)) if csv_zip_data else "N/A"
        csv_names_html = "<br/>".join([f"<code>{f['rel_path']}</code> ({f['size_display']})" for f in csv_files])
        attachments_html_rows.append(
            f"<tr>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; color: #38bdf8; font-weight: 600;'>📁 csv_files.zip</td>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; color: #94a3b8;'>{len(csv_files)} CSV files<div style='font-size: 11px; margin-top: 4px; color: #64748b;'>{csv_names_html}</div></td>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; text-align: right; color: #cbd5e1;'>{csv_size}</td>"
            f"</tr>"
        )
    if images_zip_data is not None or image_files:
        img_size = _format_size(len(images_zip_data)) if images_zip_data else "N/A"
        img_names_html = "<br/>".join([f"<code>{f['rel_path']}</code> ({f['size_display']})" for f in image_files])
        attachments_html_rows.append(
            f"<tr>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; color: #a78bfa; font-weight: 600;'>🖼️ images.zip</td>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; color: #94a3b8;'>{len(image_files)} plot/image files<div style='font-size: 11px; margin-top: 4px; color: #64748b;'>{img_names_html}</div></td>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; text-align: right; color: #cbd5e1;'>{img_size}</td>"
            f"</tr>"
        )
    if pdf_info:
        attachments_html_rows.append(
            f"<tr>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; color: #f43f5e; font-weight: 600;'>📄 {pdf_info['filename']}</td>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; color: #94a3b8;'>Executive Quantitative Report (PDF)</td>"
            f"<td style='padding: 10px 12px; border-bottom: 1px solid #1f2c45; text-align: right; color: #cbd5e1;'>{pdf_info['size_display']}</td>"
            f"</tr>"
        )

    findings_html_cards = []
    if findings.get("current_regime") and findings.get("current_regime") != "Unknown":
        findings_html_cards.append(
            f"<div style='background: rgba(56, 189, 248, 0.08); border-left: 3px solid #38bdf8; padding: 10px 14px; margin-bottom: 10px; border-radius: 4px;'>"
            f"<strong style='color: #38bdf8;'>Market Regime Status:</strong> "
            f"<span style='color: #e2e8f0;'>Current detected regime is <strong>{findings['current_regime']}</strong> "
            f"({findings.get('current_regime_model', 'N/A')} model, as of {findings.get('regime_date', 'N/A')}).</span>"
            f"</div>"
        )
    if strat:
        findings_html_cards.append(
            f"<div style='background: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; padding: 10px 14px; margin-bottom: 10px; border-radius: 4px;'>"
            f"<strong style='color: #10b981;'>Adaptive Strategy Recommendation ({strat.get('regime')}):</strong> "
            f"<div style='color: #cbd5e1; margin-top: 4px; font-size: 12px; line-height: 1.5;'>"
            f"Position Size: <strong>{strat.get('position_size')}</strong> &bull; "
            f"Stop Loss: <strong>{strat.get('stop_loss')}</strong> &bull; "
            f"Take Profit: <strong>{strat.get('take_profit')}</strong> &bull; "
            f"Signal Filter: <code>{strat.get('signal_filter')}</code><br/>"
            f"<span style='color: #94a3b8; font-style: italic;'>{strat.get('description')}</span>"
            f"</div></div>"
        )
    if bt:
        findings_html_cards.append(
            f"<div style='background: rgba(245, 158, 11, 0.08); border-left: 3px solid #f59e0b; padding: 10px 14px; margin-bottom: 10px; border-radius: 4px;'>"
            f"<strong style='color: #f59e0b;'>Walk-Forward Backtest ({bt.get('total_folds')} Folds):</strong> "
            f"<div style='color: #cbd5e1; margin-top: 4px; font-size: 12px;'>"
            f"Average Outperformance: <strong>{bt.get('avg_outperformance_pct'):+.2f}%</strong> &bull; "
            f"Fold Win Rate: <strong>{bt.get('win_rate_pct'):.1f}%</strong>"
            f"</div></div>"
        )
    if fc:
        findings_html_cards.append(
            f"<div style='background: rgba(167, 139, 250, 0.08); border-left: 3px solid #a78bfa; padding: 10px 14px; margin-bottom: 10px; border-radius: 4px;'>"
            f"<strong style='color: #a78bfa;'>60-Day Forward Forecast:</strong> "
            f"<div style='color: #cbd5e1; margin-top: 4px; font-size: 12px;'>"
            f"Near-Term (Day 1): <strong>{fc.get('day_1_regime')}</strong> ({fc.get('day_1_prob_pct'):.1f}%) &bull; "
            f"Terminal Horizon (Day 60): <strong>{fc.get('day_60_regime')}</strong> ({fc.get('day_60_prob_pct'):.1f}%)"
            f"</div></div>"
        )
    if not findings_html_cards:
        findings_html_cards.append(
            "<p style='color: #94a3b8; font-size: 13px;'>All analytical output files and visualizations have been generated successfully.</p>"
        )

    html_content = f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0b1120; color: #e2e8f0; margin: 0; padding: 20px; }}
  .card {{ background-color: #111a2e; border: 1px solid #1f2c45; border-radius: 10px; max-width: 660px; margin: 0 auto; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
  .header {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 24px; border-bottom: 1px solid #1f2c45; }}
  .title {{ margin: 0; font-size: 20px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px; }}
  .subtitle {{ margin: 6px 0 0; font-size: 13px; color: #94a3b8; }}
  .content {{ padding: 24px; }}
  .section-title {{ font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; color: #38bdf8; margin: 20px 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
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
      <p style="margin-top: 0; font-size: 14px; line-height: 1.6; color: #cbd5e1;">
        Here are the report files and model outputs attached for your review:
      </p>

      <div class="section-title">📎 Attachments Metadata</div>
      <table>
        <thead>
          <tr>
            <th>Attachment</th>
            <th>Contents</th>
            <th style="text-align: right;">Size</th>
          </tr>
        </thead>
        <tbody>
          {"".join(attachments_html_rows)}
        </tbody>
      </table>

      <div class="section-title" style="margin-top: 24px;">📊 Key Findings &amp; Analytics Summary</div>
      {"".join(findings_html_cards)}
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

    # 1. Attach CSV Zip Archive (if present)
    if csv_zip_data:
        part = MIMEApplication(csv_zip_data, _subtype="zip")
        part.add_header("Content-Disposition", "attachment", filename="csv_files.zip")
        msg.attach(part)

    # 2. Attach Images Zip Archive (if present)
    if images_zip_data:
        part = MIMEApplication(images_zip_data, _subtype="zip")
        part.add_header("Content-Disposition", "attachment", filename="images.zip")
        msg.attach(part)

    # 3. Attach Report.pdf (if present)
    if pdf_info and pdf_info.get("full_path") and Path(pdf_info["full_path"]).is_file():
        with open(pdf_info["full_path"], "rb") as fp:
            pdf_bytes = fp.read()
        part = MIMEApplication(pdf_bytes, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=pdf_info["filename"])
        msg.attach(part)

    return msg


def _display_path(path: Path) -> str:
    """Render a saved path relative to ``backend/`` when it lives there."""
    try:
        return str(path.relative_to(_BACKEND_DIR))
    except ValueError:
        return str(path)


def send_report_email(to_email: str) -> dict[str, Any]:
    """Validate email, package CSVs and images into separate ZIPs, attach Report.pdf, and send via SMTP."""
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
    csv_files = collect_csv_files(output_dir)
    image_files = collect_image_files(output_dir)
    pdf_info = get_report_pdf(output_dir)

    csv_zip_data = build_csv_zip(output_dir, csv_files) if csv_files else b""
    images_zip_data = build_images_zip(output_dir, image_files) if image_files else b""
    findings = extract_report_findings(output_dir)

    # SMTP configuration
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_from = os.environ.get("SMTP_FROM", "").strip() or smtp_user or "noreply@qmafib.local"
    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
    smtp_use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() in ("true", "1", "yes") or smtp_port == 465

    msg = create_report_email(
        to_email=clean_email,
        from_email=smtp_from,
        csv_zip_data=csv_zip_data if csv_files else None,
        csv_files=csv_files,
        images_zip_data=images_zip_data if image_files else None,
        image_files=image_files,
        pdf_info=pdf_info,
        findings=findings,
    )

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

    all_files = csv_files + image_files + ([pdf_info] if pdf_info else [])
    attachments = []
    if csv_files:
        attachments.append({"name": "csv_files.zip", "size_bytes": len(csv_zip_data), "count": len(csv_files)})
    if image_files:
        attachments.append({"name": "images.zip", "size_bytes": len(images_zip_data), "count": len(image_files)})
    if pdf_info:
        attachments.append({"name": pdf_info["filename"], "size_bytes": pdf_info["size_bytes"], "count": 1})

    return {
        "status": "success",
        "message": f"Report successfully sent to {clean_email}",
        "recipient": clean_email,
        "attachments": attachments,
        "files_count": len(all_files),
        "files": [f["rel_path"] for f in all_files],
        "csv_zip_size_bytes": len(csv_zip_data),
        "images_zip_size_bytes": len(images_zip_data),
        "pdf_size_bytes": pdf_info["size_bytes"] if pdf_info else 0,
        "findings": findings,
        "saved_local_copy": _display_path(eml_path),
    }

