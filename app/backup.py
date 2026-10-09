"""Daily database backup, keeping the last 30 days.

Runs automatically (checked at most once an hour while the app is in use) and
can also be run by hand or from a scheduler:  python -m app.backup
"""
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

KEEP_DAYS = 30
_NAME_RE = re.compile(r"^invoices-(\d{4}-\d{2}-\d{2})\.db$")


def run_backup(db_path, backup_dir, today: date, keep_days: int = KEEP_DAYS):
    """Create today's backup if missing and delete backups older than keep_days.
    Returns the path of today's backup."""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"invoices-{today.isoformat()}.db"
    if not target.exists():
        tmp = target.with_suffix(".tmp")
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)  # consistent copy even while the app is writing
        finally:
            dst.close()
            src.close()
        tmp.replace(target)
    cutoff = today - timedelta(days=keep_days - 1)
    for f in backup_dir.iterdir():
        m = _NAME_RE.match(f.name)
        if m and date.fromisoformat(m.group(1)) < cutoff:
            f.unlink()
    return target


if __name__ == "__main__":
    from .config import load_config
    from .db import today_ist

    cfg = load_config()
    print("Backup written to", run_backup(cfg["DATABASE_PATH"], cfg["BACKUP_DIR"], today_ist()))
