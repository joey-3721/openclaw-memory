"""Market data service — validate tickers and fetch stock prices."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from ..db import get_cursor

logger = logging.getLogger(__name__)

STALE_MINUTES = 15
_BJ = timezone(timedelta(hours=8))


class MarketDataService:
    """Handles stock price fetching via yfinance and DB caching."""

    def validate_ticker(self, ticker: str) -> dict | None:
        """Return {name, currency, exchange} or None if invalid."""
        import yfinance as yf

        try:
            tk = yf.Ticker(ticker.upper())
            info = tk.info
            if not info or info.get("regularMarketPrice") is None:
                hist = tk.history(period="5d")
                if hist.empty:
                    return None
                return {
                    "valid": True,
                    "ticker": ticker.upper(),
                    "name": info.get("shortName", ticker.upper()),
                    "currency": info.get("currency", "USD"),
                    "exchange": info.get("exchange", "Unknown"),
                }
            return {
                "valid": True,
                "ticker": ticker.upper(),
                "name": info.get("shortName", ticker.upper()),
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange", "Unknown"),
            }
        except Exception:
            return None

    def fetch_and_save_daily_prices(
        self,
        ticker: str,
        start_date: date,
        end_date: date | None = None,
    ) -> int:
        """Fetch from yfinance and batch upsert into stock_daily_prices."""
        import yfinance as yf

        end_date = end_date or date.today()
        end_fetch = end_date + timedelta(days=1)
        ticker = ticker.upper()

        try:
            tk = yf.Ticker(ticker)
            hist = tk.history(
                start=start_date.isoformat(),
                end=end_fetch.isoformat(),
            )
        except Exception:
            logger.warning("yfinance fetch failed for %s", ticker, exc_info=True)
            return 0

        if hist.empty:
            return 0

        rows_to_insert = []
        last_close: float | None = None
        for idx, row in hist.iterrows():
            trade_dt = idx.date() if hasattr(idx, "date") else idx
            last_close = float(row["Close"])
            rows_to_insert.append(
                (
                    ticker,
                    trade_dt,
                    float(row.get("Open", 0)),
                    float(row.get("High", 0)),
                    float(row.get("Low", 0)),
                    last_close,
                    int(row.get("Volume", 0)),
                )
            )

        if not rows_to_insert:
            return 0

        with get_cursor() as cur:
            for r in rows_to_insert:
                cur.execute(
                    """
                    INSERT INTO stock_daily_prices
                        (ticker_symbol, trade_date,
                         open_price, high_price, low_price,
                         close_price, volume, currency)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'USD')
                    ON DUPLICATE KEY UPDATE
                        open_price = VALUES(open_price),
                        high_price = VALUES(high_price),
                        low_price = VALUES(low_price),
                        close_price = VALUES(close_price),
                        volume = VALUES(volume)
                    """,
                    r,
                )

            # Record update timestamp with daily close as baseline
            cur.execute(
                """
                INSERT INTO price_update_log
                    (ticker_symbol, last_updated_at, last_price,
                     market_state)
                VALUES (%s, NOW(), %s, 'CLOSED')
                ON DUPLICATE KEY UPDATE
                    last_updated_at = NOW(),
                    last_price = VALUES(last_price),
                    market_state = 'CLOSED'
                """,
                (ticker, last_close),
            )

        return len(rows_to_insert)

    def backfill_prices(
        self, ticker: str, from_date: date
    ) -> int:
        """Fetch and store prices from from_date to today."""
        return self.fetch_and_save_daily_prices(
            ticker, from_date, date.today()
        )

    # ── Real-time quote (pre / regular / post market) ──

    def fetch_realtime_quote(self, ticker: str) -> dict | None:
        """Fetch the most current price via yf.Ticker.info.

        Uses yfinance's ``marketState`` field to determine the actual
        market phase, then picks the corresponding price.
        """
        import yfinance as yf

        ticker = ticker.upper()
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception:
            logger.warning(
                "yfinance info failed for %s", ticker, exc_info=True
            )
            return None

        # yfinance reports the real market phase
        yf_state = (info.get("marketState") or "").upper()

        post = info.get("postMarketPrice")
        regular = info.get("regularMarketPrice")
        pre = info.get("preMarketPrice")

        if yf_state == "POST" and post and post > 0:
            price, state = float(post), "POST"
        elif yf_state == "PRE" and pre and pre > 0:
            price, state = float(pre), "PRE"
        elif yf_state == "REGULAR" and regular and regular > 0:
            price, state = float(regular), "REGULAR"
        elif regular and regular > 0:
            # Market closed but regularMarketPrice holds last close
            price, state = float(regular), "CLOSED"
        else:
            return None

        return {"ticker": ticker, "price": price, "market_state": state}

    def _save_realtime_price(
        self, ticker: str, price: float, market_state: str
    ) -> None:
        """Upsert the real-time price into price_update_log."""
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO price_update_log
                    (ticker_symbol, last_updated_at, last_price, market_state)
                VALUES (%s, NOW(), %s, %s)
                ON DUPLICATE KEY UPDATE
                    last_updated_at = NOW(),
                    last_price = VALUES(last_price),
                    market_state = VALUES(market_state)
                """,
                (ticker.upper(), price, market_state),
            )

    # ── Staleness check ────────────────────────────────

    def is_price_stale(
        self, ticker: str, max_age_minutes: int = STALE_MINUTES
    ) -> bool:
        """Return True if the ticker has no update log or is older than max_age_minutes."""
        ticker = ticker.upper()
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT last_updated_at
                FROM price_update_log
                WHERE ticker_symbol = %s
                """,
                (ticker,),
            )
            row = cur.fetchone()

        if not row:
            return True

        # DB returns Beijing time (session tz = +08:00), compare with BJ now
        now_bj = datetime.now(_BJ).replace(tzinfo=None)
        age = now_bj - row["last_updated_at"]
        return age.total_seconds() > max_age_minutes * 60

    # ── Price queries ──────────────────────────────────

    def get_latest_price(self, ticker: str) -> dict | None:
        """Return the best available price with change vs last close.

        Prefers the real-time price from price_update_log when fresh,
        falls back to the daily close from stock_daily_prices.
        Includes change_pct relative to the previous close.
        """
        ticker = ticker.upper()
        with get_cursor() as cur:
            # Get real-time price from update log
            cur.execute(
                """
                SELECT last_price, last_updated_at, market_state
                FROM price_update_log
                WHERE ticker_symbol = %s
                """,
                (ticker,),
            )
            rt = cur.fetchone()

            # Get the two most recent daily closes
            cur.execute(
                """
                SELECT trade_date, close_price
                FROM stock_daily_prices
                WHERE ticker_symbol = %s
                ORDER BY trade_date DESC
                LIMIT 2
                """,
                (ticker,),
            )
            daily_rows = cur.fetchall()

        latest_daily = daily_rows[0] if daily_rows else None
        prev_daily = daily_rows[1] if len(daily_rows) >= 2 else None
        prev_close = (
            float(prev_daily["close_price"]) if prev_daily else None
        )
        latest_close = (
            float(latest_daily["close_price"])
            if latest_daily
            else None
        )

        # Prefer real-time if we have it
        if rt and rt["last_price"]:
            updated_at = rt["last_updated_at"]
            state = rt["market_state"] or "REGULAR"
            state_label = {
                "PRE": "盘前",
                "POST": "盘后",
                "REGULAR": "实时",
                "CLOSED": "收盘",
            }.get(state, state)

            rt_price = float(rt["last_price"])

            # Reference price depends on market state:
            # PRE/REGULAR/POST all compare against the latest daily close
            # CLOSED has no meaningful delta to show
            if state != "CLOSED" and latest_close and latest_close > 0:
                ref_price = latest_close
                ref_label = "收盘"
                change_pct = round(
                    (rt_price - ref_price) / ref_price * 100, 2
                )
            else:
                ref_price = None
                ref_label = None
                change_pct = 0.0

            return {
                "ticker": ticker,
                "price": rt_price,
                "date": (
                    latest_daily["trade_date"].isoformat()
                    if latest_daily
                    else None
                ),
                "currency": "USD",
                "updated_at": (
                    updated_at.strftime("%H:%M")
                    if updated_at
                    else None
                ),
                "market_state": state,
                "market_state_label": state_label,
                "change_pct": change_pct,
                "ref_price": ref_price,
                "ref_label": ref_label,
            }

        # Fallback to daily close
        if latest_daily:
            # Compare today's close vs previous close
            if prev_close and prev_close > 0:
                change_pct = round(
                    (latest_close - prev_close) / prev_close * 100, 2
                )
                ref_price = prev_close
                ref_label = "前收"
            else:
                change_pct = 0.0
                ref_price = None
                ref_label = None

            return {
                "ticker": ticker,
                "price": latest_close,
                "date": latest_daily["trade_date"].isoformat(),
                "currency": "USD",
                "updated_at": None,
                "market_state": "CLOSED",
                "market_state_label": "收盘",
                "change_pct": change_pct,
                "ref_price": ref_price,
                "ref_label": ref_label,
            }
        return None

    def get_close_price_for_date(
        self, ticker: str, trade_date: date
    ) -> Optional[Decimal]:
        """Get close price for a date, fallback to nearest prior."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT close_price FROM stock_daily_prices
                WHERE ticker_symbol = %s AND trade_date <= %s
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (ticker.upper(), trade_date),
            )
            row = cur.fetchone()
        if row:
            return Decimal(str(row["close_price"]))
        return None

    def get_prices_in_range(
        self, ticker: str, start_date: date, end_date: date
    ) -> dict[date, Decimal]:
        """Fetch all stored prices in a date range as {date: price}."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, close_price
                FROM stock_daily_prices
                WHERE ticker_symbol = %s
                  AND trade_date BETWEEN %s AND %s
                ORDER BY trade_date
                """,
                (ticker.upper(), start_date, end_date),
            )
            rows = cur.fetchall()
        return {
            row["trade_date"]: Decimal(str(row["close_price"]))
            for row in rows
        }

    def ensure_prices_current(self, ticker: str) -> None:
        """Refresh prices from yfinance if stale (>15 min since last fetch).

        Two things happen:
        1. Backfill any missing daily close prices (history gaps).
        2. Fetch real-time quote (pre/regular/post market) and save to
           price_update_log for immediate display.
        """
        ticker = ticker.upper()

        if not self.is_price_stale(ticker):
            return

        # 1. Backfill daily close prices for any gap days
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(trade_date) AS last_date
                FROM stock_daily_prices
                WHERE ticker_symbol = %s
                """,
                (ticker,),
            )
            row = cur.fetchone()

        last_date = row["last_date"] if row else None
        today = date.today()

        if last_date is None:
            self.backfill_prices(ticker, today - timedelta(days=365))
        elif last_date < today:
            self.fetch_and_save_daily_prices(
                ticker, last_date + timedelta(days=1), today
            )

        # 2. Fetch real-time quote (includes pre/post market)
        quote = self.fetch_realtime_quote(ticker)
        if quote:
            self._save_realtime_price(
                ticker, quote["price"], quote["market_state"]
            )
