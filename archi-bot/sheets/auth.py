from __future__ import annotations

import base64
import json

import gspread
from google.oauth2.service_account import Credentials

from config import Config

_SCOPES_RO = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_SCOPES_RW = ["https://www.googleapis.com/auth/spreadsheets"]


def load_service_account_info(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        pass
    try:
        with open(raw, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        pass
    raise ValueError(
        "GOOGLE_SERVICE_ACCOUNT_JSON must be raw JSON, base64-encoded JSON, or a file path"
    )


def make_gspread_client(config: Config, readonly: bool = False) -> gspread.Client:
    scopes = _SCOPES_RO if readonly else _SCOPES_RW
    info = load_service_account_info(config.google_service_account_json)
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)
