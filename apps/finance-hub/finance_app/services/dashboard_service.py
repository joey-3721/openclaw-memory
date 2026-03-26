"""Dashboard service — widget management and data aggregation."""

from __future__ import annotations

import json
import logging
from time import perf_counter

from ..db import get_cursor
from .exchange_rate_service import ExchangeRateService
from .snapshot_service import SnapshotService
from .asset_service import AssetService

logger = logging.getLogger(__name__)


class DashboardService:
    """Manage dashboard widget templates, user layouts, and data."""

    def __init__(self) -> None:
        self._snapshot = SnapshotService()
        self._fx = ExchangeRateService()
        self._assets = AssetService()
        self._latest_snapshot_cache: dict[int, dict | None] = {}
        self._latest_rate_cache: dict[int, dict | None] = {}
        self._snapshot_bundle_cache: dict[int, dict] = {}
        self._performance_summary_cache: dict[int, dict] = {}
        self._dashboard_assets_cache: dict[int, list[dict]] = {}
        self._dashboard_assets_summary_cache: dict[int, dict] = {}

    # ── Widget Templates ──────────────────────────────────

    def get_widget_templates(self) -> list[dict]:
        """Return all active widget templates."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, widget_type, display_name, description,
                       default_config, min_width, min_height,
                       component_template, display_order
                FROM dashboard_widget_templates
                WHERE is_active = 1
                ORDER BY display_order
                """
            )
            rows = cur.fetchall()
        for row in rows:
            if isinstance(row["default_config"], str):
                row["default_config"] = json.loads(
                    row["default_config"]
                )
        return rows

    # ── User Layout ───────────────────────────────────────

    def get_user_layout(self, user_id: int) -> list[dict]:
        """Return user's widget layout with template info."""
        self._ensure_layout_rows(user_id)
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT udl.id, udl.sort_order, udl.width,
                       udl.custom_config, udl.is_visible,
                       dwt.widget_type, dwt.display_name,
                       dwt.description,
                       dwt.component_template, dwt.default_config
                FROM user_dashboard_layouts udl
                JOIN dashboard_widget_templates dwt
                    ON udl.widget_template_id = dwt.id
                WHERE udl.user_id = %s
                ORDER BY udl.sort_order
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        return [self._normalize_layout_row(row) for row in rows]

    def _normalize_layout_row(self, row: dict) -> dict:
        """Coerce JSON fields into Python objects for one layout row."""
        for key in ("custom_config", "default_config"):
            if isinstance(row[key], str):
                row[key] = json.loads(row[key])
            elif row[key] is None:
                row[key] = {}
        return row

    def _ensure_layout_rows(self, user_id: int) -> None:
        """Ensure existing users get rows for any newly added widgets."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM user_dashboard_layouts
                WHERE user_id = %s
                """,
                (user_id,),
            )
            if cur.fetchone()["cnt"] == 0:
                self._create_default_layout(user_id)
                return

            cur.execute(
                """
                SELECT widget_template_id
                FROM user_dashboard_layouts
                WHERE user_id = %s
                """,
                (user_id,),
            )
            existing_template_ids = {
                row["widget_template_id"] for row in cur.fetchall()
            }

            cur.execute(
                """
                SELECT id, min_width
                FROM dashboard_widget_templates
                WHERE is_active = 1
                ORDER BY display_order
                """
            )
            templates = cur.fetchall()

            cur.execute(
                """
                SELECT COALESCE(MAX(sort_order), -1) AS max_sort
                FROM user_dashboard_layouts
                WHERE user_id = %s
                """,
                (user_id,),
            )
            next_sort_order = cur.fetchone()["max_sort"] + 1

            for tpl in templates:
                if tpl["id"] in existing_template_ids:
                    continue
                cur.execute(
                    """
                    INSERT INTO user_dashboard_layouts
                        (user_id, widget_template_id, sort_order,
                         width, is_visible)
                    VALUES (%s, %s, %s, %s, 0)
                    """,
                    (
                        user_id,
                        tpl["id"],
                        next_sort_order,
                        tpl["min_width"],
                    ),
                )
                next_sort_order += 1

    def _create_default_layout(self, user_id: int) -> None:
        """Create default layout with all widgets visible."""
        templates = self.get_widget_templates()
        with get_cursor() as cur:
            for i, tpl in enumerate(templates):
                cur.execute(
                    """
                    INSERT INTO user_dashboard_layouts
                        (user_id, widget_template_id, sort_order,
                         width, is_visible)
                    VALUES (%s, %s, %s, %s, 1)
                    """,
                    (user_id, tpl["id"], i, tpl["min_width"]),
                )

    def save_layout(
        self, user_id: int, layout: list[dict]
    ) -> None:
        """Bulk update sort_order + is_visible for user's widgets."""
        with get_cursor() as cur:
            for item in layout:
                cur.execute(
                    """
                    UPDATE user_dashboard_layouts
                    SET sort_order = %s, is_visible = %s
                    WHERE id = %s AND user_id = %s
                    """,
                    (
                        item["sort_order"],
                        item.get("is_visible", 1),
                        item["id"],
                        user_id,
                    ),
                )

    def get_layout_item(
        self, user_id: int, layout_id: int
    ) -> dict | None:
        """Return one layout item for the current user."""
        for item in self.get_user_layout(user_id):
            if item["id"] == layout_id:
                return item
        return None

    def serialize_layout(self, layout: list[dict]) -> str:
        """Serialize layout rows for frontend hydration."""
        return json.dumps(
            [
                {
                    "id": item["id"],
                    "widget_type": item["widget_type"],
                    "display_name": item["display_name"],
                    "description": item.get("description", ""),
                    "component_template": item["component_template"],
                    "sort_order": item["sort_order"],
                    "width": item["width"],
                    "is_visible": item["is_visible"],
                }
                for item in layout
            ],
            ensure_ascii=False,
        )

    def build_widget_payload(
        self, user_id: int, layout_item: dict, data: dict | None = None
    ) -> dict:
        """Build the payload needed to render or hydrate one widget."""
        return {
            "id": layout_item["id"],
            "widget_type": layout_item["widget_type"],
            "display_name": layout_item["display_name"],
            "description": layout_item.get("description", ""),
            "component_template": layout_item["component_template"],
            "sort_order": layout_item["sort_order"],
            "width": layout_item["width"],
            "is_visible": layout_item["is_visible"],
            "data": (
                data
                if data is not None
                else self.get_widget_data(
                    user_id, layout_item["widget_type"]
                )
            ),
        }

    # ── Widget Data ───────────────────────────────────────

    def get_widget_data(
        self, user_id: int, widget_type: str
    ) -> dict:
        """Dispatch to appropriate data-fetcher by widget_type."""
        dispatch = {
            "total_assets": self._data_total_assets,
            "trend_chart": self._data_trend_chart,
            "allocation_pie": self._data_allocation_pie,
            "daily_pnl": self._data_daily_pnl,
            "total_pnl": self._data_total_pnl,
            "realized_pnl": self._data_realized_pnl,
            "unrealized_pnl": self._data_unrealized_pnl,
            "income_pnl": self._data_income_pnl,
            "exchange_rate": self._data_exchange_rate,
            "asset_list": self._data_asset_list,
        }
        handler = dispatch.get(widget_type)
        if handler:
            try:
                return handler(user_id)
            except Exception:
                return {"error": True}
        return {}

    def _data_total_assets(self, user_id: int) -> dict:
        summary = self._get_dashboard_assets_summary_cached(user_id)
        if not summary:
            return {
                "total_cny": 0,
                "change_cny": 0,
                "change_pct": 0,
            }
        return {
            "label": "资产总值 (CNY)",
            "value_cny": summary["total_cny"],
            "subvalue": None,
            "tone": "neutral",
        }

    def _data_trend_chart(self, user_id: int) -> dict:
        trend = self._get_snapshot_bundle_cached(user_id)["trend"]
        return {
            "labels": [t["date"] for t in trend],
            "values": [t["total_cny"] for t in trend],
            "stock": [t["stock_cny"] for t in trend],
            "bond": [t["bond_cny"] for t in trend],
            "cash": [t["cash_cny"] for t in trend],
        }

    def _data_allocation_pie(self, user_id: int) -> dict:
        snap = self._get_latest_snapshot_cached(user_id)
        if not snap:
            return {"items": []}
        total = snap["total_cny"] or 1
        items = []
        for code, name, val, color in [
            ("STOCK", "股票", snap["stock_cny"], "#4f8df6"),
            ("BOND", "债券", snap["bond_cny"], "#8b5cf6"),
            ("CASH", "现金", snap["cash_cny"], "#15b79e"),
        ]:
            if val > 0:
                items.append(
                    {
                        "type_code": code,
                        "type_name": name,
                        "value_cny": val,
                        "pct": round(val / total * 100, 1),
                        "color": color,
                    }
                )
        return {"items": items}

    def _data_daily_pnl(self, user_id: int) -> dict:
        summary = self._get_dashboard_assets_summary_cached(user_id)
        if not summary:
            return {"change_cny": 0, "change_pct": 0}
        return {
            "label": "今日变化",
            "value_cny": summary.get("daily_change_cny", 0),
            "subvalue": summary.get("daily_change_pct", 0),
            "tone": "signed",
        }

    def _data_total_pnl(self, user_id: int) -> dict:
        summary = self._get_performance_summary_cached(user_id)
        return {
            "label": "总盈亏",
            "value_cny": summary.get("total_pnl_cny", 0),
            "subvalue": summary.get("total_return_pct", 0),
            "tone": "signed",
        }

    def _data_realized_pnl(self, user_id: int) -> dict:
        summary = self._get_performance_summary_cached(user_id)
        return {
            "label": "已实现盈亏",
            "value_cny": summary.get("realized_pnl_cny", 0),
            "subvalue": None,
            "tone": "signed",
        }

    def _data_unrealized_pnl(self, user_id: int) -> dict:
        summary = self._get_performance_summary_cached(user_id)
        return {
            "label": "未实现盈亏",
            "value_cny": summary.get("unrealized_pnl_cny", 0),
            "subvalue": None,
            "tone": "signed",
        }

    def _data_income_pnl(self, user_id: int) -> dict:
        summary = self._get_performance_summary_cached(user_id)
        return {
            "label": "累计分红/利息",
            "value_cny": summary.get("income_pnl_cny", 0),
            "subvalue": None,
            "tone": "signed",
        }

    def _data_exchange_rate(self, user_id: int) -> dict:
        rate_info = self._get_latest_rate_cached(user_id)
        if not rate_info:
            return {"rate": 0, "date": ""}
        return rate_info

    def _data_asset_list(self, user_id: int) -> dict:
        return {"assets": self._get_dashboard_assets_cached(user_id)}

    def _get_dashboard_assets_cached(self, user_id: int) -> list[dict]:
        """Reuse dashboard asset list across widgets and async hydration."""
        if user_id not in self._dashboard_assets_cache:
            self._dashboard_assets_cache[user_id] = (
                self._assets.get_dashboard_assets(user_id)
            )
        return self._dashboard_assets_cache[user_id]

    def _get_dashboard_assets_summary_cached(self, user_id: int) -> dict:
        """Derive lightweight headline cards from dashboard asset rows."""
        if user_id not in self._dashboard_assets_summary_cache:
            assets = self._get_dashboard_assets_cached(user_id)
            total_cny = sum(
                asset.get("value_cny", 0.0) for asset in assets
            )
            daily_change_cny = sum(
                asset.get("change_cny", 0.0) for asset in assets
            )
            prev_total = total_cny - daily_change_cny
            daily_change_pct = (
                (daily_change_cny / prev_total * 100)
                if prev_total
                else 0.0
            )
            self._dashboard_assets_summary_cache[user_id] = {
                "total_cny": round(total_cny, 2),
                "daily_change_cny": round(daily_change_cny, 2),
                "daily_change_pct": round(daily_change_pct, 2),
            }
        return self._dashboard_assets_summary_cache[user_id]

    def _get_latest_snapshot_cached(self, user_id: int) -> dict | None:
        """Reuse the latest snapshot across multiple dashboard widgets."""
        if user_id not in self._latest_snapshot_cache:
            self._latest_snapshot_cache[user_id] = self._get_snapshot_bundle_cached(
                user_id
            ).get("latest_snapshot")
        return self._latest_snapshot_cache[user_id]

    def _get_snapshot_bundle_cached(self, user_id: int) -> dict:
        """Reuse shared snapshot queries across dashboard widgets."""
        if user_id not in self._snapshot_bundle_cache:
            self._snapshot_bundle_cache[user_id] = (
                self._snapshot.get_dashboard_snapshot_bundle(
                    user_id, range_value=30
                )
            )
        return self._snapshot_bundle_cache[user_id]

    def _get_latest_rate_cached(self, user_id: int) -> dict | None:
        """Reuse exchange-rate payload across multiple dashboard widgets."""
        if user_id not in self._latest_rate_cache:
            latest_snapshot = self._get_latest_snapshot_cached(user_id)
            if latest_snapshot and latest_snapshot.get("exchange_rate"):
                self._latest_rate_cache[user_id] = {
                    "from": self._fx.FROM_CURRENCY,
                    "to": self._fx.TO_CURRENCY,
                    "rate": latest_snapshot["exchange_rate"],
                    "date": latest_snapshot["date"],
                }
            else:
                self._latest_rate_cache[user_id] = self._fx.get_latest_rate()
        return self._latest_rate_cache[user_id]

    def _get_performance_summary_cached(self, user_id: int) -> dict:
        """Reuse asset-page performance summary across dashboard widgets."""
        if user_id not in self._performance_summary_cache:
            self._performance_summary_cache[user_id] = (
                self._snapshot.get_performance_summary(user_id)
            )
        return self._performance_summary_cache[user_id]

    # ── Full Dashboard Load ───────────────────────────────

    def load_dashboard_data(self, user_id: int) -> dict:
        """Load all widget layout and data for the dashboard page."""
        started_at = perf_counter()
        layout = self.get_user_layout(user_id)

        visible_widgets = [
            widget for widget in layout if widget["is_visible"]
        ]
        widgets = []
        dashboard_data = {}
        for widget in visible_widgets:
            wtype = widget["widget_type"]
            widget_started_at = perf_counter()
            data = self.get_widget_data(user_id, wtype)
            print(
                "PERF dashboard widget",
                {
                    "user_id": user_id,
                    "widget": wtype,
                    "duration_ms": round(
                        (perf_counter() - widget_started_at) * 1000, 1
                    ),
                },
                flush=True,
            )
            widgets.append(
                self.build_widget_payload(
                    user_id, widget, data=data
                )
            )
            dashboard_data[wtype] = data

        result = {
            "widgets": widgets,
            "dashboard_data_json": json.dumps(
                dashboard_data, ensure_ascii=False
            ),
            "dashboard_layout_json": self.serialize_layout(layout),
        }
        print(
            "PERF dashboard load",
            {
                "user_id": user_id,
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000, 1
                ),
                "widget_count": len(widgets),
            },
            flush=True,
        )
        return result
