"""Instance settings, read from `TEAPOT_*` environment variables and the env file (D37, D43).

Every setting is listed with its default in `template/teapot.env.example`.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ENV_FILE = Path("teapot.env")


class Settings(BaseSettings):
    """Everything an instance is configured with. Secrets are `SecretStr`, so they never print."""

    model_config = SettingsConfigDict(env_prefix="TEAPOT_", extra="ignore", frozen=True)

    discord_token: SecretStr = SecretStr("")
    dev_guild_id: int | None = None
    dev_mode: bool = False

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "teapot"
    db_owner_user: str = "teapot_owner"
    db_role_prefix: str = "teapot"
    db_owner_password: SecretStr = SecretStr("")
    db_app_password: SecretStr = SecretStr("")
    db_plugins_password: SecretStr = SecretStr("")
    db_pool_size: int = Field(default=10, ge=1)

    http_host: str = "127.0.0.1"
    http_port: int = 8780
    public_url: str | None = None

    disabled_plugins: Annotated[tuple[str, ...], NoDecode] = ()
    guild_retention_days: int = Field(default=30, ge=0)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["auto", "text", "json"] = "auto"

    @field_validator("disabled_plugins", mode="before")
    @classmethod
    def _split_plugin_list(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def resolved_log_format(self) -> Literal["text", "json"]:
        """Readable text in dev mode, JSON lines otherwise, unless set explicitly."""
        if self.log_format == "auto":
            return "text" if self.dev_mode else "json"
        return self.log_format


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE) -> Settings:
    """Read the settings. Variables in the environment win over the env file."""
    path = env_file if env_file is not None and env_file.exists() else None
    return Settings(_env_file=path)  # pyright: ignore[reportCallIssue]
