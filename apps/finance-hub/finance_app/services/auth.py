from fastapi import Request

from ..config import settings
from ..db import ensure_schema, get_conn, touch_last_login
from ..security import make_session_cookie, parse_session_cookie, verify_password


def authenticate_user(username, password):
    try:
        conn = get_conn()
        ensure_schema(conn)
        row = conn.execute(
            """
            SELECT id, username, password_plain, password_hash, display_name, is_active
            FROM finance_users
            WHERE username=%s
            LIMIT 1
            """,
            (username,),
        ).fetchone()
        if not row:
            conn.close()
            return None, "用户名不存在"
        if not row["is_active"]:
            conn.close()
            return None, "账号已被禁用"

        password_ok = False
        if row.get("password_hash"):
            password_ok = verify_password(password, row["password_hash"])
        elif row.get("password_plain") is not None:
            password_ok = password == row["password_plain"]

        if not password_ok:
            conn.close()
            return None, "密码不正确"

        touch_last_login(conn, row["id"])
        conn.close()
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row.get("display_name") or row["username"],
            "session_cookie": make_session_cookie(row["id"], row["username"]),
        }, None
    except Exception as exc:
        return None, f"数据库连接失败：{exc}"


def get_current_user(request: Request):
    try:
        cookie_value = request.cookies.get(settings.session_cookie_name)
        session_data = parse_session_cookie(cookie_value)
        if not session_data:
            return None
        conn = get_conn()
        ensure_schema(conn)
        row = conn.execute(
            """
            SELECT id, username, display_name, is_active
            FROM finance_users
            WHERE id=%s AND username=%s
            LIMIT 1
            """,
            (session_data["user_id"], session_data["username"]),
        ).fetchone()
        conn.close()
        if not row or not row["is_active"]:
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row.get("display_name") or row["username"],
        }
    except Exception:
        return None
