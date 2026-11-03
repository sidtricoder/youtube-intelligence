import re
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YT_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )
    db_path: str = "data/ytintel.db"
    database_url: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DATABASE_URL", "YT_DATABASE_URL")
    )
    database_url_pooled: SecretStr | None = Field(
        default=None, validation_alias="DATABASE_URL_POOLED"
    )
    render_external_url: str = Field(default="", validation_alias="RENDER_EXTERNAL_URL")
    public_base_url: str = ""
    encryption_key: str = Field(repr=False)
    api_key: str = Field(repr=False)
    owner_key: str = Field(repr=False)
    # Optional dedicated credential that lets header-less MCP clients (such as Claude custom
    # connectors) call /mcp as https://host/mcp/?key=<value>. Empty disables the feature.
    mcp_url_key: str = Field(default="", repr=False)
    youtube_api_key: str = Field(default="", repr=False)
    google_project_id: str = ""
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    redirect_uri: str | None = None
    units_per_day: int = 10000
    searches_per_day: int = 100

    @property
    def database_connection(self) -> str | None:
        selected = self.database_url_pooled or self.database_url
        return selected.get_secret_value() if selected and selected.get_secret_value() else None

    @model_validator(mode="after")
    def validate_configuration(self):
        if min(len(self.api_key), len(self.owner_key)) < 32 or self.api_key == self.owner_key:
            raise ValueError("Use distinct random API and owner keys of at least 32 characters")
        if self.mcp_url_key:
            if len(self.mcp_url_key) < 32 or not re.fullmatch(
                r"[A-Za-z0-9._~-]+", self.mcp_url_key
            ):
                raise ValueError(
                    "YT_MCP_URL_KEY must be at least 32 URL-safe characters (letters, digits, . _ ~ -)"
                )
            if self.mcp_url_key in (self.api_key, self.owner_key):
                raise ValueError("YT_MCP_URL_KEY must differ from the API and owner keys")
        if self.units_per_day < 0 or self.searches_per_day < 0:
            raise ValueError("Quota limits cannot be negative")
        origin = (self.public_base_url or self.render_external_url).rstrip("/")
        if origin:
            parsed = urlparse(origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Public base URL must be an HTTPS origin without path, credentials or query"
                )
            callback = origin + "/oauth/callback"
            if self.redirect_uri and self.redirect_uri != callback:
                raise ValueError(
                    "YT_REDIRECT_URI must exactly equal the public origin plus /oauth/callback; remove the localhost setting on Render"
                )
            self.public_base_url = origin
            self.redirect_uri = callback
        else:
            self.redirect_uri = self.redirect_uri or "http://localhost:8000/oauth/callback"
        if self.render_external_url and not self.database_connection:
            raise ValueError(
                "Render requires DATABASE_URL or DATABASE_URL_POOLED; local database storage is not persistent"
            )
        return self
