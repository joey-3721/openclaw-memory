"""JSON API endpoints for assets, market data, dashboard."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from ..services.auth import get_current_user

router = APIRouter(prefix="/api")


def _require_user(request: Request) -> dict | None:
    """Return current user or None."""
    return get_current_user(request)


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "未登录"}, status_code=401)


def _render_dashboard_widget(request: Request, widget: dict) -> str:
    """Render one dashboard widget card into HTML."""
    templates = request.app.state.templates
    template = templates.env.get_template(
        "partials/dashboard_widget_card.html"
    )
    return template.render({"request": request, "widget": widget})


def _queue_snapshot_refresh(
    background_tasks: BackgroundTasks, user_id: int, from_date: date
) -> None:
    """Backfill snapshots after the response returns."""
    from ..services.snapshot_service import SnapshotService

    background_tasks.add_task(
        SnapshotService().refresh_snapshots_from_date,
        user_id,
        from_date,
    )


# ── Assets ────────────────────────────────────────────────


@router.get("/assets")
def list_assets(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    assets = svc.get_user_assets_with_values(user["id"])
    return JSONResponse({"assets": assets})


@router.get("/dashboard/asset-list-live")
def dashboard_asset_list_live(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService
    from ..services.market_data_service import MarketDataService

    asset_svc = AssetService()
    market_svc = MarketDataService()
    assets = asset_svc.get_user_assets(user["id"])
    seen_tickers = set()
    for asset in assets:
        ticker = asset.get("ticker_symbol")
        if (
            asset.get("has_market_price")
            and ticker
            and ticker not in seen_tickers
        ):
            seen_tickers.add(ticker)
            market_svc.ensure_prices_current(ticker)

    return JSONResponse(
        {
            "assets": asset_svc.get_dashboard_assets(user["id"]),
            "refreshed": True,
        }
    )


@router.post("/assets")
async def create_asset(
    request: Request, background_tasks: BackgroundTasks
):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    data = await request.json()
    from ..services.asset_service import AssetService

    svc = AssetService()
    try:
        asset_id = svc.create_asset(user["id"], data)
        buy_date = data.get("buy_date") or date.today().isoformat()
        _queue_snapshot_refresh(
            background_tasks, user["id"], date.fromisoformat(buy_date)
        )
        return JSONResponse(
            {"id": asset_id, "message": "资产已添加"},
            status_code=201,
        )
    except ValueError as e:
        return JSONResponse(
            {"error": str(e)}, status_code=400
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"创建失败: {e}"}, status_code=500
        )


@router.get("/assets/summary")
def assets_summary(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.snapshot_service import SnapshotService

    svc = SnapshotService()
    snap = svc.get_latest_snapshot(user["id"])
    if snap:
        return JSONResponse(snap)
    return JSONResponse(
        {
            "total_cny": 0,
            "stock_cny": 0,
            "bond_cny": 0,
            "cash_cny": 0,
        }
    )


@router.get("/assets/daily-values")
def daily_values(request: Request, days: str = "30"):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.snapshot_service import SnapshotService

    svc = SnapshotService()
    data = svc.get_trend_data(user["id"], range_value=days)
    return JSONResponse({"values": data})


@router.get("/snapshots/rebuild-status")
def snapshot_rebuild_status(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.snapshot_service import SnapshotService

    svc = SnapshotService()
    return JSONResponse(svc.get_rebuild_status(user["id"]))


@router.post("/snapshots/rebuild")
def rebuild_snapshots(
    request: Request, background_tasks: BackgroundTasks
):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.snapshot_service import SnapshotService

    svc = SnapshotService()
    status = svc.request_full_rebuild(user["id"])
    if status["is_running"] and status["status"] != "QUEUED":
        return JSONResponse(
            {
                "ok": True,
                "queued": False,
                "status": status,
            }
        )

    background_tasks.add_task(
        SnapshotService().run_full_rebuild, user["id"]
    )
    return JSONResponse(
        {
            "ok": True,
            "queued": True,
            "status": svc.get_rebuild_status(user["id"]),
        }
    )


@router.get("/assets/{asset_id}")
def get_asset(request: Request, asset_id: int):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse(
            {"error": "资产不存在"}, status_code=404
        )

    detail = svc.get_asset_detail(asset_id)
    if not detail:
        return JSONResponse(
            {"error": "资产不存在"}, status_code=404
        )

    # Convert non-serializable types
    detail["created_at"] = str(detail["created_at"])
    return JSONResponse({"asset": detail})


@router.delete("/assets/{asset_id}")
def delete_asset(request: Request, asset_id: int):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse(
            {"error": "资产不存在"}, status_code=404
        )

    svc.deactivate_asset(asset_id)
    return JSONResponse({"message": "已删除"})


# ── Transactions ──────────────────────────────────────────


@router.post("/assets/{asset_id}/transactions")
async def add_transaction(
    request: Request, asset_id: int, background_tasks: BackgroundTasks
):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse(
            {"error": "资产不存在"}, status_code=404
        )

    data = await request.json()
    try:
        tx_id = svc.add_transaction(asset_id, data)
        tx_date = data.get("transaction_date") or date.today().isoformat()
        _queue_snapshot_refresh(
            background_tasks, user["id"], date.fromisoformat(tx_date)
        )
        return JSONResponse(
            {"id": tx_id, "message": "交易已记录"},
            status_code=201,
        )
    except ValueError as e:
        return JSONResponse(
            {"error": str(e)}, status_code=400
        )


@router.get("/assets/{asset_id}/transactions")
def list_transactions(request: Request, asset_id: int):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse(
            {"error": "资产不存在"}, status_code=404
        )

    txs = svc.get_transactions(asset_id)
    return JSONResponse({"transactions": txs})


@router.get("/assets/{asset_id}/cash-flows")
def list_cash_flows(request: Request, asset_id: int):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse(
            {"error": "资产不存在"}, status_code=404
        )

    flows = svc.get_cash_flows(asset_id)
    return JSONResponse({"cash_flows": flows})


@router.post("/assets/{asset_id}/bond-price")
async def save_bond_price(
    request: Request, asset_id: int, background_tasks: BackgroundTasks
):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService
    from ..services.snapshot_service import SnapshotService

    svc = AssetService()
    snapshot_svc = SnapshotService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse(
            {"error": "资产不存在"}, status_code=404
        )

    data = await request.json()
    try:
        price = data.get("price_per_unit")
        if price in (None, ""):
            raise ValueError("请输入债券价格")
        backfill_from = svc.save_bond_price(
            asset_id, Decimal(str(price))
        )
        _queue_snapshot_refresh(
            background_tasks, user["id"], backfill_from
        )
        return JSONResponse(
            {
                "message": "债券价格已保存",
                "backfill_from": backfill_from.isoformat(),
            }
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/assets/{asset_id}/interest")
async def save_interest(
    request: Request, asset_id: int, background_tasks: BackgroundTasks
):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse({"error": "资产不存在"}, status_code=404)

    data = await request.json()
    try:
        amount = data.get("amount")
        if amount in (None, ""):
            raise ValueError("请输入利息金额")
        flow_date = data.get("flow_date") or date.today().isoformat()
        saved_date = svc.save_manual_interest(
            asset_id,
            Decimal(str(amount)),
            date.fromisoformat(flow_date),
            data.get("note"),
        )
        _queue_snapshot_refresh(
            background_tasks, user["id"], saved_date
        )
        return JSONResponse({"message": "利息已记录"})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/assets/{asset_id}/include-price-pnl")
async def set_include_price_pnl(
    request: Request, asset_id: int, background_tasks: BackgroundTasks
):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    if not svc.verify_asset_ownership(asset_id, user["id"]):
        return JSONResponse({"error": "资产不存在"}, status_code=404)

    data = await request.json()
    try:
        enabled = bool(data.get("enabled"))
        svc.set_include_price_pnl(asset_id, enabled)
        refresh_from = (
            svc.get_asset_first_activity_date(asset_id) or date.today()
        )
        _queue_snapshot_refresh(
            background_tasks, user["id"], refresh_from
        )
        return JSONResponse({"message": "已更新盈亏开关"})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Stock Validation & Price ──────────────────────────────


@router.get("/stock/validate/{ticker}")
def validate_ticker(ticker: str):
    from ..services.market_data_service import MarketDataService

    svc = MarketDataService()
    result = svc.validate_ticker(ticker)
    if result:
        return JSONResponse(result)
    return JSONResponse(
        {"valid": False, "ticker": ticker.upper()},
        status_code=200,
    )


@router.get("/stock/price/{ticker}")
def stock_price(ticker: str):
    from ..services.market_data_service import MarketDataService

    svc = MarketDataService()
    price = svc.get_latest_price(ticker)
    if price:
        return JSONResponse(price)
    return JSONResponse(
        {"error": "暂无价格数据"}, status_code=404
    )


# ── Exchange Rate ─────────────────────────────────────────


@router.get("/exchange-rate")
def exchange_rate():
    from ..services.exchange_rate_service import (
        ExchangeRateService,
    )

    svc = ExchangeRateService()
    rate = svc.get_latest_rate()
    if rate:
        return JSONResponse(rate)
    return JSONResponse(
        {"error": "暂无汇率数据"}, status_code=404
    )


# ── Dashboard ─────────────────────────────────────────────


@router.get("/dashboard/widgets")
def dashboard_widgets(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.dashboard_service import DashboardService

    svc = DashboardService()
    data = svc.load_dashboard_data(user["id"])
    return JSONResponse(
        {"widgets": data["widgets"]},
    )


@router.get("/dashboard/live-page")
def dashboard_live_page(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.dashboard_service import DashboardService
    from ..services.ibkr_service import IBKRSyncService

    try:
        IBKRSyncService().sync_user(user["id"], force=False)
    except Exception:
        pass

    svc = DashboardService()
    data = svc.load_dashboard_data(user["id"])
    html = "".join(
        _render_dashboard_widget(request, widget)
        for widget in data["widgets"]
    )
    return JSONResponse(
        {
            "html": html,
            "dashboard_data": json.loads(
                data["dashboard_data_json"]
            ),
        }
    )


@router.put("/dashboard/layout")
async def save_dashboard_layout(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    layout = await request.json()
    from ..services.dashboard_service import DashboardService

    svc = DashboardService()
    svc.save_layout(user["id"], layout)
    return JSONResponse({"message": "布局已保存"})


@router.post("/ibkr/sync")
def sync_ibkr(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.ibkr_service import IBKRSyncService

    svc = IBKRSyncService()
    try:
        result = svc.sync_user(user["id"], force=True)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse(
            {"error": f"IBKR 同步失败: {exc}"},
            status_code=500,
        )


@router.get("/ibkr/sync-status")
def ibkr_sync_status(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.ibkr_service import IBKRSyncService

    svc = IBKRSyncService()
    return JSONResponse(svc.get_sync_status(user["id"]))


@router.get("/ibkr/config")
def ibkr_config(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.ibkr_service import IBKRSyncService

    svc = IBKRSyncService()
    return JSONResponse(svc.get_settings_config(user["id"]))


@router.get("/settings/asset-maintenance")
def asset_maintenance_settings(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.ibkr_service import IBKRSyncService
    from ..services.snapshot_service import SnapshotService

    ibkr_svc = IBKRSyncService()
    snapshot_svc = SnapshotService()
    return JSONResponse(
        {
            "ibkr_config": ibkr_svc.get_settings_config(user["id"]),
            "ibkr_status": ibkr_svc.get_sync_status(user["id"]),
            "snapshot_status": snapshot_svc.get_rebuild_status(user["id"]),
        }
    )


@router.get("/settings/ibkr-panel")
def settings_ibkr_panel(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.ibkr_service import IBKRSyncService

    svc = IBKRSyncService()
    return JSONResponse(
        {
            "ibkr_config": svc.get_settings_config(user["id"]),
            "ibkr_status": svc.get_sync_status(user["id"]),
        }
    )


@router.put("/ibkr/config")
async def save_ibkr_config(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.ibkr_service import IBKRSyncService

    svc = IBKRSyncService()
    data = await request.json()
    try:
        token_expires_at = data.get("token_expires_at")
        svc.save_settings_config(
            user["id"],
            str(data.get("flex_query_id") or "").strip(),
            (data.get("flex_token") or "").strip() or None,
            (
                date.fromisoformat(token_expires_at)
                if token_expires_at
                else None
            ),
            bool(data.get("is_enabled", True)),
        )
        return JSONResponse(
            {
                "message": "IBKR 设置已保存",
                "config": svc.get_settings_config(user["id"]),
                "status": svc.get_sync_status(user["id"]),
            }
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/dashboard/layout-items/{layout_id}/show")
def show_dashboard_widget(request: Request, layout_id: int):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.dashboard_service import DashboardService

    svc = DashboardService()
    item = svc.get_layout_item(user["id"], layout_id)
    if not item:
        return JSONResponse({"error": "组件不存在"}, status_code=404)

    item["is_visible"] = 1
    item["sort_order"] = sum(
        1
        for layout_item in svc.get_user_layout(user["id"])
        if layout_item["is_visible"] and layout_item["id"] != layout_id
    )
    svc.save_layout(
        user["id"],
        [
            {
                "id": item["id"],
                "sort_order": item["sort_order"],
                "is_visible": 1,
            }
        ],
    )

    widget = svc.build_widget_payload(user["id"], item)
    return JSONResponse(
        {
            "widget": widget,
            "html": _render_dashboard_widget(request, widget),
        }
    )


@router.post("/dashboard/layout-items/{layout_id}/hide")
def hide_dashboard_widget(request: Request, layout_id: int):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.dashboard_service import DashboardService

    svc = DashboardService()
    item = svc.get_layout_item(user["id"], layout_id)
    if not item:
        return JSONResponse({"error": "组件不存在"}, status_code=404)

    svc.save_layout(
        user["id"],
        [
            {
                "id": item["id"],
                "sort_order": item["sort_order"],
                "is_visible": 0,
            }
        ],
    )
    return JSONResponse({"message": "组件已移除"})


# ── Asset Types ───────────────────────────────────────────


@router.get("/asset-types")
def list_asset_types(request: Request):
    user = _require_user(request)
    if not user:
        return _unauthorized()

    from ..services.asset_service import AssetService

    svc = AssetService()
    types = svc.get_asset_types()
    return JSONResponse({"types": types})
