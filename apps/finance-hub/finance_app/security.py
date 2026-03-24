import base64
import hashlib
import hmac
import secrets
import time

from .config import settings


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2_sha256${salt}${base64.urlsafe_b64encode(digest).decode('ascii')}"


def verify_password(password, password_hash):
    try:
        scheme, salt, _encoded = (password_hash or "").split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    return hmac.compare_digest(hash_password(password, salt=salt), password_hash)


def make_session_cookie(user_id, username):
    expires_at = int(time.time()) + settings.session_days * 86400
    payload = f"{user_id}|{username}|{expires_at}"
    signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}|{signature}"


def parse_session_cookie(raw_value):
    if not raw_value:
        return None
    parts = raw_value.split("|")
    if len(parts) != 4:
        return None
    user_id, username, expires_at, signature = parts
    payload = f"{user_id}|{username}|{expires_at}"
    expected = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    if int(expires_at) < int(time.time()):
        return None
    return {"user_id": int(user_id), "username": username}
