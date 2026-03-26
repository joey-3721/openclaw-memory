"""Exchange rate service — fetch and cache USD/CNY daily rates."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from ..db import get_cursor


class ExchangeRateService:
    """Handles USD/CNY exchange rate fetching and caching."""

    TICKER = "CNY=X"
    FROM_CURRENCY = "USD"
    TO_CURRENCY = "CNY"
    REFRESH_KEY = "usd_cny_rates"

    def get_rate_for_date(self, rate_date: date) -> Optional[Decimal]:
        """Get rate for a specific date, fallback to nearest prior."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT rate FROM exchange_rates
                WHERE from_currency = %s
                  AND to_currency = %s
                  AND rate_date <= %s
                ORDER BY rate_date DESC
                LIMIT 1
                """,
                (self.FROM_CURRENCY, self.TO_CURRENCY, rate_date),
            )
            row = cur.fetchone()
        if row:
            return Decimal(str(row["rate"]))
        return None

    def get_latest_rate(self) -> dict | None:
        """Return {date, rate} for the most recent available rate."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT rate_date, rate FROM exchange_rates
                WHERE from_currency = %s AND to_currency = %s
                ORDER BY rate_date DESC
                LIMIT 1
                """,
                (self.FROM_CURRENCY, self.TO_CURRENCY),
            )
            row = cur.fetchone()
        if row:
            return {
                "from": self.FROM_CURRENCY,
                "to": self.TO_CURRENCY,
                "rate": float(row["rate"]),
                "date": row["rate_date"].isoformat(),
            }
        return None

    def get_rates_in_range(
        self, start_date: date, end_date: date
    ) -> dict[date, Decimal]:
        """Fetch all stored rates in a date range as {date: rate}."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT rate_date, rate FROM exchange_rates
                WHERE from_currency = %s
                  AND to_currency = %s
                  AND rate_date BETWEEN %s AND %s
                ORDER BY rate_date
                """,
                (
                    self.FROM_CURRENCY,
                    self.TO_CURRENCY,
                    start_date,
                    end_date,
                ),
            )
            rows = cur.fetchall()
        return {
            row["rate_date"]: Decimal(str(row["rate"])) for row in rows
        }

    def backfill_rates_from_yfinance(
        self, from_date: date, to_date: date | None = None
    ) -> int:
        """Fetch USD/CNY rates from yfinance and store in DB."""
        import yfinance as yf

        to_date = to_date or date.today()
        end_fetch = to_date + timedelta(days=1)

        try:
            tk = yf.Ticker(self.TICKER)
            hist = tk.history(
                start=from_date.isoformat(),
                end=end_fetch.isoformat(),
            )
        except Exception:
            return 0

        if hist.empty:
            self.mark_rates_refreshed()
            return 0

        rows_to_insert = []
        for idx, row in hist.iterrows():
            trade_dt = idx.date() if hasattr(idx, "date") else idx
            close_val = float(row["Close"])
            if close_val > 0:
                rows_to_insert.append((trade_dt, close_val))

        if not rows_to_insert:
            return 0

        with get_cursor() as cur:
            for rate_dt, rate_val in rows_to_insert:
                cur.execute(
                    """
                    INSERT INTO exchange_rates
                        (from_currency, to_currency, rate_date, rate)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE rate = VALUES(rate)
                    """,
                    (
                        self.FROM_CURRENCY,
                        self.TO_CURRENCY,
                        rate_dt,
                        rate_val,
                    ),
                )
        self.mark_rates_refreshed()
        return len(rows_to_insert)

    def get_last_refresh_time(self) -> datetime | None:
        """Return the last successful exchange-rate refresh time."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT last_refreshed_at
                FROM refresh_state
                WHERE refresh_key = %s
                """,
                (self.REFRESH_KEY,),
            )
            row = cur.fetchone()
        return row["last_refreshed_at"] if row else None

    def mark_rates_refreshed(self) -> None:
        """Persist the last successful exchange-rate refresh time."""
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO refresh_state
                    (refresh_key, last_refreshed_at, note)
                VALUES (%s, NOW(), %s)
                ON DUPLICATE KEY UPDATE
                    last_refreshed_at = NOW(),
                    note = VALUES(note)
                """,
                (self.REFRESH_KEY, "USD/CNY rates"),
            )

    def should_refresh_rates(self, max_age_minutes: int = 60) -> bool:
        """Return True when exchange rates have not been refreshed recently."""
        last_refresh = self.get_last_refresh_time()
        if not last_refresh:
            return True
        return (datetime.now() - last_refresh).total_seconds() > (
            max_age_minutes * 60
        )

    def ensure_rates_current(self, max_age_minutes: int = 60) -> None:
        """Refresh rates only when the last refresh is older than max_age."""
        if not self.should_refresh_rates(max_age_minutes=max_age_minutes):
            return

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(rate_date) AS last_date
                FROM exchange_rates
                WHERE from_currency = %s AND to_currency = %s
                """,
                (self.FROM_CURRENCY, self.TO_CURRENCY),
            )
            row = cur.fetchone()

        last_date = row["last_date"] if row else None
        today = date.today()

        if last_date is None:
            self.backfill_rates_from_yfinance(
                today - timedelta(days=365), today
            )
        elif last_date < today - timedelta(days=1):
            self.backfill_rates_from_yfinance(
                last_date + timedelta(days=1), today
            )
        else:
            self.mark_rates_refreshed()
