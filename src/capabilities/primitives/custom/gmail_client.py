"""
Shared Gmail API client — handles authentication and service construction.

Supports two auth modes (checked in order):

1. **Service account** — set ``GOOGLE_SERVICE_ACCOUNT_FILE`` to the path of
   a JSON service-account key file.  The account must have domain-wide
   delegation configured, and ``GOOGLE_WORKSPACE_USER`` must be set to the
   user to impersonate.

2. **OAuth 2.0 desktop** — set ``GOOGLE_CLIENT_ID`` and
   ``GOOGLE_CLIENT_SECRET``.  On first use the library opens a browser for
   consent; the resulting token is cached at ``~/.vai/gmail_token.pickle``
   and refreshed automatically.

The token cache path can be overridden via ``GOOGLE_TOKEN_PATH``.
"""

from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path
from typing import Any

# Optional SDK imports — fail gracefully at module level.
try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as SACredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False

# ── defaults ──────────────────────────────────────────────────────────────

DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

_TOKEN_DIR = Path.home() / ".vai"
_DEFAULT_TOKEN_PATH = _TOKEN_DIR / "gmail_token.pickle"


# ── exceptions ────────────────────────────────────────────────────────────


class GmailAuthError(Exception):
    """Raised when Gmail authentication fails or is not configured."""


class GmailNotAvailableError(ImportError):
    """Raised when the Google SDK is not installed."""


# ── public API ────────────────────────────────────────────────────────────


def gmail_client(
    *,
    context: dict[str, Any] | None = None,
    scopes: list[str] | None = None,
) -> Any:
    """Return an authenticated Gmail API ``Resource``.

    Reads configuration from environment variables (or ``context`` dict
    keys with the same names, which take precedence):

    * ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET`` — OAuth 2.0 desktop
    * ``GOOGLE_SERVICE_ACCOUNT_FILE`` — service-account JSON path
    * ``GOOGLE_WORKSPACE_USER`` — user to impersonate (service-account only)
    * ``GOOGLE_TOKEN_PATH`` — token cache path (default ``~/.vai/gmail_token.pickle``)

    Args:
        context: Optional runtime context dict that may carry config.
        scopes:  OAuth scopes to request (default: gmail.modify, gmail.send,
                 gmail.readonly).

    Returns:
        A ``googleapiclient.discovery.Resource`` for the Gmail API.

    Raises:
        GmailNotAvailableError: If the Google SDK is not installed.
        GmailAuthError: If authentication is not configured or fails.
    """
    if not _GOOGLE_AVAILABLE:
        raise GmailNotAvailableError(
            "Google SDK not installed. Run: pip install google-api-python-client google-auth-oauthlib"
        )

    resolved_scopes = scopes or DEFAULT_SCOPES
    env = _resolve_env(context)

    service_account_file = env.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    client_id = env.get("GOOGLE_CLIENT_ID")
    client_secret = env.get("GOOGLE_CLIENT_SECRET")

    if service_account_file:
        return _build_service_account(service_account_file, resolved_scopes, env)
    elif client_id and client_secret:
        return _build_oauth(client_id, client_secret, resolved_scopes, env)
    else:
        raise GmailAuthError(
            "Gmail not configured. Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET "
            "(OAuth) or GOOGLE_SERVICE_ACCOUNT_FILE (service account)."
        )


# ── internal helpers ──────────────────────────────────────────────────────


def _resolve_env(context: dict[str, Any] | None) -> dict[str, str]:
    """Merge context keys and environment variables."""
    env: dict[str, str] = {}
    for key in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        "GOOGLE_WORKSPACE_USER",
        "GOOGLE_TOKEN_PATH",
    ):
        # Context takes precedence over env
        if context and key.lower() in context:
            env[key] = str(context[key.lower()])
        elif key in os.environ:
            env[key] = os.environ[key]
    return env


def _build_service_account(
    sa_file: str,
    scopes: list[str],
    env: dict[str, str],
) -> Any:
    """Build Gmail service from a service-account JSON key."""
    user = env.get("GOOGLE_WORKSPACE_USER")
    if not user:
        raise GmailAuthError(
            "GOOGLE_WORKSPACE_USER must be set when using a service account"
        )

    try:
        creds: Any = SACredentials.from_service_account_file(sa_file, scopes=scopes)
        creds = creds.with_subject(user)
        return build("gmail", "v1", credentials=creds)
    except Exception as exc:
        raise GmailAuthError(f"Service account auth failed: {exc}") from exc


def _build_oauth(
    client_id: str,
    client_secret: str,
    scopes: list[str],
    env: dict[str, str],
) -> Any:
    """Build Gmail service via OAuth 2.0 desktop flow with token caching."""
    token_path_str = env.get("GOOGLE_TOKEN_PATH", "")
    token_path = Path(token_path_str) if token_path_str else _DEFAULT_TOKEN_PATH

    creds = _load_cached_token(token_path)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleAuthRequest())
            except Exception as exc:
                raise GmailAuthError(f"Token refresh failed: {exc}") from exc
        else:
            creds = _run_oauth_flow(client_id, client_secret, scopes, token_path)

    return build("gmail", "v1", credentials=creds)


def _load_cached_token(token_path: Path) -> Credentials | None:
    """Load cached OAuth token from disk, or return None."""
    try:
        with open(token_path, "rb") as f:
            creds: Credentials = pickle.load(f)
        return creds
    except (FileNotFoundError, pickle.UnpicklingError, ValueError):
        return None


def _run_oauth_flow(
    client_id: str,
    client_secret: str,
    scopes: list[str],
    token_path: Path,
) -> Credentials:
    """Run the desktop OAuth flow (opens browser) and cache the token."""
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"],
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes)
        creds = flow.run_local_server(port=0)
    except Exception as exc:
        raise GmailAuthError(f"OAuth flow failed: {exc}") from exc

    # Persist token for future sessions
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
    except OSError:
        pass  # non-fatal — token works for this session

    return creds
