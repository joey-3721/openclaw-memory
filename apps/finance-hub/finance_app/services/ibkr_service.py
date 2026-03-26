"""IBKR Flex Web Service sync helpers."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import requests

from ..db import get_cursor
from .asset_service import AssetService
from .snapshot_service import SnapshotService


class IBKRSyncService:
    """Sync IBKR Flex Query data into local asset tables."""

    BASE_URL = (
        "https://ndcdyn.interactivebrokers.com/"
        "AccountManagement/FlexWebService"
    )
    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
    MANUAL_COOLDOWN = timedelta(hours=1)

    def __init__(self) -> None:
        self._assets = AssetService()
        self._snapshots = SnapshotService()

    def sync_user(self, user_id: int, force: bool = False) -> dict:
        """Run a two-step IBKR Flex sync for one user."""
        config = self._get_config(user_id)
        if not config:
            return {
                "ok": False,
                "skipped": True,
                "reason": "missing_config",
            }
        if not config["is_enabled"]:
            return {
                "ok": False,
                "skipped": True,
                "reason": "disabled",
            }
        if self._is_within_manual_cooldown(
            config["last_synced_at"]
        ):
            status = self.get_sync_status(user_id)
            return {
                "ok": True,
                "skipped": True,
                "reason": "cooldown",
                "last_synced_at": status["last_synced_at_iso"],
                "next_allowed_at": status["next_allowed_at_iso"],
            }
        if not force and not self._should_sync_now(
            config["last_synced_at"]
        ):
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_synced_after_noon",
            }

        xml_text = self._fetch_statement_xml(
            config["flex_query_id"], config["flex_token"]
        )
        parsed = self._parse_statement(xml_text)
        result = self._import_events(user_id, parsed)

        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE ibkr_flex_configs
                SET last_synced_at = %s,
                    last_imported_to = %s
                WHERE user_id = %s
                """,
                (
                    datetime.now(self.SHANGHAI_TZ).replace(tzinfo=None),
                    parsed.get("statement_to"),
                    user_id,
                ),
            )

        if result["earliest_effective_date"]:
            self._snapshots.refresh_snapshots_from_date(
                user_id, result["earliest_effective_date"]
            )

        return {
            "ok": True,
            "skipped": False,
            "statement_to": (
                parsed["statement_to"].isoformat()
                if parsed.get("statement_to")
                else None
            ),
            "events_seen": result["events_seen"],
            "events_inserted": result["events_inserted"],
            "trades_inserted": result["trades_inserted"],
            "cash_flows_inserted": result["cash_flows_inserted"],
            "assets_created": result["assets_created"],
        }

    def get_sync_status(self, user_id: int) -> dict:
        """Return current IBKR sync availability for the user."""
        config = self._get_config(user_id)
        last_synced_at = (
            config.get("last_synced_at") if config else None
        )
        token_expires_at = (
            config.get("token_expires_at") if config else None
        )
        next_allowed_at = None
        can_sync = True
        if last_synced_at:
            next_allowed_at = (
                last_synced_at.replace(tzinfo=self.SHANGHAI_TZ)
                + self.MANUAL_COOLDOWN
            )
            can_sync = (
                datetime.now(self.SHANGHAI_TZ) >= next_allowed_at
            )
        today = datetime.now(self.SHANGHAI_TZ).date()
        return {
            "has_config": bool(config),
            "is_enabled": bool(config and config["is_enabled"]),
            "flex_query_id": (
                config.get("flex_query_id") if config else None
            ),
            "last_synced_at_iso": (
                last_synced_at.isoformat()
                if last_synced_at
                else None
            ),
            "last_synced_at_display": (
                last_synced_at.strftime("%Y-%m-%d %H:%M")
                if last_synced_at
                else "尚未同步"
            ),
            "next_allowed_at_iso": (
                next_allowed_at.isoformat()
                if next_allowed_at
                else None
            ),
            "token_expires_at_iso": (
                token_expires_at.isoformat()
                if token_expires_at
                else None
            ),
            "token_expires_at_display": (
                token_expires_at.strftime("%Y-%m-%d")
                if token_expires_at
                else "未设置"
            ),
            "token_is_expired": bool(
                token_expires_at and token_expires_at < today
            ),
            "can_manual_sync": can_sync and bool(config),
        }

    def get_settings_config(self, user_id: int) -> dict:
        """Return IBKR settings payload for the settings page."""
        config = self._get_config(user_id)
        status = self.get_sync_status(user_id)
        return {
            "has_config": bool(config),
            "is_enabled": bool(config and config["is_enabled"]),
            "query_name": (
                config.get("query_name") if config else None
            ),
            "flex_query_id": (
                config.get("flex_query_id") if config else ""
            ),
            "token_expires_at": status["token_expires_at_iso"] or "",
            "token_expires_at_display": status[
                "token_expires_at_display"
            ],
            "token_is_expired": status["token_is_expired"],
            "last_synced_at_display": status["last_synced_at_display"],
            "last_imported_to_display": (
                config["last_imported_to"].strftime("%Y-%m-%d")
                if config and config.get("last_imported_to")
                else "尚未导入"
            ),
        }

    def save_settings_config(
        self,
        user_id: int,
        flex_query_id: str,
        token: str | None,
        token_expires_at: date | None,
        is_enabled: bool,
    ) -> None:
        """Insert or update one user's IBKR settings."""
        config = self._get_config(user_id)
        token_value = token or (
            config.get("flex_token") if config else None
        )
        if not token_value:
            raise ValueError("请输入 IBKR Token")
        if not flex_query_id:
            raise ValueError("请输入 Flex Query ID")

        expires_at = token_expires_at or (
            config.get("token_expires_at") if config else None
        )
        if not expires_at:
            expires_at = datetime.now(self.SHANGHAI_TZ).date() + timedelta(days=365)

        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO ibkr_flex_configs
                    (user_id, flex_query_id, flex_token, token_expires_at,
                     is_enabled)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    flex_query_id = VALUES(flex_query_id),
                    flex_token = VALUES(flex_token),
                    token_expires_at = VALUES(token_expires_at),
                    is_enabled = VALUES(is_enabled)
                """,
                (
                    user_id,
                    flex_query_id.strip(),
                    token_value.strip(),
                    expires_at,
                    1 if is_enabled else 0,
                ),
            )

    def _get_config(self, user_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT user_id, flex_query_id, flex_token,
                       token_expires_at, query_name,
                       is_enabled, last_synced_at, last_imported_to
                FROM ibkr_flex_configs
                WHERE user_id = %s
                """,
                (user_id,),
            )
            return cur.fetchone()

    def _is_within_manual_cooldown(
        self, last_synced_at: datetime | None
    ) -> bool:
        if not last_synced_at:
            return False
        last_sync = last_synced_at.replace(tzinfo=self.SHANGHAI_TZ)
        return (
            datetime.now(self.SHANGHAI_TZ) - last_sync
            < self.MANUAL_COOLDOWN
        )

    def _should_sync_now(self, last_synced_at: datetime | None) -> bool:
        """Only auto-sync once per Beijing day after 12:00."""
        now = datetime.now(self.SHANGHAI_TZ)
        today_noon = datetime.combine(
            now.date(), time(hour=12), tzinfo=self.SHANGHAI_TZ
        )
        if now < today_noon:
            return False
        if not last_synced_at:
            return True
        last_sync = last_synced_at.replace(tzinfo=self.SHANGHAI_TZ)
        return last_sync < today_noon

    def _fetch_statement_xml(
        self, query_id: str, token: str
    ) -> str:
        headers = {"User-Agent": "finance-hub/0.1"}
        send_resp = requests.get(
            f"{self.BASE_URL}/SendRequest",
            params={"t": token, "q": query_id, "v": "3"},
            headers=headers,
            timeout=30,
        )
        send_resp.raise_for_status()

        root = ET.fromstring(send_resp.text)
        status = root.findtext("Status")
        if status != "Success":
            raise RuntimeError(
                root.findtext("ErrorMessage")
                or "IBKR SendRequest failed"
            )

        reference_code = root.findtext("ReferenceCode")
        if not reference_code:
            raise RuntimeError("IBKR ReferenceCode missing")

        statement_resp = requests.get(
            f"{self.BASE_URL}/GetStatement",
            params={"t": token, "q": reference_code, "v": "3"},
            headers=headers,
            timeout=30,
            allow_redirects=True,
        )
        statement_resp.raise_for_status()
        return statement_resp.text

    def _parse_statement(self, xml_text: str) -> dict:
        root = ET.fromstring(xml_text)
        statement = root.find("./FlexStatements/FlexStatement")
        trades = []
        cash_transactions = []
        statement_to = None

        if statement is not None and statement.get("toDate"):
            statement_to = date.fromisoformat(
                self._normalize_date(statement.get("toDate"))
            )

        trade_root = root.find(".//Trades")
        if trade_root is not None:
            for item in trade_root.findall("Trade"):
                trades.append(dict(item.attrib))

        cash_root = root.find(".//CashTransactions")
        if cash_root is not None:
            for item in cash_root.findall("CashTransaction"):
                cash_transactions.append(dict(item.attrib))

        return {
            "statement_to": statement_to,
            "trades": trades,
            "cash_transactions": cash_transactions,
        }

    def _import_events(self, user_id: int, parsed: dict) -> dict:
        asset_cache: dict[tuple[str, str], int | None] = {}
        earliest_effective_date: date | None = None
        assets_created = 0
        events_seen = 0
        events_inserted = 0
        trades_inserted = 0
        cash_flows_inserted = 0

        for trade in parsed["trades"]:
            events_seen += 1
            trade_date = date.fromisoformat(
                self._normalize_date(trade["tradeDate"])
            )
            normalized_type = (
                "BUY"
                if trade.get("buySell", "").upper() == "BUY"
                else "SELL"
            )
            source_hash = self._build_event_hash(
                user_id, "TRADE", trade
            )
            inserted = self._insert_raw_event(
                user_id=user_id,
                event_kind="TRADE",
                normalized_type=normalized_type,
                symbol=trade.get("symbol"),
                description=trade.get("description"),
                event_at=datetime.combine(trade_date, time.min),
                currency=trade.get("currency", "USD"),
                quantity=trade.get("quantity"),
                price_per_unit=trade.get("tradePrice"),
                amount=trade.get("netCash"),
                commission=trade.get("ibCommission"),
                raw_type=trade.get("buySell"),
                raw_payload=trade,
                source_hash=source_hash,
            )
            if not inserted:
                continue

            events_inserted += 1
            asset_id, created = self._resolve_asset_for_symbol(
                user_id=user_id,
                symbol=trade.get("symbol"),
                description=trade.get("description"),
                currency=trade.get("currency", "USD"),
                cache=asset_cache,
            )
            if created:
                assets_created += 1

            if asset_id is None:
                continue

            quantity = abs(Decimal(str(trade["quantity"])))
            price_per_unit = Decimal(str(trade["tradePrice"]))
            fee = abs(Decimal(str(trade.get("ibCommission") or "0")))
            asset = self._assets._get_asset_for_sync(asset_id)
            asset_type_code = (
                asset["type_code"] if asset else "STOCK"
            )
            total_amount = (
                self._assets._calculate_transaction_total_amount(
                    asset_type_code, quantity, price_per_unit
                )
            )

            with get_cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM asset_transactions
                    WHERE user_asset_id = %s
                      AND direction = %s
                      AND transaction_date = %s
                      AND quantity = %s
                      AND price_per_unit = %s
                    LIMIT 1
                    """,
                    (
                        asset_id,
                        normalized_type,
                        trade_date,
                        str(quantity),
                        str(price_per_unit),
                    ),
                )
                if cur.fetchone():
                    continue

                cur.execute(
                    """
                    INSERT INTO asset_transactions
                        (user_asset_id, direction, quantity,
                         price_per_unit, total_amount, fee,
                         transaction_date, source_system, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'IBKR', %s)
                    """,
                    (
                        asset_id,
                        normalized_type,
                        str(quantity),
                        str(price_per_unit),
                        str(total_amount),
                        str(fee),
                        trade_date,
                        "IBKR 自动导入",
                    ),
                )
            trades_inserted += 1
            earliest_effective_date = self._min_date(
                earliest_effective_date, trade_date
            )

        for cash_flow in parsed["cash_transactions"]:
            events_seen += 1
            normalized_type = self._normalize_cash_type(cash_flow)
            flow_dt = self._parse_ibkr_datetime(
                cash_flow.get("dateTime") or ""
            )
            source_hash = self._build_event_hash(
                user_id, "CASH", cash_flow
            )
            inserted = self._insert_raw_event(
                user_id=user_id,
                event_kind="CASH",
                normalized_type=normalized_type,
                symbol=cash_flow.get("symbol"),
                description=cash_flow.get("description"),
                event_at=flow_dt,
                currency=cash_flow.get("currency", "USD"),
                quantity=None,
                price_per_unit=None,
                amount=cash_flow.get("amount"),
                commission=None,
                raw_type=cash_flow.get("type"),
                raw_payload=cash_flow,
                source_hash=source_hash,
            )
            if not inserted:
                continue

            events_inserted += 1
            if normalized_type not in {
                "DISTRIBUTION",
                "WITHHOLDING_TAX",
            }:
                continue

            asset_id, created = self._resolve_asset_for_symbol(
                user_id=user_id,
                symbol=cash_flow.get("symbol"),
                description=cash_flow.get("description"),
                currency=cash_flow.get("currency", "USD"),
                cache=asset_cache,
            )
            if created:
                assets_created += 1
            if asset_id is None:
                continue

            with get_cursor() as cur:
                cur.execute(
                    """
                    SELECT id
                    FROM asset_cash_flows
                    WHERE user_asset_id = %s
                      AND flow_type = %s
                      AND flow_date = %s
                      AND amount = %s
                      AND COALESCE(description, '') = %s
                    LIMIT 1
                    """,
                    (
                        asset_id,
                        normalized_type,
                        flow_dt.date(),
                        str(Decimal(str(cash_flow["amount"]))),
                        cash_flow.get("description") or "",
                    ),
                )
                if cur.fetchone():
                    continue

                cur.execute(
                    """
                    INSERT INTO asset_cash_flows
                        (user_asset_id, flow_type, amount, flow_date,
                         description, source_system, source_hash)
                    VALUES (%s, %s, %s, %s, %s, 'IBKR', %s)
                    """,
                    (
                        asset_id,
                        normalized_type,
                        str(Decimal(str(cash_flow["amount"]))),
                        flow_dt.date(),
                        cash_flow.get("description"),
                        source_hash,
                    ),
                )
            cash_flows_inserted += 1
            earliest_effective_date = self._min_date(
                earliest_effective_date, flow_dt.date()
            )

        if earliest_effective_date:
            self._backfill_supporting_data(user_id, earliest_effective_date)

        return {
            "events_seen": events_seen,
            "events_inserted": events_inserted,
            "trades_inserted": trades_inserted,
            "cash_flows_inserted": cash_flows_inserted,
            "assets_created": assets_created,
            "earliest_effective_date": earliest_effective_date,
        }

    def _insert_raw_event(self, **kwargs) -> bool:
        """Insert one raw IBKR event; return False when it already exists."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM ibkr_flex_events WHERE source_hash = %s",
                (kwargs["source_hash"],),
            )
            if cur.fetchone():
                return False

            cur.execute(
                """
                INSERT INTO ibkr_flex_events
                    (user_id, event_kind, normalized_type, symbol,
                     description, event_at, currency, quantity,
                     price_per_unit, amount, commission, raw_type,
                     raw_payload, source_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s)
                """,
                (
                    kwargs["user_id"],
                    kwargs["event_kind"],
                    kwargs["normalized_type"],
                    kwargs["symbol"],
                    kwargs["description"],
                    kwargs["event_at"],
                    kwargs["currency"],
                    kwargs["quantity"],
                    kwargs["price_per_unit"],
                    kwargs["amount"],
                    kwargs["commission"],
                    kwargs["raw_type"],
                    json.dumps(kwargs["raw_payload"], ensure_ascii=False),
                    kwargs["source_hash"],
                ),
            )
        return True

    def _resolve_asset_for_symbol(
        self,
        user_id: int,
        symbol: str | None,
        description: str | None,
        currency: str,
        cache: dict[tuple[str, str], int | None],
    ) -> tuple[int | None, bool]:
        symbol = (symbol or "").strip().upper()
        description = (description or "").strip()
        cache_key = (symbol, description)
        if cache_key in cache:
            return cache[cache_key], False

        if not symbol or self._should_ignore_symbol(symbol, description):
            cache[cache_key] = None
            return None, False

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT ua.id
                FROM user_assets ua
                WHERE ua.user_id = %s
                  AND ua.is_active = 1
                  AND ua.ticker_symbol = %s
                LIMIT 1
                """,
                (user_id, symbol),
            )
            row = cur.fetchone()
            if row:
                cache[cache_key] = row["id"]
                return row["id"], False

        type_code = self._guess_asset_type(symbol, description)
        asset_type = self._assets._get_asset_type_by_code(type_code)
        if not asset_type:
            cache[cache_key] = None
            return None, False

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
                    symbol,
                    description or symbol,
                    currency or asset_type.get("currency", "USD"),
                ),
            )
            asset_id = cur.lastrowid

        cache[cache_key] = asset_id
        return asset_id, True

    def _should_ignore_symbol(
        self, symbol: str, description: str
    ) -> bool:
        if symbol.startswith("USD.") or symbol.endswith(".CNH"):
            return True
        if symbol.endswith(".HKD"):
            return True
        if symbol.startswith("CBBTC_"):
            return True
        return False

    def _guess_asset_type(
        self, symbol: str, description: str
    ) -> str:
        if description.startswith("T ") or symbol.startswith("T "):
            return "BOND"
        return "STOCK"

    def _normalize_cash_type(self, cash_flow: dict) -> str:
        raw_type = (cash_flow.get("type") or "").strip()
        amount = Decimal(str(cash_flow.get("amount") or "0"))
        if raw_type == "Dividends":
            return "DISTRIBUTION"
        if raw_type == "Withholding Tax":
            return "WITHHOLDING_TAX"
        if raw_type == "Broker Interest Received":
            return "BROKER_INTEREST"
        if raw_type == "Deposits/Withdrawals":
            return "DEPOSIT" if amount >= 0 else "WITHDRAWAL"
        return "IGNORED"

    def _parse_ibkr_datetime(self, raw: str) -> datetime:
        if ";" in raw:
            dt = datetime.strptime(raw, "%Y%m%d;%H%M%S")
        else:
            dt = datetime.strptime(raw, "%Y%m%d")
        return dt

    def _normalize_date(self, raw: str) -> str:
        if "-" in raw:
            return raw
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()

    def _build_event_hash(
        self, user_id: int, event_kind: str, payload: dict
    ) -> str:
        normalized = json.dumps(
            {
                "user_id": user_id,
                "event_kind": event_kind,
                "payload": payload,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _backfill_supporting_data(
        self, user_id: int, from_date: date
    ) -> None:
        assets = self._assets.get_user_assets(user_id)
        for asset in assets:
            if asset["type_code"] not in {"STOCK", "BOND"}:
                continue
            self._assets._sync_supporting_data_from_date(
                asset,
                asset.get("ticker_symbol"),
                from_date,
            )

    def _min_date(
        self, current: date | None, candidate: date
    ) -> date:
        if current is None:
            return candidate
        return min(current, candidate)
