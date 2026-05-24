import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    google_client_id: str
    google_client_secret: str
    google_fdr_sheet_id: str
    google_portfolio_sheet_id: str
    anthropic_api_key: str
    owner_telegram_id: int
    company_name: str
    abmk_file_id: str


def load_config() -> Config:
    missing = []

    def require(key: str) -> str:
        val = os.getenv(key, "").strip()
        if not val:
            missing.append(key)
        return val

    cfg = Config(
        telegram_bot_token=require("TELEGRAM_BOT_TOKEN"),
        google_client_id=require("GOOGLE_CLIENT_ID"),
        google_client_secret=require("GOOGLE_CLIENT_SECRET"),
        google_fdr_sheet_id=require("GOOGLE_FDR_SHEET_ID"),
        google_portfolio_sheet_id=require("GOOGLE_PORTFOLIO_SHEET_ID"),
        anthropic_api_key=require("ANTHROPIC_API_KEY"),
        owner_telegram_id=int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0"),
        company_name=require("COMPANY_NAME"),
        abmk_file_id=require("ABMK_FILE_ID"),
    )

    if not os.getenv("OWNER_TELEGRAM_ID", "").strip():
        missing.append("OWNER_TELEGRAM_ID")

    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in all values."
        )

    return cfg
