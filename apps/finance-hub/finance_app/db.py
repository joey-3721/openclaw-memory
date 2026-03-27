"""Database connection pool using DBUtils.PooledDB."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Generator

import pymysql
import pymysql.cursors
from dbutils.pooled_db import PooledDB

from .config import settings

_pool: PooledDB | None = None


def init_pool() -> None:
    """Initialize the global connection pool. Call once at startup."""
    global _pool
    _pool = PooledDB(
        creator=pymysql,
        maxconnections=settings.pool_max_size,
        mincached=2,
        maxcached=5,
        blocking=True,
        maxusage=None,
        setsession=["SET time_zone='+08:00'"],
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def close_pool() -> None:
    """Close the pool. Call at shutdown."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Generator:
    """Yield a pooled connection, auto-return on exit."""
    assert _pool is not None, "Pool not initialized. Call init_pool() first."
    conn = _pool.connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor() -> Generator:
    """Yield a cursor with auto-commit/rollback and connection return."""
    with get_conn() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def ensure_schema() -> None:
    """Create core tables if they don't exist. Call once at startup."""
    with get_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS finance_users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(120) NOT NULL UNIQUE,
                password_plain VARCHAR(255) NULL,
                password_hash VARCHAR(255) NULL,
                display_name VARCHAR(120) NULL,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                last_login_at DATETIME NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_types (
                id INT AUTO_INCREMENT PRIMARY KEY,
                type_code VARCHAR(20) NOT NULL UNIQUE
                    COMMENT 'STOCK, BOND, CASH',
                type_name VARCHAR(60) NOT NULL
                    COMMENT '股票, 债券, 现金',
                currency VARCHAR(10) NOT NULL DEFAULT 'USD',
                has_market_price TINYINT(1) NOT NULL DEFAULT 0
                    COMMENT '1=needs daily price fetch',
                needs_ticker TINYINT(1) NOT NULL DEFAULT 0
                    COMMENT '1=requires ticker symbol',
                display_order INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_assets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                asset_type_id INT NOT NULL,
                ticker_symbol VARCHAR(20) NULL
                    COMMENT 'e.g. QQQ, null for cash',
                asset_name VARCHAR(120) NOT NULL
                    COMMENT 'User-facing name',
                currency VARCHAR(10) NOT NULL DEFAULT 'USD',
                notes TEXT NULL,
                include_price_pnl TINYINT(1) NOT NULL DEFAULT 1
                    COMMENT '1=include price P&L in cards, 0=principal only',
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_user_assets_user (user_id),
                INDEX idx_user_assets_user_active_created
                    (user_id, is_active, created_at),
                INDEX idx_user_assets_ticker (ticker_symbol),
                CONSTRAINT fk_user_assets_user
                    FOREIGN KEY (user_id) REFERENCES finance_users(id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_user_assets_type
                    FOREIGN KEY (asset_type_id) REFERENCES asset_types(id)
                    ON DELETE RESTRICT
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_transactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_asset_id INT NOT NULL,
                direction ENUM('BUY','SELL') NOT NULL,
                quantity DECIMAL(16, 6) NOT NULL
                    COMMENT 'Shares/units/USD amount',
                price_per_unit DECIMAL(16, 6) NULL
                    COMMENT 'USD price per share; NULL for cash',
                total_amount DECIMAL(16, 2) NOT NULL
                    COMMENT 'quantity * price or USD amount for cash',
                fee DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                transaction_date DATE NOT NULL,
                source_system VARCHAR(20) NOT NULL DEFAULT 'MANUAL'
                    COMMENT 'MANUAL or IBKR',
                note TEXT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_asset_tx_asset (user_asset_id),
                INDEX idx_asset_tx_asset_date (user_asset_id, transaction_date),
                INDEX idx_asset_tx_asset_date_id
                    (user_asset_id, transaction_date, id),
                INDEX idx_asset_tx_date (transaction_date),
                CONSTRAINT fk_asset_tx_asset
                    FOREIGN KEY (user_asset_id)
                    REFERENCES user_assets(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        try:
            cur.execute(
                """
                ALTER TABLE asset_transactions
                ADD COLUMN source_system VARCHAR(20) NOT NULL
                    DEFAULT 'MANUAL'
                    COMMENT 'MANUAL or IBKR'
                AFTER transaction_date
                """
            )
        except Exception:
            pass

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_cash_flows (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_asset_id INT NOT NULL,
                flow_type VARCHAR(30) NOT NULL
                    COMMENT 'DISTRIBUTION, WITHHOLDING_TAX, BROKER_INTEREST, MANUAL_ADJUSTMENT',
                amount DECIMAL(16, 2) NOT NULL
                    COMMENT 'Signed USD amount; positive/negative both allowed',
                flow_date DATE NOT NULL,
                description VARCHAR(255) NULL,
                source_system VARCHAR(30) NULL
                    COMMENT 'IBKR, MANUAL, etc',
                source_hash VARCHAR(64) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_asset_cash_flow_source (source_hash),
                INDEX idx_asset_cash_flow_asset_date
                    (user_asset_id, flow_date),
                INDEX idx_asset_cash_flow_type (flow_type),
                CONSTRAINT fk_asset_cash_flow_asset
                    FOREIGN KEY (user_asset_id)
                    REFERENCES user_assets(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bond_daily_prices (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_asset_id INT NOT NULL,
                price_date DATE NOT NULL,
                price_per_unit DECIMAL(16, 6) NOT NULL
                    COMMENT 'Quoted bond price, e.g. 97.670000',
                source_system VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
                note VARCHAR(255) NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_bond_asset_date (user_asset_id, price_date),
                INDEX idx_bond_price_asset_date (user_asset_id, price_date),
                CONSTRAINT fk_bond_price_asset
                    FOREIGN KEY (user_asset_id)
                    REFERENCES user_assets(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_daily_prices (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ticker_symbol VARCHAR(20) NOT NULL,
                trade_date DATE NOT NULL,
                open_price DECIMAL(16, 6) NULL,
                high_price DECIMAL(16, 6) NULL,
                low_price DECIMAL(16, 6) NULL,
                close_price DECIMAL(16, 6) NOT NULL,
                volume BIGINT NULL,
                currency VARCHAR(10) NOT NULL DEFAULT 'USD',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_ticker_date (ticker_symbol, trade_date),
                INDEX idx_sdp_ticker_trade (ticker_symbol, trade_date),
                INDEX idx_sdp_date (trade_date)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS price_update_log (
                ticker_symbol VARCHAR(20) NOT NULL PRIMARY KEY,
                last_updated_at DATETIME NOT NULL,
                last_price DECIMAL(16, 6) NULL
                    COMMENT 'Most recent price (regular/pre/post)',
                market_state VARCHAR(10) NULL
                    COMMENT 'PRE / REGULAR / POST / CLOSED'
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        # Migrate: add market_state column if table existed before this change
        try:
            cur.execute(
                """
                ALTER TABLE price_update_log
                ADD COLUMN market_state VARCHAR(10) NULL
                    COMMENT 'PRE / REGULAR / POST / CLOSED'
                """
            )
        except Exception:
            pass  # column already exists

        try:
            cur.execute(
                """
                ALTER TABLE user_assets
                ADD INDEX idx_user_assets_user_active_created
                    (user_id, is_active, created_at)
                """
            )
        except Exception:
            pass

        try:
            cur.execute(
                """
                ALTER TABLE user_assets
                ADD COLUMN include_price_pnl TINYINT(1) NOT NULL
                    DEFAULT 1
                    COMMENT '1=include price P&L in cards, 0=principal only'
                AFTER notes
                """
            )
        except Exception:
            pass

        try:
            cur.execute(
                """
                ALTER TABLE asset_transactions
                ADD INDEX idx_asset_tx_asset_date
                    (user_asset_id, transaction_date)
                """
            )
        except Exception:
            pass

        try:
            cur.execute(
                """
                ALTER TABLE asset_transactions
                ADD INDEX idx_asset_tx_asset_date_id
                    (user_asset_id, transaction_date, id)
                """
            )
        except Exception:
            pass

        try:
            cur.execute(
                """
                ALTER TABLE stock_daily_prices
                ADD INDEX idx_sdp_ticker_trade
                    (ticker_symbol, trade_date)
                """
            )
        except Exception:
            pass

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                from_currency VARCHAR(10) NOT NULL
                    COMMENT 'e.g. USD',
                to_currency VARCHAR(10) NOT NULL
                    COMMENT 'e.g. CNY',
                rate_date DATE NOT NULL,
                rate DECIMAL(12, 6) NOT NULL
                    COMMENT 'e.g. 7.2345',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_fx_pair_date
                    (from_currency, to_currency, rate_date),
                INDEX idx_er_date (rate_date)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_state (
                refresh_key VARCHAR(50) NOT NULL PRIMARY KEY,
                last_refreshed_at DATETIME NOT NULL,
                note VARCHAR(255) NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_asset_snapshots (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                snapshot_date DATE NOT NULL,
                total_value_cny DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                stock_value_cny DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                bond_value_cny DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                cash_value_cny DECIMAL(16, 2) NOT NULL DEFAULT 0.00,
                exchange_rate DECIMAL(12, 6) NULL
                    COMMENT 'USD/CNY rate used',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_user_snapshot_date
                    (user_id, snapshot_date),
                INDEX idx_das_user (user_id),
                CONSTRAINT fk_das_user
                    FOREIGN KEY (user_id) REFERENCES finance_users(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshot_rebuild_state (
                user_id INT NOT NULL PRIMARY KEY,
                status VARCHAR(20) NOT NULL DEFAULT 'IDLE'
                    COMMENT 'IDLE, QUEUED, RUNNING, SUCCEEDED, FAILED',
                refresh_from DATE NULL,
                pending_refresh_from DATE NULL,
                started_at DATETIME NULL,
                finished_at DATETIME NULL,
                last_completed_at DATETIME NULL,
                last_snapshot_date DATE NULL,
                rebuilt_days INT NOT NULL DEFAULT 0,
                message VARCHAR(255) NULL,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                CONSTRAINT fk_snapshot_rebuild_user
                    FOREIGN KEY (user_id) REFERENCES finance_users(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        try:
            cur.execute(
                """
                ALTER TABLE snapshot_rebuild_state
                ADD COLUMN pending_refresh_from DATE NULL
                    AFTER refresh_from
                """
            )
        except Exception:
            pass

        # Migrate: add net_flow_cny column if table existed before this change
        try:
            cur.execute(
                """
                ALTER TABLE daily_asset_snapshots
                ADD COLUMN net_flow_cny DECIMAL(16, 2) NOT NULL DEFAULT 0.00
                    COMMENT 'Net capital inflow on this date (BUY - SELL) in CNY'
                """
            )
        except Exception:
            pass  # column already exists

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_widget_templates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                widget_type VARCHAR(40) NOT NULL UNIQUE
                    COMMENT 'total_assets, trend_chart, etc',
                display_name VARCHAR(80) NOT NULL
                    COMMENT 'User-facing Chinese name',
                description VARCHAR(255) NULL,
                default_config JSON NULL
                    COMMENT 'Default parameters',
                min_width INT NOT NULL DEFAULT 1
                    COMMENT 'Grid columns minimum (1-2)',
                min_height INT NOT NULL DEFAULT 1
                    COMMENT 'Grid rows minimum',
                component_template VARCHAR(120) NOT NULL
                    COMMENT 'Jinja2 template path',
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                display_order INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_dashboard_layouts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                widget_template_id INT NOT NULL,
                sort_order INT NOT NULL DEFAULT 0
                    COMMENT 'Lower = higher on page',
                width INT NOT NULL DEFAULT 2
                    COMMENT 'Grid column span',
                custom_config JSON NULL
                    COMMENT 'Per-user config overrides',
                is_visible TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_udl_user (user_id),
                CONSTRAINT fk_udl_user
                    FOREIGN KEY (user_id) REFERENCES finance_users(id)
                    ON DELETE CASCADE,
                CONSTRAINT fk_udl_template
                    FOREIGN KEY (widget_template_id)
                    REFERENCES dashboard_widget_templates(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ibkr_flex_configs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                flex_query_id VARCHAR(64) NOT NULL
                    COMMENT 'IBKR Flex Query ID',
                flex_token VARCHAR(255) NOT NULL
                    COMMENT 'IBKR Flex Web Service token',
                token_expires_at DATE NULL
                    COMMENT 'IBKR token expiry date',
                query_name VARCHAR(120) NULL
                    COMMENT 'Optional user-facing query name',
                is_enabled TINYINT(1) NOT NULL DEFAULT 1,
                last_synced_at DATETIME NULL,
                last_imported_to DATE NULL
                    COMMENT 'Latest statement end date imported',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL
                    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_ibkr_flex_user (user_id),
                INDEX idx_ibkr_flex_enabled (is_enabled),
                CONSTRAINT fk_ibkr_flex_user
                    FOREIGN KEY (user_id) REFERENCES finance_users(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )

        try:
            cur.execute(
                """
                ALTER TABLE ibkr_flex_configs
                ADD COLUMN token_expires_at DATE NULL
                    COMMENT 'IBKR token expiry date'
                AFTER flex_token
                """
            )
        except Exception:
            pass

        cur.execute(
            """
            UPDATE ibkr_flex_configs
            SET token_expires_at = DATE_ADD(CURDATE(), INTERVAL 365 DAY)
            WHERE token_expires_at IS NULL
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ibkr_flex_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                event_kind VARCHAR(20) NOT NULL
                    COMMENT 'TRADE or CASH',
                normalized_type VARCHAR(30) NOT NULL
                    COMMENT 'BUY, SELL, DISTRIBUTION, WITHHOLDING_TAX, DEPOSIT, WITHDRAWAL, BROKER_INTEREST, IGNORED',
                symbol VARCHAR(40) NULL,
                description VARCHAR(255) NULL,
                event_at DATETIME NOT NULL,
                currency VARCHAR(10) NOT NULL,
                quantity DECIMAL(16, 6) NULL,
                price_per_unit DECIMAL(16, 6) NULL,
                amount DECIMAL(16, 2) NULL,
                commission DECIMAL(16, 6) NULL,
                raw_type VARCHAR(80) NULL
                    COMMENT 'Original IBKR type, e.g. Dividends',
                raw_payload JSON NULL,
                source_hash VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_ibkr_event_source (source_hash),
                INDEX idx_ibkr_event_user_time (user_id, event_at),
                INDEX idx_ibkr_event_type (normalized_type),
                CONSTRAINT fk_ibkr_event_user
                    FOREIGN KEY (user_id) REFERENCES finance_users(id)
                    ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """
        )


def seed_asset_types() -> None:
    """Insert default asset types if not present."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM asset_types")
        if cur.fetchone()["cnt"] == 0:
            cur.execute(
                """
                INSERT INTO asset_types
                    (type_code, type_name, currency,
                     has_market_price, needs_ticker, display_order)
                VALUES
                    ('STOCK', '股票', 'USD', 1, 1, 1),
                    ('BOND',  '债券', 'USD', 0, 0, 2),
                    ('CASH',  '现金', 'USD', 0, 0, 3)
                """
            )


def seed_widget_templates() -> None:
    """Insert or update default widget templates."""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO dashboard_widget_templates
                (widget_type, display_name, description,
                 default_config, min_width, min_height,
                 component_template, display_order)
            VALUES
                ('total_assets', '资产总值',
                 '复用资产页的总资产卡片',
                 '{"currency": "CNY"}', 1, 1,
                 'widgets/performance_metric.html', 1),
                ('daily_pnl', '今日变化',
                 '复用资产页的今日变化卡片',
                 '{"compare": "yesterday"}', 1, 1,
                 'widgets/performance_metric.html', 2),
                ('total_pnl', '总盈亏',
                 '复用资产页的总盈亏卡片',
                 '{}', 1, 1,
                 'widgets/performance_metric.html', 3),
                ('realized_pnl', '已实现盈亏',
                 '复用资产页的已实现盈亏卡片',
                 '{}', 1, 1,
                 'widgets/performance_metric.html', 4),
                ('unrealized_pnl', '未实现盈亏',
                 '复用资产页的未实现盈亏卡片',
                 '{}', 1, 1,
                 'widgets/performance_metric.html', 5),
                ('income_pnl', '累计分红/利息',
                 '复用资产页的累计分红利息卡片',
                 '{}', 1, 1,
                 'widgets/performance_metric.html', 6),
                ('trend_chart', '资产变化趋势',
                 '近期资产变化折线图',
                 '{"days": 30}', 2, 2,
                 'widgets/trend_chart.html', 7),
                ('allocation_pie', '资产配置',
                 '按类别的资产占比饼图',
                 '{}', 1, 2,
                 'widgets/allocation_pie.html', 8),
                ('exchange_rate', '汇率',
                 '当前 USD/CNY 汇率',
                 '{"pair": "USD/CNY"}', 1, 1,
                 'widgets/exchange_rate.html', 9),
                ('asset_list', '资产明细',
                 '持仓资产列表摘要',
                 '{"limit": 10}', 2, 2,
                 'widgets/asset_list.html', 10)
            ON DUPLICATE KEY UPDATE
                display_name = VALUES(display_name),
                description = VALUES(description),
                default_config = VALUES(default_config),
                min_width = VALUES(min_width),
                min_height = VALUES(min_height),
                component_template = VALUES(component_template),
                display_order = VALUES(display_order),
                is_active = 1
            """
        )


def touch_last_login(user_id: int) -> None:
    """Update user's last_login_at timestamp."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE finance_users SET last_login_at=%s WHERE id=%s",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id),
        )
