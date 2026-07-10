from typing import List

from pydantic_settings import BaseSettings

# Secrets that ship in source control or docs and must never reach production.
WEAK_SECRET_KEYS = {
    "",
    "dev-secret-change-me",
    "change-this-to-a-random-secret",
}


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql://eduflow:eduflow@localhost:5432/eduflow_ai"
    SECRET_KEY: str = "dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    GROQ_API_KEY: str = ""
    # Comma-separated allowlist, e.g. "https://admin.school.edu,https://app.school.edu"
    CORS_ORIGINS: str = ""

    class Config:
        env_file = ".env"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


def _assert_production_safe(cfg: "Settings") -> None:
    problems = []
    if cfg.SECRET_KEY in WEAK_SECRET_KEYS:
        problems.append("SECRET_KEY is unset or a known default; generate one with `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`")
    if not cfg.cors_origins:
        problems.append("CORS_ORIGINS must list the exact frontend origins")
    elif "*" in cfg.cors_origins:
        problems.append("CORS_ORIGINS may not contain '*'")
    if problems:
        raise RuntimeError(
            "Refusing to start with ENVIRONMENT=production:\n  - " + "\n  - ".join(problems)
        )


settings = Settings()

if settings.is_production:
    _assert_production_safe(settings)
