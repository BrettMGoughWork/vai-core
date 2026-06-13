"""Tests for DevSMTPTransport — pluggable dev-only email transport."""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from src.platform.transport.dev_smtp import DevSMTPConfig, DevSMTPTransport


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def default_config() -> DevSMTPConfig:
    """DevSMTPConfig with default values."""
    return DevSMTPConfig()


@pytest.fixture
def clock() -> list[float]:
    """Deterministic clock for timestamp assertions."""
    return [1000.0, 1001.0, 1002.0]


@pytest.fixture
def transport(default_config: DevSMTPConfig, clock: list[float]) -> DevSMTPTransport:
    """DevSMTPTransport with default config and deterministic clock."""
    return DevSMTPTransport(default_config, clock=clock.pop)


@pytest.fixture
def mock_smtp() -> MagicMock:
    """A successful smtplib.SMTP mock."""
    smtp = MagicMock(spec=smtplib.SMTP)
    smtp.__enter__.return_value = smtp
    return smtp


# =============================================================================
# DevSMTPConfig
# =============================================================================


class TestDevSMTPConfig:
    """DevSMTPConfig dataclass construction and defaults."""

    def test_defaults(self, default_config: DevSMTPConfig) -> None:
        assert default_config.host == "localhost"
        assert default_config.port == 1025
        assert default_config.sender == "alerts@vai-core.local"
        assert default_config.timeout == 5.0

    def test_custom_host_port(self) -> None:
        cfg = DevSMTPConfig(host="192.168.1.100", port=587)
        assert cfg.host == "192.168.1.100"
        assert cfg.port == 587

    def test_custom_sender(self) -> None:
        cfg = DevSMTPConfig(sender="bot@example.com")
        assert cfg.sender == "bot@example.com"

    def test_custom_timeout(self) -> None:
        cfg = DevSMTPConfig(timeout=10.0)
        assert cfg.timeout == 10.0


# =============================================================================
# DevSMTPTransport — configuration exposure
# =============================================================================


class TestDevSMTPTransportConfig:
    """DevSMTPTransport.config property."""

    def test_config_property(self, transport: DevSMTPTransport) -> None:
        assert transport.config.host == "localhost"
        assert transport.config.port == 1025
        assert transport.config.sender == "alerts@vai-core.local"


# =============================================================================
# DevSMTPTransport — SMTP interaction (mocked)
# =============================================================================


class TestDevSMTPTransportSend:
    """DevSMTPTransport.send() with mocked smtplib.SMTP."""

    def test_send_success(self, transport: DevSMTPTransport,
                          mock_smtp: MagicMock) -> None:
        """Happy path — successful SMTP send returns status details."""
        with patch.object(smtplib, "SMTP", return_value=mock_smtp):
            result = transport.send(
                to="admin@example.com",
                subject="Test Alert",
                body="This is a test email body.",
            )

        assert result["success"] is True
        assert result["status_code"] == 250
        assert result["recipient"] == "admin@example.com"
        assert result["subject"] == "Test Alert"
        assert result["body_len"] == 26
        assert result["sent_at"] == 1002.0

        # Verify SMTP was called with correct connection params
        mock_smtp.send_message.assert_called_once()
        msg = mock_smtp.send_message.call_args[0][0]
        assert msg["From"] == "alerts@vai-core.local"
        assert msg["To"] == "admin@example.com"
        assert msg["Subject"] == "Test Alert"

    def test_send_with_custom_sender(self, default_config: DevSMTPConfig,
                                      clock: list[float],
                                      mock_smtp: MagicMock) -> None:
        """Sender override is reflected in the message headers."""
        transport = DevSMTPTransport(default_config, clock=clock.pop)

        with patch.object(smtplib, "SMTP", return_value=mock_smtp):
            transport.send(
                to="dev@test.local",
                subject="Alert",
                body="Test",
                sender="override@example.com",
            )

        msg = mock_smtp.send_message.call_args[0][0]
        assert msg["From"] == "override@example.com"
        assert msg["To"] == "dev@test.local"
        assert msg["Subject"] == "Alert"

    def test_send_custom_server(self, mock_smtp: MagicMock) -> None:
        """Custom host/port are forwarded to SMTP constructor."""
        cfg = DevSMTPConfig(host="mail.example.com", port=587)
        transport = DevSMTPTransport(cfg)

        with patch.object(smtplib, "SMTP") as mock_smtp_cls:
            mock_smtp_cls.return_value = mock_smtp
            transport.send(to="u@t.com", subject="S", body="B")

        mock_smtp_cls.assert_called_once_with(
            host="mail.example.com", port=587, timeout=5.0,
        )

    def test_send_smtp_error(self, transport: DevSMTPTransport,
                              mock_smtp: MagicMock) -> None:
        """SMTPException from send_message is reflected in result."""
        mock_smtp.send_message.side_effect = smtplib.SMTPException(
            "550 Mailbox unavailable"
        )
        with patch.object(smtplib, "SMTP", return_value=mock_smtp):
            result = transport.send(
                to="fail@example.com",
                subject="Fail",
                body="Nope",
            )

        assert result["success"] is False
        assert result["status_code"] is None
        assert "SMTPException" in result["error"]

    def test_send_connection_refused(self, transport: DevSMTPTransport) -> None:
        """Connection refused (OSError) is caught and returned."""
        with patch.object(smtplib, "SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = ConnectionRefusedError(
                "Connection refused"
            )
            result = transport.send(
                to="down@example.com",
                subject="Down",
                body="Service unreachable",
            )

        assert result["success"] is False
        assert result["status_code"] is None
        assert "ConnectionRefusedError" in result["error"]

    def test_send_timeout(self, transport: DevSMTPTransport) -> None:
        """Timeout (OSError subtype) is caught and returned."""
        with patch.object(smtplib, "SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = TimeoutError(
                "Connection timed out"
            )
            result = transport.send(
                to="slow@example.com",
                subject="Slow",
                body="This request timed out",
            )

        assert result["success"] is False
        assert result["status_code"] is None
        assert "TimeoutError" in result["error"]


# =============================================================================
# DevSMTPTransport — edge cases
# =============================================================================


class TestDevSMTPTransportEdgeCases:
    """Empty body, special characters, unicode."""

    def test_empty_body(self, transport: DevSMTPTransport,
                        mock_smtp: MagicMock) -> None:
        with patch.object(smtplib, "SMTP", return_value=mock_smtp):
            result = transport.send(
                to="empty@test.com",
                subject="Empty Body",
                body="",
            )

        assert result["success"] is True
        assert result["body_len"] == 0

    def test_unicode_content(self, transport: DevSMTPTransport,
                              mock_smtp: MagicMock) -> None:
        with patch.object(smtplib, "SMTP", return_value=mock_smtp):
            body = "Café résumé – 日本語 OK ✓"
            result = transport.send(
                to="unicode@test.com",
                subject="Unicode ✓",
                body=body,
            )

        assert result["success"] is True
        assert result["body_len"] == len(body)
