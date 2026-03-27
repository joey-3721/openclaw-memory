"""Snapshot service — compute and store daily asset value totals."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from ..db import get_cursor
from .asset_service import AssetService
from .exchange_rate_service import ExchangeRateService


class SnapshotService:
    """Pre-compute daily total asset values per user."""

    def __init__(self) -> None:
        self._assets = AssetService()
        self._fx = ExchangeRateService()

    def _ensure_snapshot_rows(
        self, user_id: int, from_date: date, to_date: date
    ) -> None:
        """Ensure snapshot rows exist before applying incremental deltas."""
        existing = self.get_existing_snapshot_dates(user_id, from_date, to_date)
        current = from_date
        while current <= to_date:
            if current not in existing:
                self.compute_snapshot(user_id, current)
            current += timedelta(days=1)

    def _get_asset_snapshot_meta(self, asset_id: int) -> dict | None:
        """Return minimum asset fields needed for per-asset snapshot deltas."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT ua.id, ua.user_id, ua.ticker_symbol,
                       at2.type_code
                FROM user_assets ua
                JOIN asset_types at2 ON at2.id = ua.asset_type_id
                WHERE ua.id = %s
                """,
                (asset_id,),
            )
            return cur.fetchone()

    def _get_carried_fx_rates(
        self, from_date: date, to_date: date
    ) -> dict[date, Decimal]:
        """Return a daily FX map using the latest known prior rate."""
        latest_rate = self._fx.get_rate_for_date(from_date) or Decimal("7.2")
        daily_rates: dict[date, Decimal] = {}
        rate_rows = self._fx.get_rates_in_range(from_date, to_date)
        current = from_date
        while current <= to_date:
            latest_rate = rate_rows.get(current, latest_rate)
            daily_rates[current] = latest_rate
            current += timedelta(days=1)
        return daily_rates

    def _get_asset_bucket_fields(self, type_code: str) -> tuple[str, str]:
        """Return (bucket_field, total_field) for snapshot updates."""
        if type_code == "STOCK":
            return ("stock_value_cny", "total_value_cny")
        if type_code == "BOND":
            return ("bond_value_cny", "total_value_cny")
        return ("cash_value_cny", "total_value_cny")

    def _get_position_delta_rows(
        self, asset_id: int, from_date: date, to_date: date
    ) -> tuple[Decimal, dict[date, Decimal]]:
        """Return initial position before range and daily tx deltas."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN direction = 'BUY' THEN quantity
                         ELSE -quantity
                    END
                ), 0) AS position_before
                FROM asset_transactions
                WHERE user_asset_id = %s
                  AND transaction_date < %s
                """,
                (asset_id, from_date),
            )
            before_row = cur.fetchone()

            cur.execute(
                """
                SELECT transaction_date,
                       COALESCE(SUM(
                           CASE WHEN direction = 'BUY' THEN quantity
                                ELSE -quantity
                           END
                       ), 0) AS qty_delta
                FROM asset_transactions
                WHERE user_asset_id = %s
                  AND transaction_date BETWEEN %s AND %s
                GROUP BY transaction_date
                ORDER BY transaction_date
                """,
                (asset_id, from_date, to_date),
            )
            delta_rows = cur.fetchall()

        before = Decimal(str((before_row or {}).get("position_before") or 0))
        delta_by_date = {
            row["transaction_date"]: Decimal(str(row["qty_delta"]))
            for row in delta_rows
        }
        return before, delta_by_date

    def _get_stock_price_series(
        self, ticker: str, from_date: date, to_date: date
    ) -> dict[date, Decimal | None]:
        """Return daily carried stock close prices for a date range."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, close_price
                FROM stock_daily_prices
                WHERE ticker_symbol = %s
                  AND trade_date <= %s
                ORDER BY trade_date
                """,
                (ticker, to_date),
            )
            rows = cur.fetchall()

        latest_price = None
        price_by_date = {}
        for row in rows:
            trade_date = row["trade_date"]
            latest_price = Decimal(str(row["close_price"]))
            if trade_date >= from_date:
                price_by_date[trade_date] = latest_price

        carried = {}
        current = from_date
        while current <= to_date:
            if current in price_by_date:
                latest_price = price_by_date[current]
            carried[current] = latest_price
            current += timedelta(days=1)
        return carried

    def _build_asset_cny_series(
        self, asset: dict, from_date: date, to_date: date
    ) -> list[tuple[date, Decimal]]:
        """Build one asset's daily CNY value series for snapshot deltas."""
        asset_id = asset["id"]
        type_code = asset["type_code"]
        before_position, delta_by_date = self._get_position_delta_rows(
            asset_id, from_date, to_date
        )
        daily_rates = self._get_carried_fx_rates(from_date, to_date)
        price_series = {}
        if type_code == "STOCK" and asset.get("ticker_symbol"):
            price_series = self._get_stock_price_series(
                asset["ticker_symbol"], from_date, to_date
            )

        values: list[tuple[date, Decimal]] = []
        position = before_position
        current = from_date
        while current <= to_date:
            position += delta_by_date.get(current, Decimal("0"))
            usd_value = Decimal("0")
            if position > 0:
                if type_code == "STOCK":
                    price = price_series.get(current)
                    usd_value = position * price if price else Decimal("0")
                elif type_code in {"BOND", "CASH"}:
                    usd_value = position
            values.append((current, usd_value * daily_rates[current]))
            current += timedelta(days=1)
        return values

    def apply_cash_quantity_delta(
        self, user_id: int, from_date: date, usd_delta: Decimal
    ) -> int:
        """Fast-path update snapshots for a cash quantity change."""
        if not usd_delta:
            return 0

        to_date = date.today()
        self._ensure_snapshot_rows(user_id, from_date, to_date)
        daily_rates = self._get_carried_fx_rates(from_date, to_date)

        updates = []
        current = from_date
        while current <= to_date:
            delta_cny = usd_delta * daily_rates[current]
            updates.append(
                (str(delta_cny), str(delta_cny), user_id, current)
            )
            current += timedelta(days=1)

        with get_cursor() as cur:
            cur.executemany(
                """
                UPDATE daily_asset_snapshots
                SET cash_value_cny = cash_value_cny + %s,
                    total_value_cny = total_value_cny + %s
                WHERE user_id = %s
                  AND snapshot_date = %s
                """,
                updates,
            )
        return len(updates)

    def apply_asset_position_delta(
        self,
        user_id: int,
        asset_id: int,
        from_date: date,
        quantity_delta: Decimal,
    ) -> int:
        """Fast-path update snapshots for one transaction delta."""
        if not quantity_delta:
            return 0

        asset = self._get_asset_snapshot_meta(asset_id)
        if not asset:
            return 0

        to_date = date.today()
        self._ensure_snapshot_rows(user_id, from_date, to_date)
        daily_rates = self._get_carried_fx_rates(from_date, to_date)
        bucket_field, total_field = self._get_asset_bucket_fields(
            asset["type_code"]
        )
        price_series = {}
        if asset["type_code"] == "STOCK" and asset.get("ticker_symbol"):
            price_series = self._get_stock_price_series(
                asset["ticker_symbol"], from_date, to_date
            )

        updates = []
        current = from_date
        while current <= to_date:
            usd_value = Decimal("0")
            if asset["type_code"] == "STOCK":
                price = price_series.get(current)
                usd_value = quantity_delta * price if price else Decimal("0")
            else:
                usd_value = quantity_delta
            delta_cny = usd_value * daily_rates[current]
            updates.append((str(delta_cny), str(delta_cny), user_id, current))
            current += timedelta(days=1)

        with get_cursor() as cur:
            cur.executemany(
                f"""
                UPDATE daily_asset_snapshots
                SET {bucket_field} = {bucket_field} + %s,
                    {total_field} = {total_field} + %s
                WHERE user_id = %s
                  AND snapshot_date = %s
                """,
                updates,
            )
        return len(updates)

    def apply_cash_asset_snapshot_delta(
        self,
        user_id: int,
        asset_id: int,
        from_date: date,
        multiplier: int,
    ) -> int:
        """Fast-path add/remove one cash asset from historical snapshots."""
        to_date = date.today()
        self._ensure_snapshot_rows(user_id, from_date, to_date)
        daily_rates = self._get_carried_fx_rates(from_date, to_date)

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT transaction_date,
                       COALESCE(SUM(
                           CASE WHEN direction = 'BUY' THEN quantity
                                ELSE -quantity
                           END
                       ), 0) AS qty_delta
                FROM asset_transactions
                WHERE user_asset_id = %s
                  AND transaction_date BETWEEN %s AND %s
                GROUP BY transaction_date
                ORDER BY transaction_date
                """,
                (asset_id, from_date, to_date),
            )
            delta_rows = cur.fetchall()

            cur.execute(
                """
                SELECT COALESCE(SUM(
                    CASE WHEN direction = 'BUY' THEN quantity
                         ELSE -quantity
                    END
                ), 0) AS position_before
                FROM asset_transactions
                WHERE user_asset_id = %s
                  AND transaction_date < %s
                """,
                (asset_id, from_date),
            )
            before_row = cur.fetchone()

        delta_by_date = {
            row["transaction_date"]: Decimal(str(row["qty_delta"]))
            for row in delta_rows
        }
        position = Decimal(str((before_row or {}).get("position_before") or 0))
        updates = []
        current = from_date
        while current <= to_date:
            position += delta_by_date.get(current, Decimal("0"))
            delta_cny = position * daily_rates[current] * Decimal(multiplier)
            updates.append(
                (str(delta_cny), str(delta_cny), user_id, current)
            )
            current += timedelta(days=1)

        with get_cursor() as cur:
            cur.executemany(
                """
                UPDATE daily_asset_snapshots
                SET cash_value_cny = cash_value_cny + %s,
                    total_value_cny = total_value_cny + %s
                WHERE user_id = %s
                  AND snapshot_date = %s
                """,
                updates,
            )
        return len(updates)

    def apply_asset_snapshot_delta(
        self,
        user_id: int,
        asset_id: int,
        from_date: date,
        multiplier: int,
    ) -> int:
        """Fast-path add or remove one asset's full historical contribution."""
        asset = self._get_asset_snapshot_meta(asset_id)
        if not asset:
            return 0

        if asset["type_code"] == "CASH":
            return self.apply_cash_asset_snapshot_delta(
                user_id, asset_id, from_date, multiplier
            )

        to_date = date.today()
        self._ensure_snapshot_rows(user_id, from_date, to_date)
        bucket_field, total_field = self._get_asset_bucket_fields(
            asset["type_code"]
        )
        value_series = self._build_asset_cny_series(asset, from_date, to_date)
        updates = [
            (
                str(value_cny * Decimal(multiplier)),
                str(value_cny * Decimal(multiplier)),
                user_id,
                value_date,
            )
            for value_date, value_cny in value_series
        ]
        with get_cursor() as cur:
            cur.executemany(
                f"""
                UPDATE daily_asset_snapshots
                SET {bucket_field} = {bucket_field} + %s,
                    {total_field} = {total_field} + %s
                WHERE user_id = %s
                  AND snapshot_date = %s
                """,
                updates,
            )
        return len(updates)

    def get_rebuild_status(self, user_id: int) -> dict:
        """Return current snapshot rebuild status for a user."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT status, refresh_from, pending_refresh_from,
                       started_at, finished_at,
                       last_completed_at, last_snapshot_date,
                       rebuilt_days, message
                FROM snapshot_rebuild_state
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()

        if not row:
            return {
                "status": "IDLE",
                "is_running": False,
                "can_start": True,
                "message": "尚未执行历史回填",
                "last_completed_at_display": "尚未执行",
            }

        status = row["status"] or "IDLE"
        is_running = status in {"QUEUED", "RUNNING"}
        refresh_from = row["refresh_from"]
        pending_refresh_from = row.get("pending_refresh_from")
        started_at = row["started_at"]
        finished_at = row["finished_at"]
        last_completed_at = row["last_completed_at"]
        last_snapshot_date = row["last_snapshot_date"]
        rebuilt_days = int(row["rebuilt_days"] or 0)
        message = row["message"] or ""
        total_days = 0
        progress_pct = 0.0
        if refresh_from:
            total_days = max((date.today() - refresh_from).days + 1, 0)
            if total_days:
                progress_pct = min(
                    100.0,
                    round((rebuilt_days / total_days) * 100, 1),
                )

        return {
            "status": status,
            "is_running": is_running,
            "can_start": not is_running,
            "refresh_from": (
                refresh_from.isoformat() if refresh_from else None
            ),
            "pending_refresh_from": (
                pending_refresh_from.isoformat()
                if pending_refresh_from
                else None
            ),
            "started_at_iso": (
                started_at.isoformat() if started_at else None
            ),
            "finished_at_iso": (
                finished_at.isoformat() if finished_at else None
            ),
            "last_completed_at_iso": (
                last_completed_at.isoformat()
                if last_completed_at
                else None
            ),
            "last_snapshot_date": (
                last_snapshot_date.isoformat()
                if last_snapshot_date
                else None
            ),
            "rebuilt_days": rebuilt_days,
            "total_days": total_days,
            "progress_pct": progress_pct,
            "message": message,
            "started_at_display": (
                started_at.strftime("%Y-%m-%d %H:%M")
                if started_at
                else "未开始"
            ),
            "finished_at_display": (
                finished_at.strftime("%Y-%m-%d %H:%M")
                if finished_at
                else "未完成"
            ),
            "last_completed_at_display": (
                last_completed_at.strftime("%Y-%m-%d %H:%M")
                if last_completed_at
                else "尚未执行"
            ),
            "last_snapshot_date_display": (
                last_snapshot_date.strftime("%Y-%m-%d")
                if last_snapshot_date
                else "尚未开始"
            ),
        }

    def request_partial_refresh(
        self, user_id: int, from_date: date
    ) -> dict:
        """Queue a partial historical rebuild from the earliest dirty date."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT status, refresh_from, pending_refresh_from
                FROM snapshot_rebuild_state
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()

        current_status = (row or {}).get("status") or "IDLE"
        refresh_candidates = [from_date]
        if row and row.get("refresh_from"):
            refresh_candidates.append(row["refresh_from"])
        if row and row.get("pending_refresh_from"):
            refresh_candidates.append(row["pending_refresh_from"])
        effective_from = min(refresh_candidates)

        should_start_worker = current_status not in {"QUEUED", "RUNNING"}
        if current_status == "RUNNING":
            self._upsert_rebuild_state(
                user_id=user_id,
                status="RUNNING",
                refresh_from=row.get("refresh_from") or effective_from,
                pending_refresh_from=effective_from,
                message=(
                    "历史趋势更新中，完成后会继续补算更早的数据"
                ),
                rebuilt_days=0,
                touch_started=False,
                touch_finished=False,
                touch_completed=False,
            )
        else:
            self._upsert_rebuild_state(
                user_id=user_id,
                status="QUEUED",
                refresh_from=effective_from,
                pending_refresh_from=None,
                message=(
                    f"历史趋势更新中，将从 {effective_from.isoformat()} 开始回填"
                ),
                rebuilt_days=0,
                touch_started=False,
                touch_finished=False,
                touch_completed=False,
            )

        status = self.get_rebuild_status(user_id)
        status["should_start_worker"] = should_start_worker
        return status

    def request_full_rebuild(self, user_id: int) -> dict:
        """Queue a full snapshot rebuild from the earliest asset date."""
        status = self.get_rebuild_status(user_id)
        if status["is_running"]:
            return status

        refresh_from = self._assets.get_earliest_buy_date(user_id)
        message = (
            "已加入重建队列"
            if refresh_from
            else "当前没有可回填的资产历史"
        )
        self._upsert_rebuild_state(
            user_id=user_id,
            status="QUEUED",
            refresh_from=refresh_from,
            pending_refresh_from=None,
            message=message,
            rebuilt_days=0,
            touch_started=False,
            touch_finished=False,
            touch_completed=False,
        )
        return self.get_rebuild_status(user_id)

    def run_full_rebuild(self, user_id: int) -> None:
        """Rebuild every stored snapshot row for a user from scratch."""
        refresh_from = self._assets.get_earliest_buy_date(user_id)
        self._upsert_rebuild_state(
            user_id=user_id,
            status="RUNNING",
            refresh_from=refresh_from,
            pending_refresh_from=None,
            message="正在重建历史快照...",
            rebuilt_days=0,
            touch_started=True,
            touch_finished=False,
            touch_completed=False,
        )

        try:
            with get_cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM daily_asset_snapshots
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )

            if not refresh_from:
                self._upsert_rebuild_state(
                    user_id=user_id,
                    status="SUCCEEDED",
                    refresh_from=None,
                    pending_refresh_from=None,
                    message="没有资产历史可回填",
                    rebuilt_days=0,
                    touch_started=False,
                    touch_finished=True,
                    touch_completed=True,
                    last_snapshot_date=None,
                )
                return

            def report_progress(
                current_date: date, built_days: int, total_days: int
            ) -> None:
                self._upsert_rebuild_state(
                    user_id=user_id,
                    status="RUNNING",
                    refresh_from=refresh_from,
                    pending_refresh_from=None,
                    message=(
                        f"历史趋势更新中，已回填到 {current_date.isoformat()} "
                        f"（{built_days}/{total_days}）"
                    ),
                    rebuilt_days=built_days,
                    touch_started=False,
                    touch_finished=False,
                    touch_completed=False,
                    last_snapshot_date=current_date,
                )

            rebuilt_days = self.backfill_snapshots(
                user_id,
                refresh_from,
                recompute_existing=True,
                progress_callback=report_progress,
            )
            self._upsert_rebuild_state(
                user_id=user_id,
                status="SUCCEEDED",
                refresh_from=refresh_from,
                pending_refresh_from=None,
                message=f"历史快照已重建，共回填 {rebuilt_days} 天",
                rebuilt_days=rebuilt_days,
                touch_started=False,
                touch_finished=True,
                touch_completed=True,
                last_snapshot_date=date.today(),
            )
        except Exception as exc:
            self._upsert_rebuild_state(
                user_id=user_id,
                status="FAILED",
                refresh_from=refresh_from,
                pending_refresh_from=None,
                message=f"历史快照重建失败: {exc}",
                rebuilt_days=0,
                touch_started=False,
                touch_finished=True,
                touch_completed=False,
            )
            raise

    def _upsert_rebuild_state(
        self,
        user_id: int,
        status: str,
        refresh_from: date | None,
        pending_refresh_from: date | None,
        message: str,
        rebuilt_days: int,
        touch_started: bool,
        touch_finished: bool,
        touch_completed: bool,
        last_snapshot_date: date | None = None,
    ) -> None:
        """Persist snapshot rebuild progress for frontend polling."""
        started_expr = "NOW()" if touch_started else "started_at"
        finished_expr = "NOW()" if touch_finished else "finished_at"
        completed_expr = (
            "NOW()" if touch_completed else "last_completed_at"
        )

        with get_cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO snapshot_rebuild_state
                    (user_id, status, refresh_from, pending_refresh_from,
                     started_at, finished_at,
                     last_completed_at, last_snapshot_date, rebuilt_days,
                     message)
                VALUES (
                    %s, %s, %s, %s,
                    {'NOW()' if touch_started else 'NULL'},
                    {'NOW()' if touch_finished else 'NULL'},
                    {'NOW()' if touch_completed else 'NULL'},
                    %s, %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    refresh_from = VALUES(refresh_from),
                    pending_refresh_from = VALUES(pending_refresh_from),
                    started_at = {started_expr},
                    finished_at = {finished_expr},
                    last_completed_at = {completed_expr},
                    last_snapshot_date = VALUES(last_snapshot_date),
                    rebuilt_days = VALUES(rebuilt_days),
                    message = VALUES(message)
                """,
                (
                    user_id,
                    status,
                    refresh_from,
                    pending_refresh_from,
                    last_snapshot_date,
                    rebuilt_days,
                    message,
                ),
            )

    def run_queued_refresh(self, user_id: int) -> None:
        """Process queued partial refreshes, merging multiple edits."""
        while True:
            with get_cursor() as cur:
                cur.execute(
                    """
                    SELECT refresh_from, pending_refresh_from
                    FROM snapshot_rebuild_state
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cur.fetchone()

            if not row:
                return

            refresh_from = (
                row.get("pending_refresh_from") or row.get("refresh_from")
            )
            if not refresh_from:
                return

            self._upsert_rebuild_state(
                user_id=user_id,
                status="RUNNING",
                refresh_from=refresh_from,
                pending_refresh_from=None,
                message=f"历史趋势更新中，从 {refresh_from.isoformat()} 开始回填",
                rebuilt_days=0,
                touch_started=True,
                touch_finished=False,
                touch_completed=False,
            )

            try:
                def report_progress(
                    current_date: date,
                    built_days: int,
                    total_days: int,
                ) -> None:
                    self._upsert_rebuild_state(
                        user_id=user_id,
                        status="RUNNING",
                        refresh_from=refresh_from,
                        pending_refresh_from=None,
                        message=(
                            f"历史趋势更新中，已回填到 "
                            f"{current_date.isoformat()} "
                            f"（{built_days}/{total_days}）"
                        ),
                        rebuilt_days=built_days,
                        touch_started=False,
                        touch_finished=False,
                        touch_completed=False,
                        last_snapshot_date=current_date,
                    )

                rebuilt_days = self.refresh_snapshots_from_date(
                    user_id,
                    refresh_from,
                    progress_callback=report_progress,
                )
            except Exception as exc:
                self._upsert_rebuild_state(
                    user_id=user_id,
                    status="FAILED",
                    refresh_from=refresh_from,
                    pending_refresh_from=None,
                    message=f"历史趋势回填失败: {exc}",
                    rebuilt_days=0,
                    touch_started=False,
                    touch_finished=True,
                    touch_completed=False,
                )
                raise

            with get_cursor() as cur:
                cur.execute(
                    """
                    SELECT pending_refresh_from
                    FROM snapshot_rebuild_state
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                pending_row = cur.fetchone()

            pending_refresh_from = (
                pending_row.get("pending_refresh_from")
                if pending_row
                else None
            )
            if pending_refresh_from:
                self._upsert_rebuild_state(
                    user_id=user_id,
                    status="QUEUED",
                    refresh_from=pending_refresh_from,
                    pending_refresh_from=None,
                    message=(
                        f"检测到新的历史变更，将继续从 "
                        f"{pending_refresh_from.isoformat()} 回填"
                    ),
                    rebuilt_days=rebuilt_days,
                    touch_started=False,
                    touch_finished=False,
                    touch_completed=False,
                )
                continue

            self._upsert_rebuild_state(
                user_id=user_id,
                status="SUCCEEDED",
                refresh_from=refresh_from,
                pending_refresh_from=None,
                message=f"历史趋势已更新，共回填 {rebuilt_days} 天",
                rebuilt_days=rebuilt_days,
                touch_started=False,
                touch_finished=True,
                touch_completed=True,
                last_snapshot_date=date.today(),
            )
            return

    def compute_snapshot(
        self, user_id: int, snapshot_date: date
    ) -> dict:
        """Calculate total_value_cny broken down by type for one day."""
        assets = self._assets.get_user_assets(user_id)
        rate = self._fx.get_rate_for_date(snapshot_date)
        if not rate:
            rate = Decimal("7.2")  # fallback

        stock_cny = Decimal("0")
        bond_cny = Decimal("0")
        cash_cny = Decimal("0")

        for asset in assets:
            position = self._assets.calculate_position_for_asset(
                asset["id"], snapshot_date
            )
            if position <= 0:
                continue

            usd_val = self._assets._compute_usd_value(
                asset, position, snapshot_date
            )
            if usd_val is None:
                continue

            cny_val = usd_val * rate
            tc = asset["type_code"]
            if tc == "STOCK":
                stock_cny += cny_val
            elif tc == "BOND":
                bond_cny += cny_val
            elif tc == "CASH":
                cash_cny += cny_val

        total_cny = stock_cny + bond_cny + cash_cny

        # Calculate net capital flow for this date (BUY - SELL in CNY)
        net_flow_cny = self._calculate_net_flow(
            user_id, snapshot_date, rate
        )

        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_asset_snapshots
                    (user_id, snapshot_date, total_value_cny,
                     stock_value_cny, bond_value_cny,
                     cash_value_cny, exchange_rate, net_flow_cny)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    total_value_cny = VALUES(total_value_cny),
                    stock_value_cny = VALUES(stock_value_cny),
                    bond_value_cny  = VALUES(bond_value_cny),
                    cash_value_cny  = VALUES(cash_value_cny),
                    exchange_rate   = VALUES(exchange_rate),
                    net_flow_cny    = VALUES(net_flow_cny)
                """,
                (
                    user_id,
                    snapshot_date,
                    str(total_cny),
                    str(stock_cny),
                    str(bond_cny),
                    str(cash_cny),
                    str(rate),
                    str(net_flow_cny),
                ),
            )

        return {
            "date": snapshot_date.isoformat(),
            "total_cny": float(total_cny),
            "stock_cny": float(stock_cny),
            "bond_cny": float(bond_cny),
            "cash_cny": float(cash_cny),
            "exchange_rate": float(rate),
        }

    def get_existing_snapshot_dates(
        self, user_id: int, from_date: date, to_date: date
    ) -> set[date]:
        """Return the set of dates that already have a snapshot."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_date
                FROM daily_asset_snapshots
                WHERE user_id = %s
                  AND snapshot_date BETWEEN %s AND %s
                """,
                (user_id, from_date, to_date),
            )
            return {row["snapshot_date"] for row in cur.fetchall()}

    def backfill_snapshots(
        self,
        user_id: int,
        from_date: date,
        to_date: date | None = None,
        recompute_existing: bool = False,
        progress_callback=None,
    ) -> int:
        """Compute snapshots for each date in range.

        By default we only compute missing historical dates, but when
        recompute_existing=True we recompute all dates in the range to
        handle retroactive transaction inserts (e.g. a user enters an
        older transaction_date after snapshots were already generated).
        """
        to_date = to_date or date.today()
        today = date.today()
        total_days = max((to_date - from_date).days + 1, 0)

        count = 0
        current = from_date
        existing = (
            set()
            if recompute_existing
            else self.get_existing_snapshot_dates(user_id, from_date, to_date)
        )
        while current <= to_date:
            if recompute_existing or current == today or current not in existing:
                self.compute_snapshot(user_id, current)
                count += 1
                if progress_callback:
                    progress_callback(current, count, total_days)
            current += timedelta(days=1)
        return count

    def get_earliest_snapshot_date(self, user_id: int) -> date | None:
        """Return the first snapshot date for the user."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT MIN(snapshot_date) AS first_snapshot_date
                FROM daily_asset_snapshots
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()

        return row["first_snapshot_date"] if row else None

    def _resolve_trend_start_date(
        self, user_id: int, range_value: str | int | None, end_date: date
    ) -> date | None:
        """Translate a range token into the earliest date to query."""
        earliest = self.get_earliest_snapshot_date(user_id)
        if not earliest:
            return None

        if isinstance(range_value, int):
            normalized = range_value
        else:
            normalized = str(range_value or "30").strip().lower()

        if normalized == "all":
            return earliest
        if normalized == "ytd":
            return max(date(end_date.year, 1, 1), earliest)

        try:
            days = int(normalized)
        except (TypeError, ValueError):
            days = 30

        start_date = end_date - timedelta(days=max(days - 1, 0))
        return max(start_date, earliest)

    def get_trend_data(
        self, user_id: int, range_value: str | int | None = 30
    ) -> list[dict]:
        """Return daily snapshots for trend chart."""
        end_date = date.today()
        start_date = self._resolve_trend_start_date(
            user_id, range_value, end_date
        )
        if not start_date:
            return []

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_date, total_value_cny,
                       stock_value_cny, bond_value_cny,
                       cash_value_cny, exchange_rate
                FROM daily_asset_snapshots
                WHERE user_id = %s
                  AND snapshot_date BETWEEN %s AND %s
                ORDER BY snapshot_date
                """,
                (user_id, start_date, end_date),
            )
            rows = cur.fetchall()

        trend = [
            {
                "date": row["snapshot_date"].isoformat(),
                "total_cny": float(row["total_value_cny"]),
                "stock_cny": float(row["stock_value_cny"]),
                "bond_cny": float(row["bond_value_cny"]),
                "cash_cny": float(row["cash_value_cny"]),
            }
            for row in rows
        ]
        return self._merge_live_today_point(
            user_id, trend, live_today=self.get_live_portfolio_snapshot(user_id)
        )

    def get_dashboard_snapshot_bundle(
        self, user_id: int, range_value: str | int | None = 30
    ) -> dict:
        """Fetch the dashboard snapshot data with minimal queries."""
        end_date = date.today()
        start_date = self._resolve_trend_start_date(
            user_id, range_value, end_date
        )

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_date, total_value_cny,
                       stock_value_cny, bond_value_cny,
                       cash_value_cny, exchange_rate,
                       net_flow_cny
                FROM daily_asset_snapshots
                WHERE user_id = %s
                ORDER BY snapshot_date DESC
                LIMIT 2
                """,
                (user_id,),
            )
            latest_rows = cur.fetchall()

            trend_rows = []
            if start_date:
                cur.execute(
                    """
                    SELECT snapshot_date, total_value_cny,
                           stock_value_cny, bond_value_cny,
                           cash_value_cny, exchange_rate
                    FROM daily_asset_snapshots
                    WHERE user_id = %s
                      AND snapshot_date BETWEEN %s AND %s
                    ORDER BY snapshot_date
                    """,
                    (user_id, start_date, end_date),
                )
                trend_rows = cur.fetchall()

        live_snapshot = self.get_live_portfolio_snapshot(user_id)
        latest = latest_rows[0] if latest_rows else None
        prev = latest_rows[1] if len(latest_rows) > 1 else None
        latest_snapshot = None
        if latest:
            prev_total = float(prev["total_value_cny"]) if prev else 0
            current_total = float(latest["total_value_cny"])
            current_net_flow = float(latest["net_flow_cny"])
            change = current_total - prev_total - current_net_flow
            change_pct = (
                (change / prev_total * 100) if prev_total else 0
            )
            latest_snapshot = {
                "date": latest["snapshot_date"].isoformat(),
                "total_cny": current_total,
                "stock_cny": float(latest["stock_value_cny"]),
                "bond_cny": float(latest["bond_value_cny"]),
                "cash_cny": float(latest["cash_value_cny"]),
                "exchange_rate": float(latest["exchange_rate"])
                if latest["exchange_rate"]
                else None,
                "change_cny": round(change, 2),
                "change_pct": round(change_pct, 2),
            }
        if live_snapshot:
            latest_snapshot = live_snapshot

        trend = [
            {
                "date": row["snapshot_date"].isoformat(),
                "total_cny": float(row["total_value_cny"]),
                "stock_cny": float(row["stock_value_cny"]),
                "bond_cny": float(row["bond_value_cny"]),
                "cash_cny": float(row["cash_value_cny"]),
                "exchange_rate": float(row["exchange_rate"])
                if row["exchange_rate"]
                else None,
            }
            for row in trend_rows
        ]
        trend = self._merge_live_today_point(
            user_id, trend, live_today=live_snapshot
        )
        return {
            "latest_snapshot": latest_snapshot,
            "trend": trend,
        }

    def get_live_portfolio_snapshot(self, user_id: int) -> dict:
        assets = self._assets.get_user_assets_with_values(user_id)
        total_cny = 0.0
        stock_cny = 0.0
        bond_cny = 0.0
        cash_cny = 0.0
        daily_change_cny = 0.0

        for asset in assets:
            value_cny = float(asset.get("value_cny", 0.0) or 0.0)
            change_cny = float(asset.get("change_cny", 0.0) or 0.0)
            total_cny += value_cny
            daily_change_cny += change_cny
            type_code = asset.get("type_code")
            if type_code == "STOCK":
                stock_cny += value_cny
            elif type_code == "BOND":
                bond_cny += value_cny
            elif type_code == "CASH":
                cash_cny += value_cny

        prev_total_cny = total_cny - daily_change_cny
        daily_change_pct = (
            (daily_change_cny / prev_total_cny * 100)
            if prev_total_cny
            else 0.0
        )
        return {
            "date": date.today().isoformat(),
            "total_cny": round(total_cny, 2),
            "stock_cny": round(stock_cny, 2),
            "bond_cny": round(bond_cny, 2),
            "cash_cny": round(cash_cny, 2),
            "change_cny": round(daily_change_cny, 2),
            "change_pct": round(daily_change_pct, 2),
        }

    def _merge_live_today_point(
        self,
        user_id: int,
        trend: list[dict],
        live_today: dict | None = None,
    ) -> list[dict]:
        """Replace/add today's trend point with live asset totals."""
        today_iso = date.today().isoformat()
        live_today = live_today or self.get_live_portfolio_snapshot(user_id)
        if not trend:
            return [live_today]

        merged = []
        replaced = False
        for item in trend:
            if item["date"] == today_iso:
                merged.append({**item, **live_today})
                replaced = True
            else:
                merged.append(item)

        if not replaced:
            merged.append(live_today)

        merged.sort(key=lambda item: item["date"])
        return merged

    def get_latest_snapshot(self, user_id: int) -> dict | None:
        """Most recent snapshot for summary widgets."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_date, total_value_cny,
                       stock_value_cny, bond_value_cny,
                       cash_value_cny, exchange_rate,
                       net_flow_cny
                FROM daily_asset_snapshots
                WHERE user_id = %s
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()

        if not row:
            return None

        # Get previous day for change calculation
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT total_value_cny
                FROM daily_asset_snapshots
                WHERE user_id = %s
                  AND snapshot_date < %s
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (user_id, row["snapshot_date"]),
            )
            prev = cur.fetchone()

        prev_total = float(prev["total_value_cny"]) if prev else 0
        current_total = float(row["total_value_cny"])
        current_net_flow = float(row["net_flow_cny"])
        # Deduct net capital flow so new purchases aren't counted as profit
        change = current_total - prev_total - current_net_flow
        change_pct = (
            (change / prev_total * 100) if prev_total else 0
        )

        return {
            "date": row["snapshot_date"].isoformat(),
            "total_cny": current_total,
            "stock_cny": float(row["stock_value_cny"]),
            "bond_cny": float(row["bond_value_cny"]),
            "cash_cny": float(row["cash_value_cny"]),
            "exchange_rate": float(row["exchange_rate"])
            if row["exchange_rate"]
            else None,
            "change_cny": round(change, 2),
            "change_pct": round(change_pct, 2),
        }

    def get_performance_summary(
        self, user_id: int, assets: list[dict] | None = None
    ) -> dict:
        """Return portfolio-level performance metrics in CNY.

        All summary cards intentionally use the same asset-performance
        lens as the asset detail cards, so the numbers stay visually and
        conceptually aligned across the page.
        """
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT snapshot_date, total_value_cny, net_flow_cny
                FROM daily_asset_snapshots
                WHERE user_id = %s
                ORDER BY snapshot_date
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        if not rows:
            return {
                "total_cny": 0.0,
                "daily_change_cny": 0.0,
                "daily_change_pct": 0.0,
                "total_pnl_cny": 0.0,
                "realized_pnl_cny": 0.0,
                "unrealized_pnl_cny": 0.0,
                "income_pnl_cny": 0.0,
                "total_return_pct": 0.0,
                "ytd_pnl_cny": 0.0,
                "ytd_return_pct": 0.0,
                "ytd_annualized_pct": 0.0,
                "ytd_days": 0,
            }

        normalized_rows = [
            {
                "date": row["snapshot_date"],
                "total": float(row["total_value_cny"]),
                "flow": float(row["net_flow_cny"] or 0),
            }
            for row in rows
        ]

        latest = normalized_rows[-1]
        assets = (
            assets
            if assets is not None
            else self._assets.get_user_assets_with_values(user_id)
        )
        live_total_cny = sum(
            asset.get("value_cny", 0.0) for asset in assets
        )
        daily_change = sum(
            asset.get("change_cny", 0.0) for asset in assets
        )
        prev_total = live_total_cny - daily_change
        daily_change_pct = (
            (daily_change / prev_total * 100) if prev_total else 0.0
        )
        unrealized_pnl_usd = sum(
            asset.get("unrealized_pnl_usd", 0.0) for asset in assets
        )
        realized_pnl_usd = sum(
            asset.get("realized_pnl_usd", 0.0) for asset in assets
        )
        income_pnl_usd = sum(
            asset.get("distribution_net_usd", 0.0) for asset in assets
        )
        total_pnl_usd = (
            unrealized_pnl_usd + realized_pnl_usd
        )
        total_cost_basis_usd = sum(
            asset.get("cost_basis_usd", 0.0) for asset in assets
        )
        latest_rate = float(
            self._fx.get_rate_for_date(latest["date"]) or Decimal("1")
        )
        unrealized_pnl_cny = unrealized_pnl_usd * latest_rate
        realized_pnl_cny = realized_pnl_usd * latest_rate
        income_pnl_cny = income_pnl_usd * latest_rate
        total_pnl_cny = total_pnl_usd * latest_rate
        total_return_pct = (
            total_pnl_usd / total_cost_basis_usd * 100
            if total_cost_basis_usd > 0
            else 0.0
        )

        year_start = date(date.today().year, 1, 1)
        opening_value = 0.0
        ytd_rows = []
        for row in normalized_rows:
            if row["date"] < year_start:
                opening_value = row["total"]
            else:
                ytd_rows.append(row)

        if ytd_rows:
            effective_start = (
                year_start if opening_value > 0 else ytd_rows[0]["date"]
            )
            ytd_base_value = (
                opening_value if opening_value > 0 else ytd_rows[0]["total"]
            )
            ytd_income_cny = self._get_asset_income_cny_since(
                user_id, effective_start, latest["date"], latest_rate
            )
            ytd_pnl_cny = (
                live_total_cny - ytd_base_value + ytd_income_cny
            )
            ytd_return = (
                (live_total_cny - ytd_base_value + ytd_income_cny)
                / ytd_base_value
                if ytd_base_value > 0
                else 0.0
            )
            ytd_days = max(
                (latest["date"] - effective_start).days + 1, 1
            )
            ytd_annualized_pct = (
                self._annualize_return(ytd_return, ytd_days) * 100
            )
            ytd_return_pct = ytd_return * 100
        else:
            ytd_pnl_cny = 0.0
            ytd_return_pct = 0.0
            ytd_annualized_pct = 0.0
            ytd_days = 0

        return {
            "total_cny": round(live_total_cny, 2),
            "daily_change_cny": round(daily_change, 2),
            "daily_change_pct": round(daily_change_pct, 2),
            "total_pnl_cny": round(total_pnl_cny, 2),
            "realized_pnl_cny": round(realized_pnl_cny, 2),
            "unrealized_pnl_cny": round(unrealized_pnl_cny, 2),
            "income_pnl_cny": round(income_pnl_cny, 2),
            "total_return_pct": round(total_return_pct, 2),
            "ytd_pnl_cny": round(ytd_pnl_cny, 2),
            "ytd_return_pct": round(ytd_return_pct, 2),
            "ytd_annualized_pct": round(ytd_annualized_pct, 2),
            "ytd_days": ytd_days,
        }

    def _get_asset_income_cny_since(
        self,
        user_id: int,
        from_date: date,
        to_date: date,
        fx_rate: float,
    ) -> float:
        """Sum card-level income flows for the period and convert to CNY."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(acf.amount), 0) AS total_income_usd
                FROM asset_cash_flows acf
                JOIN user_assets ua ON ua.id = acf.user_asset_id
                WHERE ua.user_id = %s
                  AND ua.is_active = 1
                  AND acf.flow_date BETWEEN %s AND %s
                  AND acf.flow_type IN (
                      'DISTRIBUTION',
                      'WITHHOLDING_TAX',
                      'INTEREST',
                      'BROKER_INTEREST'
                  )
                """,
                (user_id, from_date, to_date),
            )
            row = cur.fetchone()
        return float(row["total_income_usd"] or 0) * fx_rate

    def ensure_today_snapshot(self, user_id: int) -> None:
        """Compute (or recompute) today's snapshot.

        Always recompute because an earlier run may have produced zeros
        when price / FX data was not yet available.
        """
        self.compute_snapshot(user_id, date.today())

    def refresh_recent_history_if_needed(
        self, user_id: int, lookback_minutes: int = 60
    ) -> date | None:
        """Repair snapshots when a recently created trade has an older effective date.

        A user may enter a transaction today but set its business date in the
        past. In that case, the position *should* exist today, but it should
        also be reflected in all snapshots from that historical date onward so
        that today's change does not look like a sudden jump.
        """
        refresh_from = self.get_recent_transaction_refresh_date(
            user_id, lookback_minutes=lookback_minutes
        )
        if not refresh_from:
            return None
        if refresh_from < date.today():
            self.refresh_snapshots_from_date(user_id, refresh_from)
        else:
            self.ensure_today_snapshot(user_id)
        return refresh_from

    def refresh_snapshots_from_date(
        self, user_id: int, from_date: date, progress_callback=None
    ) -> int:
        """Recompute snapshots from an effective transaction date onward."""
        return self.backfill_snapshots(
            user_id,
            from_date,
            recompute_existing=True,
            progress_callback=progress_callback,
        )

    def get_recent_transaction_refresh_date(
        self, user_id: int, lookback_minutes: int = 15
    ) -> date | None:
        """Return the earliest effective date among recently created trades."""
        created_after = datetime.now() - timedelta(minutes=lookback_minutes)
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT MIN(at2.transaction_date) AS refresh_from
                FROM asset_transactions at2
                JOIN user_assets ua ON at2.user_asset_id = ua.id
                WHERE ua.user_id = %s
                  AND ua.is_active = 1
                  AND at2.created_at >= %s
                """,
                (user_id, created_after),
            )
            row = cur.fetchone()

        return row["refresh_from"] if row else None

    def _calculate_net_flow(
        self, user_id: int, snapshot_date: date, rate: Decimal
    ) -> Decimal:
        """Net capital flow for a user on a given date in CNY.

        We combine:
        - IBKR external cash movements (deposits / withdrawals)
        - Manual trades, which act as principal movements because manual
          entries do not have a separate cash ledger
        """
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total_amt
                FROM ibkr_flex_events
                WHERE user_id = %s
                  AND normalized_type IN ('DEPOSIT', 'WITHDRAWAL')
                  AND DATE(event_at) = %s
                """,
                (user_id, snapshot_date),
            )
            ibkr_row = cur.fetchone()

            cur.execute(
                """
                SELECT t.direction,
                       COALESCE(SUM(t.total_amount), 0) AS total_amount,
                       COALESCE(SUM(t.fee), 0) AS total_fee
                FROM asset_transactions t
                JOIN user_assets ua ON ua.id = t.user_asset_id
                WHERE ua.user_id = %s
                  AND ua.is_active = 1
                  AND t.source_system = 'MANUAL'
                  AND t.transaction_date = %s
                GROUP BY t.direction
                """,
                (user_id, snapshot_date),
            )
            manual_rows = cur.fetchall()

        flow_usd = Decimal(str(ibkr_row["total_amt"] or 0))
        for row in manual_rows:
            total_amount = Decimal(str(row["total_amount"] or 0))
            total_fee = Decimal(str(row["total_fee"] or 0))
            if row["direction"] == "BUY":
                flow_usd += total_amount + total_fee
            elif row["direction"] == "SELL":
                flow_usd -= total_amount - total_fee

        return flow_usd * rate

    def _calculate_time_weighted_return(
        self, rows: list[dict], opening_value: float
    ) -> float:
        """Compound period returns after removing external flows."""
        factor = 1.0
        prev_value = float(opening_value)
        has_return_period = False

        for row in rows:
            current_value = float(row["total"])
            net_flow = float(row["flow"])
            if prev_value > 0:
                period_return = (
                    current_value - prev_value - net_flow
                ) / prev_value
                factor *= 1 + period_return
                has_return_period = True
            prev_value = current_value

        return factor - 1 if has_return_period else 0.0

    def _annualize_return(
        self, period_return: float, days_elapsed: int
    ) -> float:
        """Annualize a period return using compounding."""
        if days_elapsed <= 0:
            return 0.0
        if period_return <= -1:
            return -1.0
        return (1 + period_return) ** (365 / days_elapsed) - 1
