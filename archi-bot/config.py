import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    anthropic_api_key: Optional[str]
    owner_telegram_id: int
    company_name: str


def load_config() -> Config:
    missing = []

    def require(key: str) -> str:
        val = os.getenv(key, "").strip()
        if not val:
            missing.append(key)
        return val

    def optional(key: str) -> Optional[str]:
        val = os.getenv(key, "").strip()
        return val if val else None

    cfg = Config(
        telegram_bot_token=require("TELEGRAM_BOT_TOKEN"),
        anthropic_api_key=optional("ANTHROPIC_API_KEY"),
        owner_telegram_id=int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0"),
        company_name=require("COMPANY_NAME"),
    )

    if cfg.anthropic_api_key is None:
        logger.warning(
            "ANTHROPIC_API_KEY not set — AI summary features are disabled."
        )

    if not os.getenv("OWNER_TELEGRAM_ID", "").strip():
        missing.append("OWNER_TELEGRAM_ID")

    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in all values."
        )

    return cfg
