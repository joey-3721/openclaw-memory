"""Asset service — CRUD, position calculation, value computation."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Optional

from ..db import get_cursor
from .exchange_rate_service import ExchangeRateService
from .market_data_service import MarketDataService

logger = logging.getLogger(__name__)


class AssetService:
    """Core asset management: create, trade, value, list."""

    BOND_PAR_PRICE = Decimal("100")

    def __init__(self) -> None:
        self._market = MarketDataService()
        self._fx = ExchangeRateService()

    # ── Asset CRUD ────────────────────────────────────────

    def create_asset(self, user_id: int, data: dict) -> int:
        """Create a user_asset + initial BUY transaction.

        data keys: asset_type_code, ticker_symbol, asset_name,
                   quantity, price_per_unit, buy_date, note
        Returns the new asset id.
        """
        asset_type = self._get_asset_type_by_code(
            data["asset_type_code"]
        )
        if not asset_type:
            raise ValueError(
                f"Unknown asset type: {data['asset_type_code']}"
            )

        ticker = (data.get("ticker_symbol") or "").upper() or None
        quantity = Decimal(str(data["quantity"]))
        price_per_unit = (
            Decimal(str(data["price_per_unit"]))
            if data.get("price_per_unit")
            else None
        )
        buy_date = data.get("buy_date") or date.today()
        if isinstance(buy_date, str):
            buy_date = date.fromisoformat(buy_date)

        total_amount = self._calculate_transaction_total_amount(
            asset_type["type_code"], quantity, price_per_unit
        )

        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_assets
                    (user_id, asset_type_id, ticker_symbol,
                     asset_name, currency)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    asset_type["id"],
                    ticker,
                    data["asset_name"],
                    asset_type.get("currency", "USD"),
                ),
            )
            asset_id = cur.lastrowid

            cur.execute(
                """
                INSERT INTO asset_transactions
                    (user_asset_id, direction, quantity,
                     price_per_unit, total_amount, fee,
                     transaction_date, source_system, note)
                VALUES (%s, 'BUY', %s, %s, %s, %s, %s, 'MANUAL', %s)
                """,
                (
                    asset_id,
                    str(quantity),
                    str(price_per_unit) if price_per_unit else None,
                    str(total_amount),
                    str(data.get("fee", "0")),
                    buy_date,
                    data.get("note"),
                ),
            )

        self._sync_supporting_data_from_date(
            asset_type, ticker, buy_date
        )

        return asset_id

    def add_transaction(self, asset_id: int, data: dict) -> int:
        """Record a BUY or SELL transaction. Returns transaction id."""
        direction = data["direction"].upper()
        if direction not in ("BUY", "SELL"):
            raise ValueError("direction must be BUY or SELL")

        quantity = Decimal(str(data["quantity"]))
        price_per_unit = (
            Decimal(str(data["price_per_unit"]))
            if data.get("price_per_unit")
            else None
        )
        asset = self._get_asset_for_sync(asset_id)
        if not asset:
            raise ValueError("asset not found")
        tx_date = data.get("transaction_date") or date.today()
        if isinstance(tx_date, str):
            tx_date = date.fromisoformat(tx_date)

        total_amount = self._calculate_transaction_total_amount(
            asset["type_code"], quantity, price_per_unit
        )

        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_transactions
                    (user_asset_id, direction, quantity,
                     price_per_unit, total_amount, fee,
                     transaction_date, source_system, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'MANUAL', %s)
                """,
                (
                    asset_id,
                    direction,
                    str(quantity),
                    str(price_per_unit) if price_per_unit else None,
                    str(total_amount),
                    str(data.get("fee", "0")),
                    tx_date,
                    data.get("note"),
                ),
            )
            tx_id = cur.lastrowid

        if asset:
            self._sync_supporting_data_from_date(
                asset, asset.get("ticker_symbol"), tx_date
            )

        return tx_id

    def deactivate_asset(self, asset_id: int) -> None:
        """Soft-delete an asset."""
        with get_cursor() as cur:
            cur.execute(
                "UPDATE user_assets SET is_active=0 WHERE id=%s",
                (asset_id,),
            )

    # ── Query ─────────────────────────────────────────────

    def get_user_assets(self, user_id: int) -> list[dict]:
        """Return all active assets for a user."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT ua.id, ua.ticker_symbol, ua.asset_name,
                       ua.currency, ua.created_at,
                       ua.include_price_pnl,
                       at2.type_code, at2.type_name,
                       at2.has_market_price
                FROM user_assets ua
                JOIN asset_types at2 ON ua.asset_type_id = at2.id
                WHERE ua.user_id = %s AND ua.is_active = 1
                ORDER BY ua.id DESC
                """,
                (user_id,),
            )
            return cur.fetchall()

    def get_user_assets_with_values(
        self, user_id: int
    ) -> list[dict]:
        """Return all active assets with current CNY & USD values."""
        started_at = perf_counter()
        assets = self.get_user_assets(user_id)
        if not assets:
            print(
                "PERF asset values",
                {
                    "user_id": user_id,
                    "asset_count": 0,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000, 1
                    ),
                },
                flush=True,
            )
            return []

        asset_ids = [asset["id"] for asset in assets]
        tickers = [
            asset["ticker_symbol"].upper()
            for asset in assets
            if asset["has_market_price"] and asset["ticker_symbol"]
        ]
        today = date.today()
        yesterday = today - timedelta(days=1)
        fx_rates = self._get_rate_pair(today, yesterday)
        rate = fx_rates.get(today, Decimal("0"))
        prev_rate = fx_rates.get(yesterday, Decimal("0"))
        rate_float = float(rate) if rate else 0.0
        tx_summary = self._get_dashboard_transaction_summary(
            asset_ids, today, yesterday
        )
        positions = tx_summary["positions"]
        cost_basis_map = tx_summary["cost_basis"]
        latest_bond_price_map = self._get_bond_price_map(
            asset_ids, today
        )
        prev_bond_price_map = self._get_bond_price_map(
            asset_ids, yesterday
        )
        performance_map = self._get_asset_performance_map(asset_ids)
        stock_prices = self._get_dashboard_stock_price_maps(
            tickers, today, yesterday
        )
        stock_close_today = stock_prices["today"]
        stock_close_yesterday = stock_prices["yesterday"]
        latest_price_info_map = self._get_latest_price_info_map(
            tickers, stock_close_today, stock_close_yesterday
        )

        result = []
        for asset in assets:
            asset_id = asset["id"]
            ticker = (
                asset["ticker_symbol"].upper()
                if asset["ticker_symbol"]
                else None
            )
            position_info = positions.get(asset_id, {})
            position = position_info.get("today", Decimal("0"))
            prev_position = position_info.get(
                "yesterday", Decimal("0")
            )

            latest_price = None
            price_updated_at = None
            market_state_label = None
            price_change_pct = 0.0
            ref_price = None
            ref_label = None

            if asset["type_code"] == "STOCK" and ticker:
                close_today = stock_close_today.get(ticker)
                close_yesterday = stock_close_yesterday.get(ticker)
                price_info = latest_price_info_map.get(ticker)
                current_price_for_value = None
                prev_price_for_value = None
                if price_info:
                    current_price_for_value = Decimal(
                        str(price_info["price"])
                    )
                    if price_info.get("ref_price") is not None:
                        prev_price_for_value = Decimal(
                            str(price_info["ref_price"])
                        )
                if current_price_for_value is None:
                    current_price_for_value = (
                        close_today or close_yesterday
                    )
                if prev_price_for_value is None:
                    prev_price_for_value = (
                        close_yesterday or close_today
                    )
                value_usd = (
                    position * current_price_for_value
                    if current_price_for_value is not None
                    else Decimal("0")
                )
                prev_value_usd = (
                    prev_position * prev_price_for_value
                    if prev_price_for_value is not None
                    else value_usd
                )
                if price_info:
                    latest_price = price_info["price"]
                    price_updated_at = price_info.get("updated_at")
                    market_state_label = price_info.get(
                        "market_state_label"
                    )
                    price_change_pct = price_info.get(
                        "change_pct", 0.0
                    )
                    ref_price = price_info.get("ref_price")
                    ref_label = price_info.get("ref_label")
            elif asset["type_code"] == "BOND":
                value_usd = position
                prev_value_usd = prev_position
                latest_price = None
            else:
                value_usd = position
                prev_value_usd = prev_position
                latest_price = (
                    float(position)
                    if asset["type_code"] == "CASH"
                    else None
                )

            value_cny = (
                value_usd * rate
                if rate and value_usd
                else Decimal("0")
            )
            prev_value_cny = (
                prev_value_usd * prev_rate
                if prev_rate and prev_value_usd
                else Decimal("0")
            )

            change_cny = value_cny - prev_value_cny
            change_pct = (
                float(change_cny / prev_value_cny * 100)
                if prev_value_cny
                else 0.0
            )

            # Total P&L: current value vs cost basis
            performance = performance_map.get(
                asset_id, self._empty_performance_summary()
            )
            include_price_pnl = bool(
                asset.get("include_price_pnl", 1)
            )
            if asset["type_code"] == "BOND":
                current_cost_basis = position
            else:
                current_cost_basis = Decimal(
                    str(performance["current_cost_basis_usd"])
                )
            avg_cost = (
                current_cost_basis / position
                if position > 0
                else None
            )
            current_usd = value_usd if value_usd else Decimal("0")
            unrealized_pnl_usd = float(
                current_usd - current_cost_basis
            )
            realized_pnl_usd = performance["realized_pnl_usd"]
            income_pnl_usd = performance["distribution_net_usd"]
            total_pnl_usd = (
                unrealized_pnl_usd
                + realized_pnl_usd
                + income_pnl_usd
            )
            unrealized_pnl_pct = (
                round(
                    float(
                        (current_usd - current_cost_basis)
                        / current_cost_basis
                        * 100
                    ),
                    2,
                )
                if current_cost_basis > 0
                else 0.0
            )

            result.append(
                {
                    "id": asset["id"],
                    "type_code": asset["type_code"],
                    "type_name": asset["type_name"],
                    "ticker_symbol": asset["ticker_symbol"],
                    "asset_name": asset["asset_name"],
                    "currency": asset["currency"],
                    "include_price_pnl": include_price_pnl,
                    "position": float(position),
                    "value_usd": float(value_usd) if value_usd else 0,
                    "value_cny": float(value_cny),
                    "latest_price_usd": latest_price,
                    "price_updated_at": price_updated_at,
                    "market_state_label": market_state_label,
                    "price_change_pct": price_change_pct,
                    "ref_price": ref_price,
                    "ref_label": ref_label,
                    "change_cny": float(change_cny),
                    "change_pct": round(change_pct, 2),
                    "has_market_price": asset["has_market_price"],
                    "cost_basis_usd": float(current_cost_basis),
                    "avg_cost_usd": (
                        float(avg_cost)
                        if avg_cost is not None
                        else None
                    ),
                    "unrealized_pnl_usd": unrealized_pnl_usd,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "realized_pnl_usd": realized_pnl_usd,
                    "distribution_gross_usd": performance["distribution_gross_usd"],
                    "interest_income_usd": performance["interest_income_usd"],
                    "withholding_tax_usd": performance["withholding_tax_usd"],
                    "distribution_net_usd": income_pnl_usd,
                    "total_pnl_usd": total_pnl_usd,
                    "realized_pnl_cny": realized_pnl_usd * rate_float,
                    "unrealized_pnl_cny": unrealized_pnl_usd * rate_float,
                    "income_pnl_cny": income_pnl_usd * rate_float,
                    "total_pnl_cny": total_pnl_usd * rate_float,
                }
            )
        print(
            "PERF asset values",
            {
                "user_id": user_id,
                "asset_count": len(assets),
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000, 1
                ),
            },
            flush=True,
        )
        result.sort(
            key=lambda item: item.get("value_cny", 0.0),
            reverse=True,
        )
        return result

    def get_dashboard_assets(
        self, user_id: int, limit: int = 10
    ) -> list[dict]:
        """Return a lightweight asset list for the dashboard widget."""
        started_at = perf_counter()
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT ua.id, ua.ticker_symbol, ua.asset_name,
                       ua.currency, ua.include_price_pnl,
                       at2.type_code, at2.type_name,
                       at2.has_market_price
                FROM user_assets ua
                JOIN asset_types at2 ON ua.asset_type_id = at2.id
                WHERE ua.user_id = %s AND ua.is_active = 1
                ORDER BY ua.id DESC
                """,
                (user_id,),
            )
            assets = cur.fetchall()

        if not assets:
            return []

        asset_ids = [asset["id"] for asset in assets]
        tickers = [
            asset["ticker_symbol"].upper()
            for asset in assets
            if asset["has_market_price"] and asset["ticker_symbol"]
        ]
        today = date.today()
        yesterday = today - timedelta(days=1)
        fx_rates = self._get_rate_pair(today, yesterday)
        today_rate = fx_rates.get(today, Decimal("0"))
        prev_rate = fx_rates.get(yesterday, Decimal("0"))
        today_rate_float = float(today_rate) if today_rate else 0.0

        tx_summary = self._get_dashboard_transaction_summary(
            asset_ids, today, yesterday
        )
        positions = tx_summary["positions"]
        cost_basis_map = tx_summary["cost_basis"]
        stock_prices = self._get_dashboard_stock_price_maps(
            tickers, today, yesterday
        )
        stock_close_today = stock_prices["today"]
        stock_close_yesterday = stock_prices["yesterday"]
        realtime_price_map = self._get_realtime_price_map(tickers)

        result = []
        for asset in assets:
            asset_id = asset["id"]
            ticker = (
                asset["ticker_symbol"].upper()
                if asset["ticker_symbol"]
                else None
            )
            position_info = positions.get(asset_id, {})
            position_today = position_info.get("today", Decimal("0"))
            position_yesterday = position_info.get(
                "yesterday", Decimal("0")
            )

            latest_price_usd = None
            price_change_pct = 0.0
            if asset["type_code"] == "STOCK" and ticker:
                close_today = stock_close_today.get(ticker)
                close_yesterday = stock_close_yesterday.get(ticker)
                realtime_price = realtime_price_map.get(ticker)
                latest_price_usd = (
                    realtime_price
                    or close_today
                    or close_yesterday
                )
                if (
                    latest_price_usd is not None
                    and close_yesterday is not None
                    and close_yesterday > 0
                ):
                    price_change_pct = round(
                        float(
                            (latest_price_usd - close_yesterday)
                            / close_yesterday
                            * 100
                        ),
                        2,
                    )
                current_price_for_value = (
                    realtime_price
                    or close_today
                    or close_yesterday
                )
                prev_price_for_value = (
                    close_yesterday
                    or close_today
                )
                value_usd = (
                    position_today * current_price_for_value
                    if current_price_for_value is not None
                    else Decimal("0")
                )
                prev_value_usd = (
                    position_yesterday * prev_price_for_value
                    if prev_price_for_value is not None
                    else value_usd
                )
            elif asset["type_code"] == "BOND":
                latest_price_usd = None
                value_usd = position_today
                prev_value_usd = position_yesterday
            else:
                latest_price_usd = (
                    float(position_today)
                    if asset["type_code"] == "CASH"
                    else None
                )
                value_usd = position_today
                prev_value_usd = position_yesterday

            value_cny = value_usd * today_rate if today_rate else Decimal("0")
            prev_value_cny = (
                prev_value_usd * prev_rate if prev_rate else Decimal("0")
            )
            change_cny = value_cny - prev_value_cny
            change_pct = (
                round(float(change_cny / prev_value_cny * 100), 2)
                if prev_value_cny
                else 0.0
            )
            cost_basis_usd = cost_basis_map.get(asset_id, Decimal("0"))
            unrealized_pnl_usd = float(value_usd - cost_basis_usd)
            realized_pnl_usd = 0.0
            income_pnl_usd = 0.0
            total_pnl_usd = unrealized_pnl_usd + realized_pnl_usd + income_pnl_usd
            total_pnl_cny = total_pnl_usd * today_rate_float

            result.append(
                {
                    "id": asset_id,
                    "type_code": asset["type_code"],
                    "type_name": asset["type_name"],
                    "ticker_symbol": asset["ticker_symbol"],
                    "asset_name": asset["asset_name"],
                    "currency": asset["currency"],
                    "position": float(position_today),
                    "value_cny": float(value_cny),
                    "latest_price_usd": (
                        float(latest_price_usd)
                        if latest_price_usd is not None
                        else None
                    ),
                    "price_change_pct": price_change_pct,
                    "change_cny": float(change_cny),
                    "change_pct": change_pct,
                    "has_market_price": asset["has_market_price"],
                    "cost_basis_usd": float(cost_basis_usd),
                    "unrealized_pnl_usd": unrealized_pnl_usd,
                    "realized_pnl_usd": realized_pnl_usd,
                    "distribution_net_usd": income_pnl_usd,
                    "total_pnl_usd": total_pnl_usd,
                    "unrealized_pnl_cny": unrealized_pnl_usd * today_rate_float,
                    "realized_pnl_cny": 0.0,
                    "income_pnl_cny": 0.0,
                    "total_pnl_cny": total_pnl_cny,
                }
            )

        print(
            "PERF dashboard asset list",
            {
                "user_id": user_id,
                "asset_count": len(assets),
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000, 1
                ),
            },
            flush=True,
        )
        result.sort(
            key=lambda item: item.get("value_cny", 0.0),
            reverse=True,
        )
        return result[:limit]

    def get_asset_detail(self, asset_id: int) -> dict | None:
        """Single asset with transaction history."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT ua.id, ua.user_id, ua.ticker_symbol,
                       ua.asset_name, ua.currency, ua.notes,
                       ua.include_price_pnl,
                       ua.created_at,
                       at2.type_code, at2.type_name,
                       at2.has_market_price
                FROM user_assets ua
                JOIN asset_types at2 ON ua.asset_type_id = at2.id
                WHERE ua.id = %s
                """,
                (asset_id,),
            )
            asset = cur.fetchone()

        if not asset:
            return None

        transactions = self.get_transactions(asset_id)
        today = date.today()
        position = self.calculate_position_for_asset(asset_id, today)
        rate = self._fx.get_rate_for_date(today)
        value_usd = self._compute_usd_value(asset, position, today)
        value_cny = (
            value_usd * rate
            if rate and value_usd
            else Decimal("0")
        )

        return {
            **asset,
            "position": float(position),
            "value_usd": float(value_usd) if value_usd else 0,
            "value_cny": float(value_cny),
            "exchange_rate": float(rate) if rate else None,
            "transactions": transactions,
        }

    def get_transactions(self, asset_id: int) -> list[dict]:
        """Get all transactions for an asset."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, direction, quantity, price_per_unit,
                       total_amount, fee, transaction_date,
                       CASE
                           WHEN note = 'IBKR 自动导入'
                           THEN 'IBKR'
                           ELSE source_system
                       END AS source_system,
                       note,
                       created_at
                FROM asset_transactions
                WHERE user_asset_id = %s
                ORDER BY transaction_date DESC, id DESC
                """,
                (asset_id,),
            )
            rows = cur.fetchall()

        for row in rows:
            for key in (
                "quantity",
                "price_per_unit",
                "total_amount",
                "fee",
            ):
                if row[key] is not None:
                    row[key] = float(row[key])
            if row["transaction_date"]:
                row["transaction_date"] = row[
                    "transaction_date"
                ].isoformat()
            # json serializable: JSONResponse can't encode datetime objects
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
        return rows

    def get_cash_flows(self, asset_id: int) -> list[dict]:
        """Get imported/manual cash flow records for an asset."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, flow_type, amount, flow_date,
                       description, source_system, created_at
                FROM asset_cash_flows
                WHERE user_asset_id = %s
                ORDER BY flow_date DESC, id DESC
                """,
                (asset_id,),
            )
            rows = cur.fetchall()

        for row in rows:
            row["amount"] = float(row["amount"])
            if row["flow_date"]:
                row["flow_date"] = row["flow_date"].isoformat()
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
        return rows

    def save_bond_price(
        self,
        asset_id: int,
        price_per_unit: Decimal,
        price_date: date | None = None,
    ) -> date:
        """Save a manual bond price and backfill missing dates with the same value."""
        asset = self.get_asset_detail(asset_id)
        if not asset:
            raise ValueError("资产不存在")
        if asset["type_code"] != "BOND":
            raise ValueError("仅债券资产支持录入价格")

        price_date = price_date or date.today()
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(price_date) AS last_price_date
                FROM bond_daily_prices
                WHERE user_asset_id = %s
                  AND price_date <= %s
                """,
                (asset_id, price_date),
            )
            row = cur.fetchone()

            last_price_date = row["last_price_date"] if row else None
            backfill_from = (
                last_price_date + timedelta(days=1)
                if last_price_date and last_price_date < price_date
                else price_date
            )

            current = backfill_from
            while current <= price_date:
                if current == price_date:
                    cur.execute(
                        """
                        INSERT INTO bond_daily_prices
                            (user_asset_id, price_date, price_per_unit,
                             source_system, note)
                        VALUES (%s, %s, %s, 'MANUAL', %s)
                        ON DUPLICATE KEY UPDATE
                            price_per_unit = VALUES(price_per_unit),
                            source_system = VALUES(source_system),
                            note = VALUES(note)
                        """,
                        (
                            asset_id,
                            current,
                            str(price_per_unit),
                            "手动录入债券价格",
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT IGNORE INTO bond_daily_prices
                            (user_asset_id, price_date, price_per_unit,
                             source_system, note)
                        VALUES (%s, %s, %s, 'MANUAL', %s)
                        """,
                        (
                            asset_id,
                            current,
                            str(price_per_unit),
                            "沿用最近一次手动债券价格",
                        ),
                    )
                current += timedelta(days=1)

        return backfill_from

    def save_manual_interest(
        self,
        asset_id: int,
        amount: Decimal,
        flow_date: date | None = None,
        note: str | None = None,
    ) -> date:
        """Save a manual interest record for bond or cash assets."""
        asset = self.get_asset_detail(asset_id)
        if not asset:
            raise ValueError("资产不存在")
        if asset["type_code"] not in {"BOND", "CASH"}:
            raise ValueError("仅债券或现金资产支持录入利息")

        flow_date = flow_date or date.today()
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_cash_flows
                    (user_asset_id, flow_type, amount, flow_date,
                     description, source_system)
                VALUES (%s, 'INTEREST', %s, %s, %s, 'MANUAL')
                """,
                (
                    asset_id,
                    str(amount),
                    flow_date,
                    note or "手动录入利息",
                ),
            )
        return flow_date

    def set_include_price_pnl(
        self, asset_id: int, enabled: bool
    ) -> None:
        """Toggle whether an asset contributes price P&L to summary cards."""
        asset = self.get_asset_detail(asset_id)
        if not asset:
            raise ValueError("资产不存在")
        if asset["type_code"] != "BOND":
            raise ValueError("仅债券资产支持该开关")

        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE user_assets
                SET include_price_pnl = %s
                WHERE id = %s
                """,
                (1 if enabled else 0, asset_id),
            )

    def get_asset_first_activity_date(
        self, asset_id: int
    ) -> date | None:
        """Return the earliest date that can affect this asset's value."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT MIN(first_date) AS first_activity_date
                FROM (
                    SELECT MIN(transaction_date) AS first_date
                    FROM asset_transactions
                    WHERE user_asset_id = %s
                    UNION ALL
                    SELECT MIN(flow_date) AS first_date
                    FROM asset_cash_flows
                    WHERE user_asset_id = %s
                    UNION ALL
                    SELECT MIN(price_date) AS first_date
                    FROM bond_daily_prices
                    WHERE user_asset_id = %s
                ) activity_dates
                """,
                (asset_id, asset_id, asset_id),
            )
            row = cur.fetchone()
        return row["first_activity_date"] if row else None

    def _empty_performance_summary(self) -> dict:
        return {
            "current_cost_basis_usd": 0.0,
            "realized_pnl_usd": 0.0,
            "distribution_gross_usd": 0.0,
            "interest_income_usd": 0.0,
            "withholding_tax_usd": 0.0,
            "distribution_net_usd": 0.0,
        }

    def _get_asset_performance_map(
        self, asset_ids: list[int]
    ) -> dict[int, dict]:
        """Compute realized P&L and dividend totals per asset."""
        if not asset_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(asset_ids))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT ua.id, at2.type_code, ua.include_price_pnl
                FROM user_assets ua
                JOIN asset_types at2 ON at2.id = ua.asset_type_id
                WHERE ua.id IN ({placeholders})
                """,
                asset_ids,
            )
            asset_meta_rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT user_asset_id, id, transaction_date,
                       direction, quantity, total_amount, fee
                FROM asset_transactions
                WHERE user_asset_id IN ({placeholders})
                ORDER BY transaction_date, id
                """,
                asset_ids,
            )
            tx_rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT user_asset_id, id, flow_date,
                       flow_type, amount
                FROM asset_cash_flows
                WHERE user_asset_id IN ({placeholders})
                ORDER BY flow_date, id
                """,
                asset_ids,
            )
            flow_rows = cur.fetchall()

        asset_meta = {
            row["id"]: {
                "type_code": row["type_code"],
                "include_price_pnl": bool(
                    row.get("include_price_pnl", 1)
                ),
            }
            for row in asset_meta_rows
        }
        events_by_asset: dict[int, list[dict]] = {
            asset_id: [] for asset_id in asset_ids
        }
        for row in tx_rows:
            events_by_asset[row["user_asset_id"]].append(
                {
                    "kind": "tx",
                    "event_date": row["transaction_date"],
                    "event_id": row["id"],
                    "payload": row,
                }
            )
        for row in flow_rows:
            events_by_asset[row["user_asset_id"]].append(
                {
                    "kind": "flow",
                    "event_date": row["flow_date"],
                    "event_id": row["id"],
                    "payload": row,
                }
            )

        result = {}
        for asset_id, events in events_by_asset.items():
            asset_info = asset_meta.get(asset_id, {})
            quantity = Decimal("0")
            cost_basis = Decimal("0")
            realized_pnl = Decimal("0")
            gross_dividends = Decimal("0")
            withholding_tax = Decimal("0")
            interest_income = Decimal("0")

            events.sort(
                key=lambda item: (item["event_date"], item["event_id"])
            )

            for event in events:
                payload = event["payload"]
                if event["kind"] == "tx":
                    tx_qty = Decimal(str(payload["quantity"]))
                    gross_amount = Decimal(
                        str(payload["total_amount"])
                    )
                    fee = Decimal(str(payload.get("fee") or 0))
                    if payload["direction"] == "BUY":
                        quantity += tx_qty
                        cost_basis += gross_amount + fee
                    else:
                        avg_cost = (
                            cost_basis / quantity if quantity > 0 else Decimal("0")
                        )
                        if asset_info.get("type_code") != "BOND":
                            realized_pnl += (
                                gross_amount
                                - fee
                                - avg_cost * tx_qty
                            )
                        quantity -= tx_qty
                        cost_basis -= avg_cost * tx_qty
                else:
                    amount = Decimal(str(payload["amount"]))
                    if payload["flow_type"] == "DISTRIBUTION":
                        gross_dividends += amount
                        cost_basis -= amount
                    elif payload["flow_type"] in {
                        "INTEREST",
                        "BROKER_INTEREST",
                    }:
                        gross_dividends += amount
                        interest_income += amount
                    elif payload["flow_type"] == "WITHHOLDING_TAX":
                        withholding_tax += amount
                        cost_basis -= amount

            result[asset_id] = {
                "current_cost_basis_usd": round(
                    float(cost_basis), 2
                ),
                "realized_pnl_usd": round(float(realized_pnl), 2),
                "distribution_gross_usd": round(
                    float(gross_dividends), 2
                ),
                "interest_income_usd": round(float(interest_income), 2),
                "withholding_tax_usd": round(
                    float(withholding_tax), 2
                ),
                "distribution_net_usd": round(
                    float(gross_dividends + withholding_tax), 2
                ),
            }

        return result

    # ── Position Calculation ──────────────────────────────

    def calculate_position_for_asset(
        self, asset_id: int, as_of_date: date
    ) -> Decimal:
        """Sum BUY quantities minus SELL quantities up to as_of_date."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT direction,
                       COALESCE(SUM(quantity), 0) AS total_qty
                FROM asset_transactions
                WHERE user_asset_id = %s
                  AND transaction_date <= %s
                GROUP BY direction
                """,
                (asset_id, as_of_date),
            )
            rows = cur.fetchall()

        buy_qty = Decimal("0")
        sell_qty = Decimal("0")
        for row in rows:
            if row["direction"] == "BUY":
                buy_qty = Decimal(str(row["total_qty"]))
            elif row["direction"] == "SELL":
                sell_qty = Decimal(str(row["total_qty"]))
        return buy_qty - sell_qty

    def _get_positions_for_dates(
        self, asset_ids: list[int], today: date, yesterday: date
    ) -> dict[int, dict[str, Decimal]]:
        """Fetch current and previous-day positions in one batch query."""
        if not asset_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(asset_ids))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT user_asset_id,
                       COALESCE(SUM(
                           CASE
                               WHEN transaction_date <= %s
                               THEN CASE
                                   WHEN direction = 'BUY' THEN quantity
                                   ELSE -quantity
                               END
                               ELSE 0
                           END
                       ), 0) AS pos_today,
                       COALESCE(SUM(
                           CASE
                               WHEN transaction_date <= %s
                               THEN CASE
                                   WHEN direction = 'BUY' THEN quantity
                                   ELSE -quantity
                               END
                               ELSE 0
                           END
                       ), 0) AS pos_yesterday
                FROM asset_transactions
                WHERE user_asset_id IN ({placeholders})
                GROUP BY user_asset_id
                """,
                (today, yesterday, *asset_ids),
            )
            rows = cur.fetchall()

        return {
            row["user_asset_id"]: {
                "today": Decimal(str(row["pos_today"])),
                "yesterday": Decimal(str(row["pos_yesterday"])),
            }
            for row in rows
        }

    def _get_dashboard_transaction_summary(
        self, asset_ids: list[int], today: date, yesterday: date
    ) -> dict[str, dict[int, Decimal] | dict[int, dict[str, Decimal]]]:
        """Fetch positions, cost basis, and latest transaction prices together."""
        if not asset_ids:
            return {
                "positions": {},
                "cost_basis": {},
                "latest_price": {},
            }

        placeholders = ", ".join(["%s"] * len(asset_ids))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT t.user_asset_id,
                       COALESCE(SUM(
                           CASE
                               WHEN t.transaction_date <= %s
                               THEN CASE
                                   WHEN t.direction = 'BUY' THEN t.quantity
                                   ELSE -t.quantity
                               END
                               ELSE 0
                           END
                       ), 0) AS pos_today,
                       COALESCE(SUM(
                           CASE
                               WHEN t.transaction_date <= %s
                               THEN CASE
                                   WHEN t.direction = 'BUY' THEN t.quantity
                                   ELSE -t.quantity
                               END
                               ELSE 0
                           END
                       ), 0) AS pos_yesterday,
                       COALESCE(SUM(
                           CASE
                               WHEN t.direction = 'BUY' THEN t.total_amount
                               ELSE -t.total_amount
                           END
                       ), 0) AS cost_basis
                FROM asset_transactions t
                WHERE t.user_asset_id IN ({placeholders})
                GROUP BY t.user_asset_id
                """,
                (today, yesterday, *asset_ids),
            )
            summary_rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT user_asset_id,
                       COALESCE(SUM(amount), 0) AS cash_flow_adjustment
                FROM asset_cash_flows
                WHERE user_asset_id IN ({placeholders})
                GROUP BY user_asset_id
                """,
                asset_ids,
            )
            cash_flow_rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT t.user_asset_id, t.price_per_unit
                FROM asset_transactions t
                JOIN (
                    SELECT user_asset_id,
                           MAX(transaction_date) AS latest_date
                    FROM asset_transactions
                    WHERE user_asset_id IN ({placeholders})
                      AND price_per_unit IS NOT NULL
                    GROUP BY user_asset_id
                ) latest_date
                  ON latest_date.user_asset_id = t.user_asset_id
                 AND latest_date.latest_date = t.transaction_date
                JOIN (
                    SELECT user_asset_id, transaction_date, MAX(id) AS latest_id
                    FROM asset_transactions
                    WHERE user_asset_id IN ({placeholders})
                      AND price_per_unit IS NOT NULL
                    GROUP BY user_asset_id, transaction_date
                ) latest_id
                  ON latest_id.latest_id = t.id
                """,
                (*asset_ids, *asset_ids),
            )
            latest_price_rows = cur.fetchall()

        positions = {}
        cost_basis = {}
        cash_flow_adjustments = {
            row["user_asset_id"]: Decimal(
                str(row["cash_flow_adjustment"])
            )
            for row in cash_flow_rows
        }
        for row in summary_rows:
            asset_id = row["user_asset_id"]
            positions[asset_id] = {
                "today": Decimal(str(row["pos_today"])),
                "yesterday": Decimal(str(row["pos_yesterday"])),
            }
            cost_basis[asset_id] = Decimal(
                str(row["cost_basis"])
            ) - cash_flow_adjustments.get(asset_id, Decimal("0"))

        latest_price = {
            row["user_asset_id"]: Decimal(str(row["price_per_unit"]))
            for row in latest_price_rows
            if row["price_per_unit"] is not None
        }
        return {
            "positions": positions,
            "cost_basis": cost_basis,
            "latest_price": latest_price,
        }

    def _get_bond_price_map(
        self, asset_ids: list[int], target_date: date
    ) -> dict[int, Decimal]:
        """Fetch latest manual bond prices on or before target_date."""
        if not asset_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(asset_ids))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT p.user_asset_id, p.price_per_unit
                FROM bond_daily_prices p
                JOIN (
                    SELECT user_asset_id, MAX(price_date) AS latest_date
                    FROM bond_daily_prices
                    WHERE user_asset_id IN ({placeholders})
                      AND price_date <= %s
                    GROUP BY user_asset_id
                ) latest
                  ON latest.user_asset_id = p.user_asset_id
                 AND latest.latest_date = p.price_date
                """,
                (*asset_ids, target_date),
            )
            rows = cur.fetchall()

        return {
            row["user_asset_id"]: Decimal(str(row["price_per_unit"]))
            for row in rows
            if row["price_per_unit"] is not None
        }

    def calculate_cost_basis(self, asset_id: int) -> Decimal:
        """Net cost = total BUY amount - total SELL amount (USD)."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT direction,
                       COALESCE(SUM(total_amount), 0) AS total_amt
                FROM asset_transactions
                WHERE user_asset_id = %s
                GROUP BY direction
                """,
                (asset_id,),
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS cash_flow_adjustment
                FROM asset_cash_flows
                WHERE user_asset_id = %s
                """,
                (asset_id,),
            )
            cash_flow_row = cur.fetchone()

        buy_amt = Decimal("0")
        sell_amt = Decimal("0")
        for row in rows:
            if row["direction"] == "BUY":
                buy_amt = Decimal(str(row["total_amt"]))
            elif row["direction"] == "SELL":
                sell_amt = Decimal(str(row["total_amt"]))
        cash_flow_adjustment = Decimal(
            str(cash_flow_row["cash_flow_adjustment"] or 0)
        )
        return buy_amt - sell_amt - cash_flow_adjustment

    def _get_cost_basis_map(
        self, asset_ids: list[int]
    ) -> dict[int, Decimal]:
        """Fetch cost basis for multiple assets."""
        if not asset_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(asset_ids))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT user_asset_id,
                       COALESCE(SUM(
                           CASE
                               WHEN direction = 'BUY' THEN total_amount
                               ELSE -total_amount
                           END
                       ), 0) AS cost_basis
                FROM asset_transactions
                WHERE user_asset_id IN ({placeholders})
                GROUP BY user_asset_id
                """,
                asset_ids,
            )
            rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT user_asset_id,
                       COALESCE(SUM(amount), 0) AS cash_flow_adjustment
                FROM asset_cash_flows
                WHERE user_asset_id IN ({placeholders})
                GROUP BY user_asset_id
                """,
                asset_ids,
            )
            cash_flow_rows = cur.fetchall()

        cash_flow_adjustments = {
            row["user_asset_id"]: Decimal(
                str(row["cash_flow_adjustment"])
            )
            for row in cash_flow_rows
        }
        return {
            row["user_asset_id"]: Decimal(str(row["cost_basis"]))
            - cash_flow_adjustments.get(
                row["user_asset_id"], Decimal("0")
            )
            for row in rows
        }

    def calculate_avg_cost(self, asset_id: int) -> Decimal | None:
        """Average cost per unit = cost_basis / position."""
        cost = self.calculate_cost_basis(asset_id)
        position = self.calculate_position_for_asset(
            asset_id, date.today()
        )
        if position > 0 and cost > 0:
            return cost / position
        return None

    # ── Value Computation ─────────────────────────────────

    def _compute_usd_value(
        self,
        asset: dict,
        position: Decimal,
        value_date: date,
    ) -> Optional[Decimal]:
        """Compute USD value based on asset type."""
        if position <= 0:
            return Decimal("0")

        type_code = asset["type_code"]

        if type_code == "STOCK":
            price = self._market.get_close_price_for_date(
                asset["ticker_symbol"], value_date
            )
            if price:
                return position * price
            return None

        elif type_code == "BOND":
            return position

        elif type_code == "CASH":
            # For cash, quantity IS the USD amount
            return position

        return None

    def _get_last_transaction_price(
        self, asset_id: int
    ) -> Optional[Decimal]:
        """Get the most recent price_per_unit from transactions."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT price_per_unit
                FROM asset_transactions
                WHERE user_asset_id = %s
                  AND price_per_unit IS NOT NULL
                ORDER BY transaction_date DESC, id DESC
                LIMIT 1
                """,
                (asset_id,),
            )
            row = cur.fetchone()
        if row and row["price_per_unit"]:
            return Decimal(str(row["price_per_unit"]))
        return None

    def _get_latest_transaction_price_map(
        self, asset_ids: list[int]
    ) -> dict[int, Decimal]:
        """Fetch the latest transaction price_per_unit for each asset."""
        if not asset_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(asset_ids))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT t.user_asset_id, t.price_per_unit
                FROM asset_transactions t
                JOIN (
                    SELECT user_asset_id, MAX(id) AS latest_id
                    FROM asset_transactions
                    WHERE user_asset_id IN ({placeholders})
                      AND price_per_unit IS NOT NULL
                    GROUP BY user_asset_id
                ) latest ON latest.latest_id = t.id
                """,
                asset_ids,
            )
            rows = cur.fetchall()

        return {
            row["user_asset_id"]: Decimal(str(row["price_per_unit"]))
            for row in rows
            if row["price_per_unit"] is not None
        }

    def _get_bond_price_for_date(
        self, asset_id: int, price_date: date
    ) -> Optional[Decimal]:
        """Return latest manual bond price on or before price_date."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT price_per_unit
                FROM bond_daily_prices
                WHERE user_asset_id = %s
                  AND price_date <= %s
                ORDER BY price_date DESC
                LIMIT 1
                """,
                (asset_id, price_date),
            )
            row = cur.fetchone()
        if row and row["price_per_unit"] is not None:
            return Decimal(str(row["price_per_unit"]))
        return None

    def _get_rate_pair(
        self, today: date, yesterday: date
    ) -> dict[date, Decimal]:
        """Fetch today's and yesterday's USD/CNY rates in one query."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT rate_date, rate
                FROM exchange_rates
                WHERE from_currency = %s
                  AND to_currency = %s
                  AND rate_date <= %s
                ORDER BY rate_date DESC
                LIMIT 2
                """,
                (self._fx.FROM_CURRENCY, self._fx.TO_CURRENCY, today),
            )
            rows = cur.fetchall()

        rate_by_date = {
            row["rate_date"]: Decimal(str(row["rate"])) for row in rows
        }
        latest_rate = (
            Decimal(str(rows[0]["rate"])) if rows else Decimal("0")
        )
        previous_rate = (
            Decimal(str(rows[1]["rate"]))
            if len(rows) > 1
            else latest_rate
        )
        return {
            today: rate_by_date.get(today, latest_rate),
            yesterday: rate_by_date.get(yesterday, previous_rate),
        }

    def _get_dashboard_stock_price_maps(
        self, tickers: list[str], today: date, yesterday: date
    ) -> dict[str, dict[str, Decimal]]:
        """Fetch latest available stock close prices for two dates together."""
        if not tickers:
            return {"today": {}, "yesterday": {}}

        placeholders = ", ".join(["%s"] * len(tickers))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT p.ticker_symbol, p.close_price, price_dates.target_label
                FROM stock_daily_prices p
                JOIN (
                    SELECT ticker_symbol,
                           'today' AS target_label,
                           MAX(trade_date) AS max_trade_date
                    FROM stock_daily_prices
                    WHERE ticker_symbol IN ({placeholders})
                      AND trade_date <= %s
                    GROUP BY ticker_symbol
                    UNION ALL
                    SELECT ticker_symbol,
                           'yesterday' AS target_label,
                           MAX(trade_date) AS max_trade_date
                    FROM stock_daily_prices
                    WHERE ticker_symbol IN ({placeholders})
                      AND trade_date <= %s
                    GROUP BY ticker_symbol
                ) price_dates
                  ON price_dates.ticker_symbol = p.ticker_symbol
                 AND price_dates.max_trade_date = p.trade_date
                """,
                (
                    *tickers,
                    today,
                    *tickers,
                    yesterday,
                ),
            )
            rows = cur.fetchall()

        today_prices = {}
        yesterday_prices = {}
        for row in rows:
            if row["target_label"] == "today":
                today_prices[row["ticker_symbol"]] = Decimal(
                    str(row["close_price"])
                )
            else:
                yesterday_prices[row["ticker_symbol"]] = Decimal(
                    str(row["close_price"])
                )
        return {"today": today_prices, "yesterday": yesterday_prices}

    def _get_latest_close_price_map(
        self, tickers: list[str], as_of_date: date
    ) -> dict[str, Decimal]:
        """Fetch the latest available close on or before as_of_date."""
        if not tickers:
            return {}

        placeholders = ", ".join(["%s"] * len(tickers))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT p.ticker_symbol, p.close_price
                FROM stock_daily_prices p
                JOIN (
                    SELECT ticker_symbol, MAX(trade_date) AS max_trade_date
                    FROM stock_daily_prices
                    WHERE ticker_symbol IN ({placeholders})
                      AND trade_date <= %s
                    GROUP BY ticker_symbol
                ) latest
                  ON latest.ticker_symbol = p.ticker_symbol
                 AND latest.max_trade_date = p.trade_date
                """,
                (*tickers, as_of_date),
            )
            rows = cur.fetchall()

        return {
            row["ticker_symbol"]: Decimal(str(row["close_price"]))
            for row in rows
        }

    def _get_realtime_price_map(
        self, tickers: list[str]
    ) -> dict[str, Decimal]:
        """Fetch the cached real-time prices for a set of tickers."""
        if not tickers:
            return {}

        placeholders = ", ".join(["%s"] * len(tickers))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker_symbol, last_price
                FROM price_update_log
                WHERE ticker_symbol IN ({placeholders})
                  AND last_price IS NOT NULL
                """,
                tickers,
            )
            rows = cur.fetchall()

        return {
            row["ticker_symbol"]: Decimal(str(row["last_price"]))
            for row in rows
        }

    def _get_latest_price_info_map(
        self,
        tickers: list[str],
        stock_close_today: dict[str, Decimal],
        stock_close_yesterday: dict[str, Decimal],
    ) -> dict[str, dict]:
        """Fetch latest display price info for multiple stock tickers."""
        if not tickers:
            return {}

        placeholders = ", ".join(["%s"] * len(tickers))
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker_symbol, last_price, last_updated_at, market_state
                FROM price_update_log
                WHERE ticker_symbol IN ({placeholders})
                  AND last_price IS NOT NULL
                """,
                tickers,
            )
            rows = cur.fetchall()

        result = {}
        for row in rows:
            ticker = row["ticker_symbol"]
            rt_price = float(row["last_price"])
            close_today = stock_close_today.get(ticker)
            close_yesterday = stock_close_yesterday.get(ticker)
            state = row["market_state"] or "REGULAR"
            state_label = {
                "PRE": "盘前",
                "POST": "盘后",
                "REGULAR": "实时",
                "CLOSED": "收盘",
            }.get(state, state)

            if state != "CLOSED" and close_today and close_today > 0:
                ref_price = float(close_today)
                ref_label = "收盘"
                change_pct = round(
                    (rt_price - ref_price) / ref_price * 100, 2
                )
            elif close_yesterday and close_yesterday > 0:
                ref_price = float(close_yesterday)
                ref_label = "前收"
                change_pct = round(
                    (rt_price - ref_price) / ref_price * 100, 2
                )
            else:
                ref_price = None
                ref_label = None
                change_pct = 0.0

            updated_at = row["last_updated_at"]
            result[ticker] = {
                "price": rt_price,
                "updated_at": (
                    updated_at.strftime("%H:%M")
                    if updated_at
                    else None
                ),
                "market_state_label": state_label,
                "change_pct": change_pct,
                "ref_price": ref_price,
                "ref_label": ref_label,
            }

        for ticker in tickers:
            if ticker in result:
                continue
            close_today = stock_close_today.get(ticker)
            close_yesterday = stock_close_yesterday.get(ticker)
            latest_close = close_today or close_yesterday
            previous_close = close_yesterday
            if latest_close is None:
                continue
            change_pct = 0.0
            ref_price = None
            ref_label = None
            if previous_close and previous_close > 0:
                ref_price = float(previous_close)
                ref_label = "前收"
                change_pct = round(
                    (float(latest_close) - ref_price) / ref_price * 100,
                    2,
                )
            result[ticker] = {
                "price": float(latest_close),
                "updated_at": None,
                "market_state_label": "收盘",
                "change_pct": change_pct,
                "ref_price": ref_price,
                "ref_label": ref_label,
            }

        return result

    def _get_asset_type_by_code(
        self, type_code: str
    ) -> dict | None:
        """Lookup asset type by code."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, type_code, type_name, currency,
                       has_market_price, needs_ticker
                FROM asset_types
                WHERE type_code = %s
                """,
                (type_code.upper(),),
            )
            return cur.fetchone()

    def get_asset_types(self) -> list[dict]:
        """Return all asset types for the add-asset form."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, type_code, type_name, currency,
                       has_market_price, needs_ticker
                FROM asset_types
                ORDER BY display_order
                """
            )
            return cur.fetchall()

    def _get_asset_for_sync(self, asset_id: int) -> dict | None:
        """Return the minimum asset fields needed for history sync."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT ua.ticker_symbol, at2.has_market_price,
                       at2.type_code
                FROM user_assets ua
                JOIN asset_types at2 ON ua.asset_type_id = at2.id
                WHERE ua.id = %s
                """,
                (asset_id,),
            )
            return cur.fetchone()

    def _calculate_transaction_total_amount(
        self,
        asset_type_code: str,
        quantity: Decimal,
        price_per_unit: Decimal | None,
    ) -> Decimal:
        """Compute stored cash amount for a transaction."""
        if price_per_unit is None:
            return quantity
        if asset_type_code == "BOND":
            return quantity * price_per_unit / self.BOND_PAR_PRICE
        return quantity * price_per_unit

    def _sync_supporting_data_from_date(
        self, asset: dict, ticker: str | None, from_date: date
    ) -> None:
        """Backfill prices and FX history when a dated transaction is inserted."""
        if asset.get("has_market_price") and ticker:
            try:
                self._market.backfill_prices(ticker, from_date)
            except Exception:
                logger.warning(
                    "Failed to backfill prices for %s", ticker, exc_info=True
                )

        try:
            self._fx.ensure_rates_current()
        except Exception:
            logger.warning(
                "Failed to backfill exchange rates", exc_info=True
            )

    def get_earliest_buy_date(self, user_id: int) -> date | None:
        """Return the earliest transaction date across all active assets."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT MIN(at2.transaction_date) AS earliest
                FROM asset_transactions at2
                JOIN user_assets ua ON at2.user_asset_id = ua.id
                WHERE ua.user_id = %s AND ua.is_active = 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if row and row["earliest"]:
            return row["earliest"]
        return None

    def verify_asset_ownership(
        self, asset_id: int, user_id: int
    ) -> bool:
        """Check if an asset belongs to a user."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id FROM user_assets
                WHERE id = %s AND user_id = %s AND is_active = 1
                """,
                (asset_id, user_id),
            )
            return cur.fetchone() is not None
