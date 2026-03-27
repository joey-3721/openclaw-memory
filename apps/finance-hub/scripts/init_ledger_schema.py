from __future__ import annotations

from pathlib import Path
import os

import pymysql


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs from the local env file."""
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
        autocommit=False,
    )


TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ledger_books (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '账本主键',
        owner_user_id INT NOT NULL COMMENT '账本拥有者，关联 finance_users.id',
        book_type VARCHAR(20) NOT NULL COMMENT '账本类型：MAIN 主账本、TRAVEL 旅行账本、THEME 其他主题账本',
        name VARCHAR(120) NOT NULL COMMENT '账本名称',
        description VARCHAR(255) NULL COMMENT '账本描述',
        base_currency VARCHAR(10) NOT NULL DEFAULT 'CNY' COMMENT '账本基础币种',
        is_default_main TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否默认主账本，主账本不可删除',
        cover_theme VARCHAR(40) NULL COMMENT '账本视觉主题，例如 ocean / sunrise / city',
        country_code VARCHAR(8) NULL COMMENT '旅行账本国家或地区代码，例如 KR / CN',
        country_name VARCHAR(80) NULL COMMENT '国家或地区中文名',
        region_name VARCHAR(80) NULL COMMENT '省份/州/大区名称，中国旅行可存省份',
        city_name VARCHAR(80) NULL COMMENT '城市名称',
        display_location VARCHAR(160) NULL COMMENT '前端展示的位置摘要，例如 韩国·首尔',
        start_date DATE NULL COMMENT '旅行开始日期，可为空',
        end_date DATE NULL COMMENT '旅行结束日期，可为空',
        is_archived TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否归档',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        INDEX idx_ledger_books_owner (owner_user_id),
        INDEX idx_ledger_books_type (book_type),
        INDEX idx_ledger_books_country (country_code),
        CONSTRAINT fk_ledger_books_owner
            FOREIGN KEY (owner_user_id) REFERENCES finance_users(id)
            ON DELETE CASCADE
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='记账账本主表：保存主账本、旅行账本及其他主题账本'
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_book_members (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '账本成员主键',
        ledger_book_id BIGINT NOT NULL COMMENT '所属账本 ID',
        user_id INT NULL COMMENT '站内用户 ID，可为空以兼容外部参与人',
        member_name VARCHAR(80) NOT NULL COMMENT '成员显示名',
        member_role VARCHAR(20) NOT NULL DEFAULT 'MEMBER' COMMENT '成员角色：OWNER / MEMBER / VIEWER',
        can_edit TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否允许记账和编辑',
        joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        UNIQUE KEY uniq_book_member_name (ledger_book_id, member_name),
        INDEX idx_book_members_book (ledger_book_id),
        INDEX idx_book_members_user (user_id),
        CONSTRAINT fk_book_members_book
            FOREIGN KEY (ledger_book_id) REFERENCES ledger_books(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_book_members_user
            FOREIGN KEY (user_id) REFERENCES finance_users(id)
            ON DELETE SET NULL
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='账本成员表：保存共享账本的参与人、角色和编辑权限'
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_categories (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '分类主键',
        category_code VARCHAR(30) NOT NULL COMMENT '分类代码，例如 DINING / TRANSPORT',
        category_name VARCHAR(60) NOT NULL COMMENT '分类名称',
        icon_key VARCHAR(40) NOT NULL COMMENT '前端图标 key，对应 SVG 图标主题',
        color_token VARCHAR(20) NOT NULL DEFAULT 'sky' COMMENT '分类颜色主题 token',
        sort_order INT NOT NULL DEFAULT 0 COMMENT '排序值，越小越靠前',
        is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        UNIQUE KEY uniq_ledger_category_code (category_code)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='记账分类字典表：保存餐饮、交通、住宿等支出分类定义'
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_entries (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '账单主键',
        ledger_book_id BIGINT NOT NULL COMMENT '所属账本 ID',
        created_by_member_id BIGINT NULL COMMENT '创建该账单的成员 ID',
        payer_member_id BIGINT NULL COMMENT '实际付款人成员 ID',
        category_id BIGINT NULL COMMENT '分类 ID',
        entry_type VARCHAR(20) NOT NULL DEFAULT 'EXPENSE' COMMENT '账单类型：EXPENSE 支出、INCOME 收入、TRANSFER 转账',
        split_mode VARCHAR(20) NOT NULL DEFAULT 'NONE' COMMENT '分摊方式：NONE / EQUAL / SHARE / FIXED',
        title VARCHAR(160) NOT NULL COMMENT '账单标题',
        merchant_name VARCHAR(160) NULL COMMENT '商户或地点名称，例如餐厅/酒店/景点',
        note VARCHAR(500) NULL COMMENT '账单备注',
        amount DECIMAL(16, 2) NOT NULL COMMENT '原始账单金额',
        currency VARCHAR(10) NOT NULL DEFAULT 'CNY' COMMENT '账单币种',
        exchange_rate_to_base DECIMAL(18, 8) NULL COMMENT '换算到账本基础币种的汇率',
        amount_in_base DECIMAL(16, 2) NULL COMMENT '换算后的基础币种金额',
        occurred_at DATETIME NOT NULL COMMENT '实际发生时间',
        country_code VARCHAR(8) NULL COMMENT '账单发生国家或地区代码',
        country_name VARCHAR(80) NULL COMMENT '账单发生国家或地区名称',
        region_name VARCHAR(80) NULL COMMENT '账单发生的省份/州',
        city_name VARCHAR(80) NULL COMMENT '账单发生城市',
        location_label VARCHAR(180) NULL COMMENT '地点摘要，用于前端展示',
        address_text VARCHAR(255) NULL COMMENT '详细地址文本',
        latitude DECIMAL(10, 7) NULL COMMENT '纬度，后续可用于地图标记',
        longitude DECIMAL(10, 7) NULL COMMENT '经度，后续可用于地图标记',
        ai_source VARCHAR(30) NULL COMMENT 'AI 来源，例如 MINIMAX / SHORTCUTS / MANUAL',
        ai_confidence DECIMAL(5, 2) NULL COMMENT 'AI 识别置信度，0-100',
        ai_raw_payload JSON NULL COMMENT 'AI 原始识别结果 JSON，便于复查',
        subcategory_name VARCHAR(80) NULL COMMENT '二级分类名称，例如 饮品 / 地铁 / 酒店',
        shared_group_key VARCHAR(64) NULL COMMENT '共享记录分组键，用于主账本同步与跨账本结算联动',
        is_mirror TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否镜像记录，1 表示同步到其他账本的副本',
        mirror_source_entry_id BIGINT NULL COMMENT '镜像来源账单 ID，指向原始记录',
        is_settled TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已结算，1 表示现实中已付款完毕',
        settled_at DATETIME NULL COMMENT '结算完成时间',
        status VARCHAR(20) NOT NULL DEFAULT 'CONFIRMED' COMMENT '账单状态：DRAFT / CONFIRMED / SETTLED / VOID',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        INDEX idx_ledger_entries_book (ledger_book_id),
        INDEX idx_ledger_entries_payer (payer_member_id),
        INDEX idx_ledger_entries_category (category_id),
        INDEX idx_ledger_entries_time (occurred_at),
        INDEX idx_ledger_entries_country_city (country_code, city_name),
        CONSTRAINT fk_ledger_entries_book
            FOREIGN KEY (ledger_book_id) REFERENCES ledger_books(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_ledger_entries_creator
            FOREIGN KEY (created_by_member_id) REFERENCES ledger_book_members(id)
            ON DELETE SET NULL,
        CONSTRAINT fk_ledger_entries_payer
            FOREIGN KEY (payer_member_id) REFERENCES ledger_book_members(id)
            ON DELETE SET NULL,
        CONSTRAINT fk_ledger_entries_category
            FOREIGN KEY (category_id) REFERENCES ledger_categories(id)
            ON DELETE SET NULL,
        CONSTRAINT fk_ledger_entries_mirror_source
            FOREIGN KEY (mirror_source_entry_id) REFERENCES ledger_entries(id)
            ON DELETE SET NULL
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='账单主表：保存一笔收入/支出的金额、位置、AI 识别结果和分账规则'
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_entry_participants (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '账单参与人主键',
        ledger_entry_id BIGINT NOT NULL COMMENT '所属账单 ID',
        member_id BIGINT NOT NULL COMMENT '参与分摊的成员 ID',
        share_ratio DECIMAL(10, 4) NOT NULL DEFAULT 1.0000 COMMENT '份额值，按份额分时使用',
        fixed_amount DECIMAL(16, 2) NULL COMMENT '固定分摊金额，按固定金额分时使用',
        amount_owed_base DECIMAL(16, 2) NULL COMMENT '该成员应承担的基础币种金额',
        is_included TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否参与本次分摊',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        UNIQUE KEY uniq_entry_member (ledger_entry_id, member_id),
        INDEX idx_entry_participants_member (member_id),
        CONSTRAINT fk_entry_participants_entry
            FOREIGN KEY (ledger_entry_id) REFERENCES ledger_entries(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_entry_participants_member
            FOREIGN KEY (member_id) REFERENCES ledger_book_members(id)
            ON DELETE CASCADE
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='账单参与人表：保存每笔账单里谁参与分摊、份额和应承担金额'
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_entry_attachments (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '附件主键',
        ledger_entry_id BIGINT NOT NULL COMMENT '所属账单 ID',
        file_name VARCHAR(255) NOT NULL COMMENT '原始文件名',
        file_url VARCHAR(500) NOT NULL COMMENT '附件存储地址或对象存储 URL',
        mime_type VARCHAR(120) NULL COMMENT '文件 MIME 类型，例如 image/png',
        file_size BIGINT NULL COMMENT '文件大小，单位字节',
        source_type VARCHAR(30) NOT NULL DEFAULT 'MANUAL' COMMENT '附件来源：MANUAL / SHORTCUTS / AI_IMPORT',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_attachments_entry (ledger_entry_id),
        CONSTRAINT fk_attachments_entry
            FOREIGN KEY (ledger_entry_id) REFERENCES ledger_entries(id)
            ON DELETE CASCADE
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='账单附件表：保存截图、小票、照片等素材，供 AI 识别或人工查看'
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_settlement_items (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '结算关系主键',
        ledger_book_id BIGINT NOT NULL COMMENT '所属账本 ID',
        ledger_entry_id BIGINT NOT NULL COMMENT '来源账单 ID',
        from_member_id BIGINT NOT NULL COMMENT '应付款成员 ID，谁需要转出这笔钱',
        to_member_id BIGINT NOT NULL COMMENT '收款成员 ID，谁应该收到这笔钱',
        amount_base DECIMAL(16, 2) NOT NULL COMMENT '应结算金额，使用账本基础币种',
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING' COMMENT '结算状态：PENDING 待结算、SETTLED 已结清、VOID 作废',
        settled_at DATETIME NULL COMMENT '该条关系直接结清的时间，仅对直接标记已结算的账单生效',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        INDEX idx_settlement_items_book_status (ledger_book_id, status),
        INDEX idx_settlement_items_entry (ledger_entry_id),
        INDEX idx_settlement_items_from_to (from_member_id, to_member_id),
        CONSTRAINT fk_settlement_items_book
            FOREIGN KEY (ledger_book_id) REFERENCES ledger_books(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_settlement_items_entry
            FOREIGN KEY (ledger_entry_id) REFERENCES ledger_entries(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_settlement_items_from_member
            FOREIGN KEY (from_member_id) REFERENCES ledger_book_members(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_settlement_items_to_member
            FOREIGN KEY (to_member_id) REFERENCES ledger_book_members(id)
            ON DELETE CASCADE
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='结算明细表：逐条保存谁该给谁多少钱，是共享账本多人分账的原始欠款关系'
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_settlement_payments (
        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '实际付款记录主键',
        ledger_book_id BIGINT NOT NULL COMMENT '所属账本 ID',
        from_member_id BIGINT NOT NULL COMMENT '实际付款成员 ID',
        to_member_id BIGINT NOT NULL COMMENT '实际收款成员 ID',
        amount_base DECIMAL(16, 2) NOT NULL COMMENT '本次现实中已经支付的金额，使用账本基础币种',
        note VARCHAR(255) NULL COMMENT '付款说明，例如 手动结清 / 批量结清',
        created_by_member_id BIGINT NULL COMMENT '创建这条付款记录的成员 ID',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_settlement_payments_book (ledger_book_id, created_at),
        INDEX idx_settlement_payments_from_to (from_member_id, to_member_id),
        CONSTRAINT fk_settlement_payments_book
            FOREIGN KEY (ledger_book_id) REFERENCES ledger_books(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_settlement_payments_from_member
            FOREIGN KEY (from_member_id) REFERENCES ledger_book_members(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_settlement_payments_to_member
            FOREIGN KEY (to_member_id) REFERENCES ledger_book_members(id)
            ON DELETE CASCADE,
        CONSTRAINT fk_settlement_payments_creator
            FOREIGN KEY (created_by_member_id) REFERENCES ledger_book_members(id)
            ON DELETE SET NULL
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
      COMMENT='结算付款记录表：保存现实中谁已经给谁转过多少钱，用来抵扣未结算关系并计算最优路径'
    """,
]


CATEGORY_SEEDS = [
    ("DINING", "餐饮", "dining", "mint", 10),
    ("TRANSPORT", "交通", "transport", "sky", 20),
    ("LODGING", "住宿", "lodging", "amber", 30),
    ("SHOPPING", "购物", "shopping", "violet", 40),
    ("GAME", "游戏", "game", "violet", 50),
    ("MEDICAL", "医疗", "medical", "sky", 60),
    ("SERVICE", "服务", "service", "rose", 70),
    ("BILL", "账单", "bill", "amber", 80),
    ("OTHER", "其他", "other", "amber", 999),
]


ALTER_STATEMENTS = [
    """
    ALTER TABLE ledger_entries
    ADD COLUMN subcategory_name VARCHAR(80) NULL
        COMMENT '二级分类名称，例如 饮品 / 地铁 / 酒店'
    AFTER occurred_at
    """,
    """
    ALTER TABLE ledger_entries
    ADD COLUMN shared_group_key VARCHAR(64) NULL
        COMMENT '共享记录分组键，用于主账本同步与跨账本结算联动'
    AFTER note
    """,
    """
    ALTER TABLE ledger_entries
    ADD COLUMN is_mirror TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '是否镜像记录，1 表示同步到其他账本的副本'
    AFTER shared_group_key
    """,
    """
    ALTER TABLE ledger_entries
    ADD COLUMN mirror_source_entry_id BIGINT NULL
        COMMENT '镜像来源账单 ID，指向原始记录'
    AFTER is_mirror
    """,
    """
    ALTER TABLE ledger_entries
    ADD COLUMN is_settled TINYINT(1) NOT NULL DEFAULT 0
        COMMENT '是否已结算，1 表示现实中已付款完毕'
    AFTER mirror_source_entry_id
    """,
    """
    ALTER TABLE ledger_entries
    ADD COLUMN settled_at DATETIME NULL
        COMMENT '结算完成时间'
    AFTER is_settled
    """,
    """
    ALTER TABLE ledger_entries
    ADD INDEX idx_ledger_entries_settled (ledger_book_id, is_settled, occurred_at)
    """,
    """
    ALTER TABLE ledger_entries
    ADD INDEX idx_ledger_entries_group_key (shared_group_key)
    """,
    """
    ALTER TABLE ledger_entries
    ADD INDEX idx_ledger_entries_mirror_source (mirror_source_entry_id)
    """,
    """
    ALTER TABLE ledger_entries
    ADD CONSTRAINT fk_ledger_entries_mirror_source
        FOREIGN KEY (mirror_source_entry_id) REFERENCES ledger_entries(id)
        ON DELETE SET NULL
    """,
]


def seed_categories(cur) -> None:
    cur.executemany(
        """
        INSERT INTO ledger_categories
            (category_code, category_name, icon_key, color_token, sort_order)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            category_name = VALUES(category_name),
            icon_key = VALUES(icon_key),
            color_token = VALUES(color_token),
            sort_order = VALUES(sort_order),
            is_active = 1
        """,
        CATEGORY_SEEDS,
    )


def main() -> None:
    load_env_file(ENV_FILE)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION lock_wait_timeout = 2")
            for index, statement in enumerate(TABLE_STATEMENTS, start=1):
                try:
                    print(f"[ledger-schema] table step {index}/{len(TABLE_STATEMENTS)}", flush=True)
                    cur.execute(statement)
                except Exception as exc:
                    print(f"[ledger-schema] table step skipped: {exc}", flush=True)
            for index, statement in enumerate(ALTER_STATEMENTS, start=1):
                try:
                    print(f"[ledger-schema] alter step {index}/{len(ALTER_STATEMENTS)}", flush=True)
                    cur.execute(statement)
                except Exception as exc:
                    print(f"[ledger-schema] alter step skipped: {exc}", flush=True)
            print("[ledger-schema] seeding categories", flush=True)
            seed_categories(cur)
        conn.commit()
        print("Ledger schema initialized successfully.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
