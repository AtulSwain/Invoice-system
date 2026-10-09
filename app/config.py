"""Configuration from environment variables. Nothing secret lives in the code."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _secret_key(data_dir: Path) -> str:
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    # Local use: create a random key once and keep it in the data folder (not in git).
    key_file = data_dir / "secret_key.txt"
    data_dir.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


def load_config() -> dict:
    data_dir = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")).resolve()
    production = os.environ.get("APP_ENV", "development").lower() == "production"
    return {
        "DATA_DIR": data_dir,
        "DATABASE_PATH": Path(os.environ.get("DATABASE_PATH", data_dir / "invoices.db")).resolve(),
        "BACKUP_DIR": Path(os.environ.get("BACKUP_DIR", BASE_DIR / "backups")).resolve(),
        "SECRET_KEY": _secret_key(data_dir),
        "PRODUCTION": production,
        "AUTO_BACKUP": os.environ.get("AUTO_BACKUP", "1") != "0",
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "MAX_CONTENT_LENGTH": 5 * 1024 * 1024,  # uploads (logo, CSV) up to 5 MB
    }
