"""Configuration management via environment variables.

Loads settings from .env files and environment variables with sensible
defaults. API keys are validated lazily -- only when the corresponding
client is actually instantiated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Application configuration loaded from environment variables."""

    github_token: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    log_level: str = "INFO"
    max_file_size: int = 50_000
    request_timeout: int = 30
    max_retries: int = 3

    def require_github_token(self) -> str:
        """Return the GitHub token or raise if missing."""
        if not self.github_token:
            raise ConfigurationError(
                "GITHUB_TOKEN is required. "
                "Set it in your environment or .env file. "
                "Generate one at https://github.com/settings/tokens"
            )
        return self.github_token

    def require_gemini_api_key(self) -> str:
        """Return the Gemini API key or raise if missing."""
        if not self.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required. "
                "Set it in your environment or .env file. "
                "Generate one at https://aistudio.google.com/apikey"
            )
        return self.gemini_api_key

    def masked_display(self) -> dict[str, str]:
        """Return config values with secrets partially masked."""
        def _mask(value: str) -> str:
            if not value:
                return "(not set)"
            if len(value) <= 8:
                return "****"
            return value[:4] + "****" + value[-4:]

        return {
            "GITHUB_TOKEN": _mask(self.github_token),
            "GEMINI_API_KEY": _mask(self.gemini_api_key),
            "GEMINI_MODEL": self.gemini_model,
            "LOG_LEVEL": self.log_level,
            "MAX_FILE_SIZE": str(self.max_file_size),
            "REQUEST_TIMEOUT": f"{self.request_timeout}s",
            "MAX_RETRIES": str(self.max_retries),
        }


class ConfigurationError(Exception):
    """Raised when a required configuration value is missing or invalid."""


def _load_env() -> None:
    """Load .env file from the current directory or parent directories."""
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings from the environment.

    Settings are read once and cached for the lifetime of the process.
    Call this function wherever configuration is needed.
    """
    _load_env()
    return Settings(
        github_token=os.getenv("GITHUB_TOKEN", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        max_file_size=int(os.getenv("MAX_FILE_SIZE", "50000")),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", "30")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
    )
