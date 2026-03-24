from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import settings
from ..db import ensure_schema, get_conn
from ..services.auth import authenticate_user, get_current_user
from ..services.dashboard import load_dashboard_from_db


router = APIRouter()


def render_template(request: Request, template_name: str, context: dict, status_code: int = 200):
    templates = request.app.state.templates
    return templates.TemplateResponse(template_name, {"request": request, **context}, status_code=status_code)


@router.get("/login")
def login_page(request: Request):
    current_user = get_current_user(request)
    if current_user:
        return RedirectResponse("/", status_code=302)
    return render_template(request, "login.html", {"title": "登录 · Finance Hub"})


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
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
def dashboard(request: Request):
    current_user = get_current_user(request)
    if not current_user:
        return RedirectResponse("/login", status_code=302)
    data = load_dashboard_from_db()
    return render_template(
        request,
        "index.html",
        {
            "title": "Finance Hub",
            "current_user": current_user,
            **data,
        },
    )


@router.get("/api/health", response_class=JSONResponse)
def health_check():
    payload = {"ok": True, "service": "finance-hub", "database": settings.mysql_db}
    try:
        conn = get_conn()
        ensure_schema(conn)
        conn.close()
        payload["database_ok"] = True
    except Exception as exc:
        payload["database_ok"] = False
        payload["error"] = str(exc)
    return JSONResponse(payload)
