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
    build_zip_archive,
    collect_output_files,
    create_report_email,
    get_output_dir,
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

    def test_collect_output_files(self):
        output_dir = get_output_dir()
        files = collect_output_files(output_dir)

        # backend/output should contain CSV files and plots
        assert len(files) > 0
        filenames = [f["filename"] for f in files]
        assert any(fn.endswith(".csv") for fn in filenames)

        # Check relative paths
        for f in files:
            assert not f["rel_path"].startswith("emails")
            assert f["full_path"].exists()
            assert f["size_bytes"] >= 0

    def test_build_zip_archive(self):
        output_dir = get_output_dir()
        files = collect_output_files(output_dir)
        zip_bytes = build_zip_archive(output_dir, files)

        assert len(zip_bytes) > 0

        # Read back in-memory zip to verify valid zip structure
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            namelist = zf.namelist()
            assert len(namelist) == len(files)
            for f in files:
                assert f["rel_path"] in namelist


class TestEmailConstruction:
    """Verify MIME multipart email structure and attachments."""

    def test_create_report_email(self):
        output_dir = get_output_dir()
        files = collect_output_files(output_dir)
        zip_bytes = build_zip_archive(output_dir, files)

        msg = create_report_email(
            to_email="test@example.com",
            files=files,
            zip_data=zip_bytes,
            from_email="noreply@qmafib.local",
        )

        assert msg["To"] == "test@example.com"
        assert msg["From"] == "noreply@qmafib.local"
        assert "QMAFIB" in msg["Subject"]

        # Check attachments: zip file should be present
        attachment_names = []
        for part in msg.walk():
            filename = part.get_filename()
            if filename:
                attachment_names.append(filename)

        assert "output_report.zip" in attachment_names
        # Check individual file attachments are also included
        assert len(attachment_names) >= len(files)


class TestReportEndpoint:
    """Test the POST /api/report/send-email endpoint."""

    def test_send_report_invalid_email(self):
        response = client.post("/api/report/send-email", json={"email": "invalid-email"})
        assert response.status_code == 400
        assert "Invalid email address" in response.json()["detail"]

    def test_send_report_success_mocked_smtp(self, monkeypatch, tmp_path):
        # The recipient allowlist fails closed, so a test that expects delivery
        # has to say who delivery is allowed to — exactly as a real deployment
        # does. Without this the endpoint correctly answers 403.
        monkeypatch.setenv("REPORT_EMAIL_ALLOWLIST", "quant.researcher@test.com")

        # Redirect the archive at a temporary directory. Against the real one
        # this test packaged every artifact in backend/output and wrote a ~5 MB
        # .eml audit copy back into it on every run — the suite was growing the
        # repository it was testing, and the next run then had more to zip.
        (tmp_path / "report.csv").write_text("date,value\n2024-01-01,1\n")
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested" / "plot.txt").write_text("placeholder")
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
            assert "output_report.zip" or len(data["files"]) > 0
            assert instance.send_message.called
