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


def print_table_columns(cur, table_name: str) -> None:
    cur.execute(
        """
        SELECT
            column_name AS column_name,
            column_type AS column_type
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    rows = list(cur.fetchall())
    print(f"[inspect] table={table_name} columns={len(rows)}")
    for row in rows:
        print(f"  - {row['column_name']}: {row['column_type']}")


def main() -> None:
    load_env_file(ENV_FILE)
    conn = connect()
    try:
        with conn.cursor() as cur:
            for table_name in [
                "ledger_books",
                "ledger_book_members",
                "ledger_categories",
                "ledger_entries",
                "ledger_entry_participants",
                "ledger_entry_attachments",
            ]:
                print_table_columns(cur, table_name)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
