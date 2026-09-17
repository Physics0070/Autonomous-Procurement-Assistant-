"""Application configuration.

All settings come from environment variables (see .env.example).
Nothing secret is ever hardcoded here.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
    AI_PROVIDER: str = "gemini"  # gemini | none
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

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def ai_configured(self) -> bool:
        if self.AI_PROVIDER.lower() == "none":
            return False
        if self.AI_PROVIDER.lower() == "gemini":
            return bool(self.GEMINI_API_KEY.strip())
        return False

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
