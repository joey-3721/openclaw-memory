from __future__ import annotations

from pathlib import Path
import os

import pymysql


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def connect():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "finance_hub"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def main() -> None:
    load_env_file(ENV_FILE)
    conn = connect()
    try:
        with conn.cursor() as cur:
            print("[locks] processlist", flush=True)
            cur.execute("SHOW FULL PROCESSLIST")
            rows = list(cur.fetchall())
            for row in rows:
                if row.get("db") != os.getenv("MYSQL_DB", "finance_hub"):
                    continue
                print(
                    {
                        "id": row.get("Id"),
                        "user": row.get("User"),
                        "host": row.get("Host"),
                        "command": row.get("Command"),
                        "time": row.get("Time"),
                        "state": row.get("State"),
                        "info": row.get("Info"),
                    },
                    flush=True,
                )

            try:
                print("[locks] metadata_locks", flush=True)
                cur.execute(
                    """
                    SELECT
                        object_type,
                        object_schema,
                        object_name,
                        lock_type,
                        lock_duration,
                        lock_status,
                        owner_thread_id
                    FROM performance_schema.metadata_locks
                    WHERE object_schema = DATABASE()
                      AND object_name = 'ledger_entries'
                    """
                )
                for row in cur.fetchall():
                    print(row, flush=True)
            except Exception as exc:
                print(f"[locks] metadata_locks unavailable: {exc}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
