"""Configuration owned exclusively by the automatic Merkle checkpointer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import parse_audit_merkle_public_keys
from app.services.merkle_audit_service import MerkleIntegrityError, validate_signing_configuration


MIN_CHECKPOINT_INTERVAL_SECONDS = 10
MAX_CHECKPOINT_INTERVAL_SECONDS = 86_400


class MerkleCheckpointerSettings(BaseSettings):
    """Minimal process settings; no backend, broker, or application secrets."""

    model_config = SettingsConfigDict(
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/channels"
    audit_merkle_checkpoint_enabled: bool = True
    audit_merkle_checkpoint_interval_seconds: int = Field(
        default=300,
        ge=MIN_CHECKPOINT_INTERVAL_SECONDS,
        le=MAX_CHECKPOINT_INTERVAL_SECONDS,
    )
    audit_merkle_batch_size: int = Field(default=256, ge=1, le=4096)
    audit_merkle_public_keys: Any = ""
    audit_merkle_signing_key_id: str = ""
    audit_merkle_signing_private_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"

    @field_validator("audit_merkle_public_keys", mode="before")
    @classmethod
    def _parse_public_keys(cls, value: Any) -> dict[str, str]:
        return parse_audit_merkle_public_keys(value)

    @field_validator("audit_merkle_signing_key_id", mode="before")
    @classmethod
    def _strip_key_id(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> str:
        return str(value or "INFO").strip().upper()

    @model_validator(mode="after")
    def _validate_signing_configuration(self) -> "MerkleCheckpointerSettings":
        if not self.audit_merkle_checkpoint_enabled:
            return self

        private_key = self.audit_merkle_signing_private_key.get_secret_value().strip()
        if not private_key:
            raise ValueError(
                "AUDIT_MERKLE_SIGNING_PRIVATE_KEY is required when automatic checkpointing is enabled"
            )
        try:
            validate_signing_configuration(
                self.audit_merkle_signing_key_id,
                private_key,
                self.audit_merkle_public_keys,
            )
        except MerkleIntegrityError as exc:
            raise ValueError(f"Merkle signing configuration is invalid [{exc.code}]: {exc}") from None
        return self
