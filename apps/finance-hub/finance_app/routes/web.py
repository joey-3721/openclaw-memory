from __future__ import annotations

import logging
from datetime import date
from time import perf_counter

from fastapi import APIRouter, Form, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)

from ..config import settings
from ..db import get_cursor
from ..services.auth import authenticate_user, get_current_user
from ..services.page_cache_service import PageCacheService

router = APIRouter()
logger = logging.getLogger(__name__)
LIVE_PAGE_CACHE_TTL_SECONDS = 60
PAGE_SHELL_CACHE_TTL_SECONDS = 60


@router.get("/favicon.ico")
def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


def render_template(
    request: Request,
    template_name: str,
    context: dict,
    status_code: int = 200,
) -> object:
    """Render a Jinja2 template with the given context."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        template_name, {"request": request, **context}, status_code=status_code
    )


@router.get("/login")
def login_page(request: Request):
    current_user = get_current_user(request)
    if current_user:
        return RedirectResponse("/", status_code=302)
    return render_template(
        request, "login.html", {"title": "登录 · Finance Hub"}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user, error = authenticate_user(username.strip(), password)
    if error or not user:
        return render_template(
            request,
            "login.html",
            {
                "title": "登录 · Finance Hub",
                "login_error": error or "登录失败",
                "login_username": username.strip(),
            },
            status_code=400,
        )

    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        settings.session_cookie_name,
        user["session_cookie"],
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/")
def dashboard_page(request: Request):
    started_at = perf_counter()
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    from ..services.dashboard_service import DashboardService

    cache = PageCacheService()
    cache_key = f"dashboard:shell:v2:{current_user['id']}"

    def _build_html():
        svc = DashboardService()
        layout = svc.get_user_layout(current_user["id"])
        widgets = [
            {
                "id": item["id"],
                "widget_type": item["widget_type"],
                "display_name": item["display_name"],
                "description": item.get("description", ""),
                "component_template": item["component_template"],
                "sort_order": item["sort_order"],
                "width": item["width"],
                "is_visible": item["is_visible"],
                "data": {},
                "is_loading": True,
            }
            for item in layout
            if item["is_visible"]
        ]
        template = request.app.state.templates.env.get_template(
            "index.html"
        )
        return template.render(
            {
                "request": request,
                "title": "Finance Hub",
                "current_user": current_user,
                "active_page": "dashboard",
                "widgets": widgets,
                "dashboard_data_json": "{}",
                "dashboard_layout_json": svc.serialize_layout(layout),
            }
        )

    print(
        "PERF page dashboard",
        {
            "user_id": current_user["id"],
            "duration_ms": round(
                (perf_counter() - started_at) * 1000, 1
            ),
        },
        flush=True,
    )

    html = cache.get_or_set(
        cache_key,
        PAGE_SHELL_CACHE_TTL_SECONDS,
        _build_html,
    )
    return HTMLResponse(html)


@router.get("/assets")
def assets_page(request: Request):
    started_at = perf_counter()
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    user_id = current_user["id"]

    print(
        "PERF page assets total",
        {
            "user_id": user_id,
            "duration_ms": round(
                (perf_counter() - started_at) * 1000, 1
            ),
        },
        flush=True,
    )

    cache = PageCacheService()
    cache_key = f"assets:shell:v2:{user_id}"

    def _build_html():
        template = request.app.state.templates.env.get_template(
            "assets.html"
        )
        return template.render(
            {
                "request": request,
                "title": "我的资产 · Finance Hub",
                "current_user": current_user,
                "active_page": "assets",
                "assets": [],
                "performance_summary": {
                    "total_cny": 0.0,
                    "daily_change_cny": 0.0,
                    "daily_change_pct": 0.0,
                    "total_pnl_cny": 0.0,
                    "realized_pnl_cny": 0.0,
                    "unrealized_pnl_cny": 0.0,
                    "income_pnl_cny": 0.0,
                    "total_return_pct": 0.0,
                },
                "is_assets_loading": True,
                "ibkr_sync_status": {
                    "can_manual_sync": False,
                    "last_synced_at_display": "加载中...",
                },
                "snapshot_rebuild_status": {
                    "can_start": False,
                    "is_running": False,
                    "status": "IDLE",
                    "last_completed_at_display": "加载中...",
                    "refresh_from": None,
                },
                "today_iso": date.today().isoformat(),
            }
        )

    html = cache.get_or_set(
        cache_key,
        PAGE_SHELL_CACHE_TTL_SECONDS,
        _build_html,
    )
    return HTMLResponse(html)


@router.get("/assets/live-content")
def assets_live_content(request: Request):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    from ..services.asset_service import AssetService
    from ..services.ibkr_service import IBKRSyncService
    from ..services.exchange_rate_service import ExchangeRateService
    from ..services.market_data_service import MarketDataService
    from ..services.snapshot_service import SnapshotService

    user_id = current_user["id"]
    asset_svc = AssetService()
    ibkr_svc = IBKRSyncService()
    market_svc = MarketDataService()
    snapshot_svc = SnapshotService()

    try:
        ibkr_svc.sync_user(user_id, force=False)
    except Exception:
        logger.warning(
            "Failed to auto-sync IBKR on assets live content",
            exc_info=True,
        )

    try:
        ExchangeRateService().ensure_rates_current()
    except Exception:
        logger.warning(
            "Failed to refresh FX rates on assets live content",
            exc_info=True,
        )

    try:
        raw_assets = asset_svc.get_user_assets(user_id)
        for asset in raw_assets:
            if asset["has_market_price"] and asset["ticker_symbol"]:
                market_svc.ensure_prices_current(asset["ticker_symbol"])
    except Exception:
        logger.warning(
            "Failed to refresh prices on assets live content",
            exc_info=True,
        )

    try:
        snapshot_svc.ensure_today_snapshot(user_id)
    except Exception:
        logger.warning(
            "Failed to refresh snapshot on assets live content",
            exc_info=True,
        )

    cache = PageCacheService()
    cache_key = f"assets:live_content:v2:{user_id}"

    def _build_html():
        assets = asset_svc.get_user_assets_with_values(user_id)
        performance_summary = snapshot_svc.get_performance_summary(
            user_id, assets=assets
        )
        response = render_template(
            request,
            "partials/assets_content.html",
            {
                "assets": assets,
                "performance_summary": performance_summary,
                "current_user": current_user,
                "active_page": "assets",
                "today_iso": date.today().isoformat(),
            },
        )
        return response.body.decode("utf-8")

    html = cache.get_or_set(
        cache_key,
        LIVE_PAGE_CACHE_TTL_SECONDS,
        _build_html,
    )
    return HTMLResponse(html)


@router.get("/settings")
def settings_page(request: Request):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse("/login", status_code=302)

    return render_template(
        request,
        "settings.html",
        {
            "title": "设置 · Finance Hub",
            "current_user": current_user,
            "active_page": "settings",
            "ibkr_settings": {
                "flex_query_id": "",
                "token_expires_at": "",
                "token_expires_at_display": "加载中...",
                "token_is_expired": False,
                "last_imported_to_display": "加载中...",
                "is_enabled": True,
            },
            "ibkr_sync_status": {
                "can_manual_sync": False,
                "last_synced_at_display": "加载中...",
            },
            "snapshot_rebuild_status": {
                "can_start": False,
                "is_running": False,
                "status": "IDLE",
                "last_completed_at_display": "加载中...",
                "message": "加载中...",
                "refresh_from": None,
            },
        },
    )


@router.get("/api/health", response_class=JSONResponse)
def health_check():
    payload = {
        "ok": True,
        "service": "finance-hub",
        "database": settings.mysql_db,
    }
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
        payload["database_ok"] = True
        payload["pool"] = "active"
    except Exception as exc:
        payload["database_ok"] = False
        payload["error"] = str(exc)
    return JSONResponse(payload)
