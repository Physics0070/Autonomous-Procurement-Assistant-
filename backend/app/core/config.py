"""Application configuration.

All settings come from environment variables (see .env.example).
Nothing secret is ever hardcoded here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Anchored to backend/, so the app reads the same .env whatever directory it starts from.
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    APP_NAME: str = "Autonomous Procurement Assistant"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # --- Database ---
    MONGODB_URI: str = "mongodb://127.0.0.1:27017"
    MONGODB_DB_NAME: str = "procurement_assistant"

    # --- Security ---
    JWT_SECRET_KEY: str = Field(default="CHANGE_ME_IN_PRODUCTION")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- CORS ---
    # Kept as a plain string: pydantic-settings JSON-decodes complex types
    # straight from .env, which rejects a comma-separated list.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Storage ---
    STORAGE_BACKEND: str = "local"  # local | s3 | minio (future)
    STORAGE_LOCAL_PATH: str = "../storage"
    MAX_UPLOAD_SIZE_MB: int = 25

    # --- AI provider ---
    AI_PROVIDER: str = "openrouter"  # openrouter | ollama | gemini | none

    # OpenRouter (OpenAI-compatible). Free model IDs end in ":free".
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = "google/gemma-4-31b-it:free"
    # Comma-separated; OpenRouter falls through to these when the primary fails.
    OPENROUTER_FALLBACK_MODELS: str = "nvidia/nemotron-3-super-120b-a12b:free"
    OPENROUTER_APP_URL: str = "http://localhost:5173"

    # Ollama (local, free, no key).
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "llama3.1"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    AI_REQUEST_TIMEOUT_SECONDS: int = 90

    # --- OCR ---
    OCR_ENGINE: str = "auto"  # auto | tesseract | rapidocr | none
    TESSERACT_CMD: str = ""  # explicit path to tesseract.exe if not on PATH
    # If a PDF page yields fewer characters than this, treat it as scanned.
    PDF_TEXT_MIN_CHARS_PER_PAGE: int = 60

    # --- Processing ---
    PROCESSING_WORKER_CONCURRENCY: int = 2

    # --- Scoring weights (configurable, never deeply hardcoded) ---
    SCORE_WEIGHT_PRICE: float = 0.40
    SCORE_WEIGHT_DELIVERY: float = 0.20
    SCORE_WEIGHT_PAYMENT: float = 0.15
    SCORE_WEIGHT_RELIABILITY: float = 0.15
    SCORE_WEIGHT_OTHER: float = 0.10

    # --- Matching thresholds ---
    MATCH_AUTO_THRESHOLD: float = 0.86     # >= -> automatic match
    MATCH_REVIEW_THRESHOLD: float = 0.62   # >= -> match but flag for review
    # below MATCH_REVIEW_THRESHOLD -> unmatched / requires manual review

    # --- Secrets at rest ---
    # Fernet key for OAuth refresh tokens. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Derived from JWT_SECRET_KEY when empty.
    TOKEN_ENCRYPTION_KEY: str = ""

    # --- Frontend (OAuth callbacks redirect here) ---
    FRONTEND_URL: str = "http://localhost:5173"

    # --- Google OAuth 2.0 / Gmail ingestion ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/channels/gmail/callback"
    GMAIL_SCOPES: str = "https://www.googleapis.com/auth/gmail.readonly"
    # drive.file only reaches files this app creates; it cannot read an existing Drive.
    GOOGLE_DRIVE_ENABLED: bool = True
    GOOGLE_DRIVE_FOLDER_ID: str = ""  # optional: file POs into one folder
    # Deliberately narrow: importing every PDF in a mailbox would pull in bank
    # statements and invoices. Use e.g. `label:quotations` for a dedicated label.
    GMAIL_SYNC_QUERY: str = (
        "newer_than:30d subject:(quotation OR quotations OR quote OR RFQ "
        'OR "price list" OR proforma OR "rate list")'
    )
    GMAIL_MAX_MESSAGES_PER_SYNC: int = 25
    GMAIL_SYNC_INTERVAL_MINUTES: int = 15  # 0 disables automatic collection

    # --- Procurement automation, agents, analytics ---
    NEGOTIATION_DEFAULT_DISCOUNT_PCT: float = 5.0  # target price below the quote when none is given
    NEGOTIATION_WEAK_CRITERION_SCORE: float = 0.5  # delivery/payment scores below this are negotiated
    ASSISTANT_MAX_TOOL_ROUNDS: int = 6
    AGENT_MAX_STEPS: int = 12  # supervisor routing decisions per run
    # The monitor agent starts work on its own. It only ever produces drafts that wait
    # for approval; set AGENT_AUTOPILOT=false to require a person to press the button.
    AGENT_AUTOPILOT: bool = True
    AGENT_AUTOPILOT_MIN_QUOTATIONS: int = 2
    AGENT_WATCHDOG_INTERVAL_MINUTES: int = 60  # overdue-delivery check; 0 disables
    EXTRACTION_SELF_CORRECTION: bool = True  # re-read a document once when validation finds errors
    ML_MIN_RETRAIN_ORDERS: int = 50  # delivered POs needed to retrain the reliability model

    @model_validator(mode="after")
    def _no_placeholder_secret_outside_development(self) -> "Settings":
        if self.ENVIRONMENT.lower() != "development" and self.JWT_SECRET_KEY == "CHANGE_ME_IN_PRODUCTION":
            raise ValueError("JWT_SECRET_KEY must be set outside development (it signs logins and OAuth state).")
        return self

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def openrouter_fallback_models(self) -> List[str]:
        return [m.strip() for m in self.OPENROUTER_FALLBACK_MODELS.split(",") if m.strip()]

    @property
    def ai_configured(self) -> bool:
        provider = self.AI_PROVIDER.lower()
        if provider == "openrouter":
            return bool(self.OPENROUTER_API_KEY.strip())
        if provider == "ollama":
            return bool(self.OLLAMA_MODEL.strip())
        if provider == "gemini":
            return bool(self.GEMINI_API_KEY.strip())
        return False

    @property
    def google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID.strip() and self.GOOGLE_CLIENT_SECRET.strip())

    def scoring_weights(self) -> dict:
        return {
            "price": self.SCORE_WEIGHT_PRICE,
            "delivery": self.SCORE_WEIGHT_DELIVERY,
            "payment": self.SCORE_WEIGHT_PAYMENT,
            "reliability": self.SCORE_WEIGHT_RELIABILITY,
            "other": self.SCORE_WEIGHT_OTHER,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
