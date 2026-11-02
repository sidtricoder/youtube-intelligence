from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YT_", env_file=".env", extra="ignore")
    db_path: str = "data/ytintel.db"
    encryption_key: str
    api_key: str
    owner_key: str
    youtube_api_key: str = ""
    google_project_id: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    redirect_uri: str = "http://localhost:8000/oauth/callback"
    units_per_day: int = 10000
    searches_per_day: int = 100

    @model_validator(mode="after")
    def secure_keys(self):
        if min(len(self.api_key), len(self.owner_key)) < 32 or self.api_key == self.owner_key:
            raise ValueError("Use distinct random API and owner keys of at least 32 characters")
        if self.units_per_day < 0 or self.searches_per_day < 0:
            raise ValueError("Quota limits cannot be negative")
        return self
