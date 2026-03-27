"""Lightweight in-process cache for rendered page payloads."""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class PageCacheService:
    """Short-lived user-scoped cache for heavy page data endpoints."""

    _store: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        now = time()
        if not entry:
            return None
        if entry.expires_at <= now:
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> Any:
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time() + max(ttl_seconds, 1),
        )
        return value

    def get_or_set(
        self, key: str, ttl_seconds: int, builder
    ) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        return self.set(key, builder(), ttl_seconds)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_user_pages(self, user_id: int) -> None:
        prefixes = (
            f"dashboard:live_page:{user_id}",
            f"assets:live_content:{user_id}",
            f"dashboard:shell:{user_id}",
            f"assets:shell:{user_id}",
        )
        keys_to_delete = [
            key
            for key in list(self._store.keys())
            if key.startswith(prefixes)
        ]
        for key in keys_to_delete:
            self._store.pop(key, None)
