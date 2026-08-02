"""Typed application configuration.

All configuration is loaded from environment variables (optionally via a local
``.env`` file, which is git-ignored). Every credential is stored as a
:class:`pydantic.SecretStr` so it can never be accidentally logged, printed, or
serialized in a repr — call :meth:`Settings.github_token_value` /
:meth:`Settings.openai_api_key_value` to unwrap a secret at the point of use.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATA_DIR = Path.home() / ".opensource-scout"


class Settings(BaseSettings):
    """Application configuration.

    Values are read from environment variables first, then from a ``.env``
    file in the current working directory if present. See ``.env.example``
    for the full list of supported variables and their meaning.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Credentials (never logged; never included in repr output) ---
    github_token: SecretStr | None = Field(default=None, alias="GITHUB_TOKEN")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")

    # --- Model routing (logical roles; never hard-coded in application code) ---
    openai_model_fast: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL_FAST")
    openai_model_reasoning: str = Field(default="gpt-4o", alias="OPENAI_MODEL_REASONING")
    openai_model_coding: str = Field(default="gpt-4o", alias="OPENAI_MODEL_CODING")

    # --- Cost and token controls ---
    daily_openai_budget_usd: float = Field(default=5.0, alias="DAILY_OPENAI_BUDGET_USD")
    monthly_openai_budget_usd: float = Field(default=50.0, alias="MONTHLY_OPENAI_BUDGET_USD")
    max_llm_calls_per_workflow: int = Field(default=40, alias="MAX_LLM_CALLS_PER_WORKFLOW")
    max_input_tokens_per_call: int = Field(default=12_000, alias="MAX_INPUT_TOKENS_PER_CALL")
    max_output_tokens_per_call: int = Field(default=2_000, alias="MAX_OUTPUT_TOKENS_PER_CALL")

    # --- GitHub client behavior ---
    github_concurrency: int = Field(default=4, alias="GITHUB_CONCURRENCY")

    # --- Local storage ---
    data_dir: Path = Field(default=DEFAULT_DATA_DIR, alias="OSS_DATA_DIR")
    # None means "not explicitly set"; see the workspace_dir property below,
    # which derives it from data_dir. A bare `default=DEFAULT_DATA_DIR /
    # "workspaces"` would freeze the workspace path to the real home
    # directory even when OSS_DATA_DIR is overridden, since Pydantic
    # evaluates that default once at class-definition time, not per instance.
    workspace_dir_override: Path | None = Field(default=None, alias="OSS_WORKSPACE_DIR")

    # --- Logging ---
    log_level: str = Field(default="INFO", alias="OSS_LOG_LEVEL")
    log_json: bool = Field(default=True, alias="OSS_LOG_JSON")

    @field_validator("github_concurrency")
    @classmethod
    def _positive_concurrency(cls, value: int) -> int:
        if value < 1:
            raise ValueError("GITHUB_CONCURRENCY must be at least 1")
        return value

    @field_validator("daily_openai_budget_usd", "monthly_openai_budget_usd")
    @classmethod
    def _non_negative_budget(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Budgets must be non-negative")
        return value

    @property
    def workspace_dir(self) -> Path:
        return self.workspace_dir_override or (self.data_dir / "workspaces")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "opensource_scout.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    def github_token_value(self) -> str | None:
        """Unwrap the GitHub token. Call only at the point of use (e.g. building
        an Authorization header) — never store or log the returned value."""
        return self.github_token.get_secret_value() if self.github_token else None

    def openai_api_key_value(self) -> str | None:
        """Unwrap the OpenAI API key. Call only at the point of use."""
        return self.openai_api_key.get_secret_value() if self.openai_api_key else None

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Load settings from the environment. Raises ``pydantic.ValidationError``
    on malformed values (e.g. a negative budget or non-positive concurrency)."""
    return Settings()
