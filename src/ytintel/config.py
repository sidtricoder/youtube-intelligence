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
    youtube_api_key: str = Field(default="", repr=False)
    google_project_id: str = ""
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    redirect_uri: str | None = None
    units_per_day: int = 10000
    searches_per_day: int = 100
    user_units_per_day: int = 1000
    anonymous_units_per_day: int | None = None
    anonymous_rate_limit: int = 30
    user_rate_limit: int = 120
    max_searches_per_request: int = 3
    trusted_proxies: str = ""
    local_base_url: str = "http://localhost:8000"

    @property
    def database_connection(self) -> str | None:
        selected = self.database_url_pooled or self.database_url
        return selected.get_secret_value() if selected and selected.get_secret_value() else None

    @model_validator(mode="after")
    def validate_configuration(self):
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
            self.redirect_uri = (
                self.redirect_uri or self.local_base_url.rstrip("/") + "/oauth/callback"
            )
        if self.render_external_url and not self.database_connection:
            raise ValueError(
                "Render requires DATABASE_URL or DATABASE_URL_POOLED; local database storage is not persistent"
            )
        if self.anonymous_units_per_day is None:
            self.anonymous_units_per_day = int(self.units_per_day * 0.3)
        if (
            min(
                self.user_units_per_day,
                self.anonymous_units_per_day,
                self.max_searches_per_request,
                self.anonymous_rate_limit,
                self.user_rate_limit,
            )
            < 0
        ):
            raise ValueError("Budgets and rate limits cannot be negative")
        from ipaddress import ip_network

        for item in self.trusted_proxies.split(","):
            if item.strip():
                ip_network(item.strip(), strict=False)
        if not self.public_base_url:
            parsed_local = urlparse(self.local_base_url)
            if (
                parsed_local.scheme != "http"
                or parsed_local.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed_local.path
                or parsed_local.query
                or parsed_local.fragment
            ):
                raise ValueError("Local base URL must be a loopback HTTP origin")
            expected = self.local_base_url.rstrip("/") + "/oauth/callback"
            if self.redirect_uri and self.redirect_uri != expected:
                raise ValueError(
                    "Local redirect URI must match YT_LOCAL_BASE_URL + /oauth/callback"
                )
            self.redirect_uri = expected
        return self
