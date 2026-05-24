"""
OAuth2 user-credential auth for Google APIs.

First run: opens a browser tab for Google login, saves the token to
data/google_token.json. Every subsequent run loads and auto-refreshes
that token — no browser needed.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import Config

logger = logging.getLogger(__name__)

_TOKEN_PATH = "data/google_token.json"

# One set of scopes covers both Sheets (read/write) and Drive (read-only for ABMK file)
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _client_config(config: Config) -> dict:
    return {
        "installed": {
            "client_id": config.google_client_id,
            "client_secret": config.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }


def get_credentials(config: Config) -> Credentials:
    """
    Return valid Google OAuth2 credentials.

    Order of operations:
      1. Load token from data/google_token.json if it exists.
      2. Refresh if expired (uses refresh_token, no browser needed).
      3. Run browser OAuth2 flow if no valid token exists.
      4. Save the (new/refreshed) token back to disk.
    """
    creds: Optional[Credentials] = None

    if os.path.exists(_TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(_TOKEN_PATH, _SCOPES)
        except Exception as exc:
            logger.warning("Ignoring invalid token file (%s) — will re-authorise", exc)
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing expired Google token")
        creds.refresh(Request())
    else:
        logger.info(
            "No valid Google token found — starting browser OAuth2 flow.\n"
            "A browser window will open. Log in with your Google account and "
            "grant the requested permissions."
        )
        flow = InstalledAppFlow.from_client_config(_client_config(config), _SCOPES)
        creds = flow.run_local_server(port=0)

    os.makedirs(os.path.dirname(os.path.abspath(_TOKEN_PATH)), exist_ok=True)
    with open(_TOKEN_PATH, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    logger.info("Google token saved → %s", _TOKEN_PATH)

    return creds


def make_gspread_client(config: Config) -> gspread.Client:
    return gspread.authorize(get_credentials(config))
