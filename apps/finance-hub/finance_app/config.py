from dataclasses import dataclass
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    templates_dir: Path = BASE_DIR / "templates"
    static_dir: Path = BASE_DIR / "static"
    logs_dir: Path = BASE_DIR / "logs"
    mysql_host: str = os.getenv("MYSQL_HOST", "120.244.13.159")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "1479"))
    mysql_user: str = os.getenv("MYSQL_USER", "joey")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "Joey@2026!")
    mysql_db: str = os.getenv("MYSQL_DB", "finance_hub")
    pool_max_size: int = int(os.getenv("POOL_MAX_SIZE", "20"))
    session_cookie_name: str = os.getenv(
        "FINANCE_HUB_SESSION_COOKIE", "finance_hub_session"
    )
    session_secret: str = os.getenv(
        "FINANCE_HUB_SECRET", "finance-hub-dev-secret"
    )
    session_days: int = int(
        os.getenv("FINANCE_HUB_SESSION_DAYS", "180")
    )


settings = Settings()
