"""Tests for email report generation and dispatch."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.email_service import (
    EMAIL_REGEX,
    build_csv_zip,
    build_images_zip,
    build_zip_archive,
    collect_csv_files,
    collect_image_files,
    collect_output_files,
    create_report_email,
    extract_report_findings,
    get_output_dir,
    get_report_pdf,
    send_report_email,
    validate_email,
)
from app.main import app

client = TestClient(app)


class TestEmailValidation:
    """Validate RFC 5322 regex validation behavior."""

    @pytest.mark.parametrize(
        "valid_email",
        [
            "analyst@example.com",
            "first.last@firm.co.uk",
            "user+tag@domain.org",
            "investor123@sub.domain.io",
        ],
    )
    def test_valid_emails(self, valid_email: str):
        assert validate_email(valid_email) is True
        assert EMAIL_REGEX.match(valid_email) is not None

    @pytest.mark.parametrize(
        "invalid_email",
        [
            "",
            "plainaddress",
            "@missingusername.com",
            "username@.com",
            "username@com",
            "username@domain..com",
            "user@domain,com",
            "user name@domain.com",
        ],
    )
    def test_invalid_emails(self, invalid_email: str):
        assert validate_email(invalid_email) is False


class TestOutputFilesAndZip:
    """Verify scanning backend/output and ZIP creation."""

    def test_collect_csv_files(self):
        output_dir = get_output_dir()
        csv_files = collect_csv_files(output_dir)
        assert len(csv_files) > 0
        for f in csv_files:
            assert f["filename"].lower().endswith(".csv")
            assert not f["rel_path"].startswith("emails")
            assert f["full_path"].exists()

    def test_collect_image_files(self):
        output_dir = get_output_dir()
        image_files = collect_image_files(output_dir)
        assert len(image_files) > 0
        for f in image_files:
            assert f["rel_path"].startswith("plots/") or f["filename"].lower().endswith(
                (".png", ".jpg", ".jpeg", ".svg")
            )
            assert f["full_path"].exists()

    def test_get_report_pdf(self):
        output_dir = get_output_dir()
        pdf_info = get_report_pdf(output_dir)
        if (output_dir / "Report.pdf").exists():
            assert pdf_info is not None
            assert pdf_info["filename"] == "Report.pdf"
            assert pdf_info["full_path"].exists()

    def test_build_csv_zip(self):
        output_dir = get_output_dir()
        csv_files = collect_csv_files(output_dir)
        zip_bytes = build_csv_zip(output_dir, csv_files)
        assert len(zip_bytes) > 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            namelist = zf.namelist()
            assert len(namelist) == len(csv_files)
            for f in csv_files:
                assert f["rel_path"] in namelist

    def test_build_images_zip(self):
        output_dir = get_output_dir()
        image_files = collect_image_files(output_dir)
        zip_bytes = build_images_zip(output_dir, image_files)
        assert len(zip_bytes) > 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            namelist = zf.namelist()
            assert len(namelist) == len(image_files)
            for f in image_files:
                assert f["rel_path"] in namelist

    def test_extract_report_findings(self):
        output_dir = get_output_dir()
        findings = extract_report_findings(output_dir)
        assert isinstance(findings, dict)
        assert "current_regime" in findings
        assert "strategy_recommendation" in findings
        assert len(findings["details"]) > 0


class TestEmailConstruction:
    """Verify MIME multipart email structure and attachments."""

    def test_create_report_email(self):
        output_dir = get_output_dir()
        csv_files = collect_csv_files(output_dir)
        image_files = collect_image_files(output_dir)
        pdf_info = get_report_pdf(output_dir)
        csv_zip = build_csv_zip(output_dir, csv_files)
        images_zip = build_images_zip(output_dir, image_files)
        findings = extract_report_findings(output_dir)

        msg = create_report_email(
            to_email="test@example.com",
            from_email="noreply@qmafib.local",
            csv_zip_data=csv_zip,
            csv_files=csv_files,
            images_zip_data=images_zip,
            image_files=image_files,
            pdf_info=pdf_info,
            findings=findings,
        )

        assert msg["To"] == "test@example.com"
        assert msg["From"] == "noreply@qmafib.local"
        assert "QMAFIB" in msg["Subject"]

        # Check attachments: ONLY csv_files.zip, images.zip, and Report.pdf
        attachment_names = []
        for part in msg.walk():
            filename = part.get_filename()
            if filename:
                attachment_names.append(filename)

        expected = ["csv_files.zip", "images.zip"]
        if pdf_info:
            expected.append(pdf_info["filename"])

        assert sorted(attachment_names) == sorted(expected)

        # Verify email body text includes intro, metadata, and findings
        body_text = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body_text = part.get_payload(decode=True).decode("utf-8")
                break

        assert "Here are the report files" in body_text
        assert "ATTACHMENTS METADATA" in body_text
        assert "KEY FINDINGS & ANALYTICS SUMMARY" in body_text
        assert "csv_files.zip" in body_text
        assert "images.zip" in body_text


class TestReportEndpoint:
    """Test the POST /api/report/send-email endpoint."""

    def test_send_report_invalid_email(self):
        response = client.post("/api/report/send-email", json={"email": "invalid-email"})
        assert response.status_code == 400
        assert "Invalid email address" in response.json()["detail"]

    def test_send_report_success_mocked_smtp(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "quant.researcher@test.com")

        # Create dummy artifacts in tmp_path
        (tmp_path / "report.csv").write_text("date,value\n2024-01-01,1\n")
        (tmp_path / "plots").mkdir()
        (tmp_path / "plots" / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\nplaceholder")
        (tmp_path / "Report.pdf").write_bytes(b"%PDF-1.4 dummy pdf")
        monkeypatch.setattr("app.email_service.get_output_dir", lambda: tmp_path)

        with patch("smtplib.SMTP") as mock_smtp:
            instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = instance

            response = client.post(
                "/api/report/send-email",
                json={"email": "quant.researcher@test.com"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["recipient"] == "quant.researcher@test.com"
            assert data["files_count"] > 0
            assert "attachments" in data
            attachment_names = [a["name"] for a in data["attachments"]]
            assert "csv_files.zip" in attachment_names
            assert "images.zip" in attachment_names
            assert "Report.pdf" in attachment_names
            assert instance.send_message.called

