from __future__ import annotations

from pathlib import Path
import os

import pymysql


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"


MISSING_COLUMN_ALTERS = [
    (
        "subcategory_name",
        """
        ALTER TABLE ledger_entries
        ADD COLUMN subcategory_name VARCHAR(80) NULL
            COMMENT '二级分类名称，例如 饮品 / 地铁 / 酒店'
        AFTER occurred_at
        """,
    ),
    (
        "shared_group_key",
        """
        ALTER TABLE ledger_entries
        ADD COLUMN shared_group_key VARCHAR(64) NULL
            COMMENT '共享记录分组键，用于主账本同步与跨账本结算联动'
        AFTER note
        """,
    ),
    (
        "is_mirror",
        """
        ALTER TABLE ledger_entries
        ADD COLUMN is_mirror TINYINT(1) NOT NULL DEFAULT 0
            COMMENT '是否镜像记录，1 表示同步到其他账本的副本'
        AFTER shared_group_key
        """,
    ),
    (
        "mirror_source_entry_id",
        """
        ALTER TABLE ledger_entries
        ADD COLUMN mirror_source_entry_id BIGINT NULL
            COMMENT '镜像来源账单 ID，指向原始记录'
        AFTER is_mirror
        """,
    ),
    (
        "is_settled",
        """
        ALTER TABLE ledger_entries
        ADD COLUMN is_settled TINYINT(1) NOT NULL DEFAULT 0
            COMMENT '是否已结算，1 表示现实中已付款完毕'
        AFTER mirror_source_entry_id
        """,
    ),
    (
        "settled_at",
        """
        ALTER TABLE ledger_entries
        ADD COLUMN settled_at DATETIME NULL
            COMMENT '结算完成时间'
        AFTER is_settled
        """,
    ),
]

INDEX_ALTERS = [
    (
        "idx_ledger_entries_settled",
        """
        ALTER TABLE ledger_entries
        ADD INDEX idx_ledger_entries_settled
            (ledger_book_id, is_settled, occurred_at)
        """,
    ),
    (
        "idx_ledger_entries_group_key",
        """
        ALTER TABLE ledger_entries
        ADD INDEX idx_ledger_entries_group_key (shared_group_key)
        """,
    ),
    (
        "idx_ledger_entries_mirror_source",
        """
        ALTER TABLE ledger_entries
        ADD INDEX idx_ledger_entries_mirror_source (mirror_source_entry_id)
        """,
    ),
]

FK_ALTER = """
ALTER TABLE ledger_entries
ADD CONSTRAINT fk_ledger_entries_mirror_source
    FOREIGN KEY (mirror_source_entry_id) REFERENCES ledger_entries(id)
    ON DELETE SET NULL
"""


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


def fetch_existing_columns(cur) -> set[str]:
    cur.execute(
        """
        SELECT column_name AS column_name
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'ledger_entries'
        """
    )
    return {row["column_name"] for row in cur.fetchall()}


def fetch_existing_indexes(cur) -> set[str]:
    cur.execute(
        """
        SELECT DISTINCT index_name AS index_name
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = 'ledger_entries'
        """
    )
    return {row["index_name"] for row in cur.fetchall()}


def fetch_existing_constraints(cur) -> set[str]:
    cur.execute(
        """
        SELECT constraint_name AS constraint_name
        FROM information_schema.table_constraints
        WHERE table_schema = DATABASE()
          AND table_name = 'ledger_entries'
        """
    )
    return {row["constraint_name"] for row in cur.fetchall()}


def main() -> None:
    load_env_file(ENV_FILE)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION lock_wait_timeout = 2")
            columns = fetch_existing_columns(cur)
            print(f"[fix] existing columns: {sorted(columns)}")
            for column_name, sql in MISSING_COLUMN_ALTERS:
                if column_name in columns:
                    print(f"[fix] column exists: {column_name}")
                    continue
                try:
                    print(f"[fix] add column: {column_name}")
                    cur.execute(sql)
                except Exception as exc:
                    print(f"[fix] add column failed: {column_name} -> {exc}")

            indexes = fetch_existing_indexes(cur)
            print(f"[fix] existing indexes: {sorted(indexes)}")
            for index_name, sql in INDEX_ALTERS:
                if index_name in indexes:
                    print(f"[fix] index exists: {index_name}")
                    continue
                try:
                    print(f"[fix] add index: {index_name}")
                    cur.execute(sql)
                except Exception as exc:
                    print(f"[fix] add index failed: {index_name} -> {exc}")

            constraints = fetch_existing_constraints(cur)
            if "fk_ledger_entries_mirror_source" in constraints:
                print("[fix] fk exists: fk_ledger_entries_mirror_source")
            else:
                try:
                    print("[fix] add fk: fk_ledger_entries_mirror_source")
                    cur.execute(FK_ALTER)
                except Exception as exc:
                    print(f"[fix] add fk failed: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
