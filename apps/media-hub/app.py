from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pymysql
import pymysql.cursors
from pathlib import Path
from collections import Counter
import random
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextvars import ContextVar
import os
import re
import json
import threading
import queue
import requests
import urllib.request
from urllib.parse import quote
import time

BASE_DIR = Path(__file__).resolve().parent

def load_env_local(path: Path) -> bool:
    """Load simple KEY=VALUE or export KEY=VALUE lines from .env.local."""
    if not path.exists():
        return False
    try:
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[len('export '):].strip()
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value
        return True
    except Exception:
        return False


ENV_LOCAL_LOADED = load_env_local(BASE_DIR / '.env.local')

# ── 代理配置：优先使用 .env.local；只有读不到时才回退默认代理 ────────────
if not ENV_LOCAL_LOADED:
    _PROXY = os.getenv('HTTP_PROXY', 'http://192.168.50.209:7890')
    os.environ.setdefault('HTTP_PROXY', _PROXY)
    os.environ.setdefault('HTTPS_PROXY', _PROXY)
    os.environ.setdefault('http_proxy', _PROXY)
    os.environ.setdefault('https_proxy', _PROXY)
# ─────────────────────────────────────────────────────────────────────

MYSQL_HOST = os.getenv('MYSQL_HOST', '172.17.0.5')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'joey')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'Joey@2026!')
MYSQL_DB = os.getenv('MYSQL_DB', 'media_hub')
_covers_dir_raw = Path(os.getenv('MEDIA_HUB_COVERS_DIR', '/app/covers'))
COVERS_DIR = _covers_dir_raw if _covers_dir_raw.is_absolute() else (BASE_DIR / _covers_dir_raw).resolve()
CONFIG_DIR = Path(os.getenv('MEDIA_HUB_CONFIG_DIR', str(BASE_DIR / 'config')))
BEIJING_TZ = ZoneInfo('Asia/Shanghai')
RUNTIME_CACHE_TTL_SECONDS = int(os.getenv('MEDIA_HUB_RUNTIME_CACHE_TTL_SECONDS', '20'))
_runtime_cache = {}
METADATA_ENRICH_RETRY_COOLDOWN_SECONDS = int(os.getenv('MEDIA_HUB_METADATA_ENRICH_RETRY_COOLDOWN_SECONDS', '21600'))
_metadata_retry_after = {}
_metadata_queue = queue.Queue()
_metadata_pending = set()
_metadata_lock = threading.Lock()
_metadata_worker_started = False
_cover_queue = queue.Queue()
_cover_pending = set()
_cover_lock = threading.Lock()
_cover_worker_started = False


def get_runtime_cache(key):
    cached = _runtime_cache.get(key)
    if not cached:
        return None
    expires_at, value = cached
    if datetime.utcnow() >= expires_at:
        _runtime_cache.pop(key, None)
        return None
    return value


def set_runtime_cache(key, value, ttl_seconds=RUNTIME_CACHE_TTL_SECONDS):
    _runtime_cache[key] = (datetime.utcnow() + timedelta(seconds=ttl_seconds), value)
    return value
COVER_RETRY_COOLDOWN_SECONDS = int(os.getenv('MEDIA_HUB_COVER_RETRY_COOLDOWN_SECONDS', '60'))
_cover_retry_after = {}


def adapt_sql(sql: str) -> str:
    """Convert SQLite SQL to MySQL-compatible SQL."""
    # ? -> %s
    sql = re.sub(r'\?', '%s', sql)
    # INSERT OR REPLACE -> REPLACE
    sql = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'REPLACE INTO', sql, flags=re.IGNORECASE)
    # datetime('now') / datetime("now") -> NOW()
    sql = re.sub(r'datetime\s*\(\s*[\'"]now[\'"]\s*\)', 'NOW()', sql, flags=re.IGNORECASE)
    # datetime('now', '-30 days') / datetime("now", "-30 days") -> DATE_SUB(NOW(), INTERVAL 30 DAY)
    def _dt_modifier(m):
        mod = m.group(1).strip()
        mm = re.match(r'([+-]\d+)\s+(day|hour|minute|month|year)s?', mod, re.IGNORECASE)
        if mm:
            amt = int(mm.group(1))
            unit = mm.group(2).upper()
            if amt < 0:
                return f'DATE_SUB(NOW(), INTERVAL {abs(amt)} {unit})'
            else:
                return f'DATE_ADD(NOW(), INTERVAL {amt} {unit})'
        return 'NOW()'
    sql = re.sub(r'datetime\s*\(\s*[\'"]now[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]\s*\)', _dt_modifier, sql, flags=re.IGNORECASE)
    # Double-quoted string literals for known values -> single-quoted
    sql = re.sub(r'"(collect|wish|recommended|dislike|user|douban|tmdb|disliked|local)"', r"'\1'", sql)
    # Empty string "" -> ''
    sql = re.sub(r'(?<!\w)""(?!\w)', "''", sql)
    return sql


class MySQLConn:
    """Wraps pymysql to mimic sqlite3 connection interface."""
    def __init__(self):
        self._conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT,
            user=MYSQL_USER, password=MYSQL_PASSWORD,
            database=MYSQL_DB, charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False
        )

    def execute(self, sql, params=None):
        sql = adapt_sql(sql)
        cur = self._conn.cursor()
        started = time.perf_counter()
        cur.execute(sql, params or ())
        elapsed_ms = (time.perf_counter() - started) * 1000
        bump_request_metric('db_query_count', 1)
        bump_request_metric('db_time_ms', round(elapsed_ms, 2))
        return cur

    def cursor(self):
        return MySQLCursor(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class MySQLCursor:
    """Wraps pymysql DictCursor to mimic sqlite3 cursor interface."""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=None):
        started = time.perf_counter()
        self._cur.execute(adapt_sql(sql), params or ())
        elapsed_ms = (time.perf_counter() - started) * 1000
        bump_request_metric('db_query_count', 1)
        bump_request_metric('db_time_ms', round(elapsed_ms, 2))
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur.fetchall())

    @property
    def lastrowid(self):
        return self._cur.lastrowid
SECRETS_DIR = CONFIG_DIR / 'secrets'
COOKIE_PATH = CONFIG_DIR / 'douban_cookie.json'
TMDB_KEY_PATH = SECRETS_DIR / 'tmdb.json'
TMDB_LOG_PATH = BASE_DIR / 'logs' / 'tmdb_failures.log'
REQUEST_PERF_LOG_PATH = BASE_DIR / 'logs' / 'request_perf.log'
COVERS_DIR.mkdir(parents=True, exist_ok=True)
REQUEST_METRICS = ContextVar('request_metrics', default=None)


def log_tmdb_failure(stage: str, detail: str, extra: dict | None = None):
    try:
        TMDB_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'ts': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'stage': stage,
            'detail': detail,
            'extra': extra or {},
        }
        with TMDB_LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception:
        pass


def current_request_metrics():
    return REQUEST_METRICS.get()


def bump_request_metric(key: str, amount=1):
    metrics = current_request_metrics()
    if metrics is None:
        return
    metrics[key] = metrics.get(key, 0) + amount


def log_request_perf(payload: dict):
    try:
        REQUEST_PERF_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with REQUEST_PERF_LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception:
        pass

app = FastAPI(title='Media Hub')
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))


@app.middleware('http')
async def request_perf_middleware(request: Request, call_next):
    metrics = {
        'path': request.url.path,
        'db_query_count': 0,
        'db_time_ms': 0,
        'cover_local_hit': 0,
        'cover_missing': 0,
        'cover_tmdb_attempt': 0,
        'cover_tmdb_fail': 0,
    }
    token = REQUEST_METRICS.set(metrics)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        REQUEST_METRICS.reset(token)
        if request.url.path in {'/', '/recommendations'}:
            payload = {
                'ts': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
                'path': request.url.path,
                'query': dict(request.query_params),
                'duration_ms': duration_ms,
                **metrics,
            }
            log_request_perf(payload)


@app.get('/covers/{filename:path}')
def serve_cover(filename: str):
    path = COVERS_DIR / filename
    if path.exists() and path.is_file():
        return FileResponse(path)

    basename = Path(filename).name
    stem = Path(basename).stem
    safe_stem = safe_subject_id(stem)

    # Fast path: infer directly from requested filename even if DB subject_id format differs.
    inferred_item = None
    if safe_stem.startswith('tmdb_movie_'):
        tmdb_id = safe_stem[len('tmdb_movie_'):]
        inferred_item = {
            'subject_id': safe_stem,
            'tmdb_id': tmdb_id,
            'kind': 'movie',
            'cover_url': f'/covers/{basename}',
            'title': safe_stem,
        }
    elif safe_stem.startswith('tmdb_tv_'):
        tmdb_id = safe_stem[len('tmdb_tv_'):]
        inferred_item = {
            'subject_id': safe_stem,
            'tmdb_id': tmdb_id,
            'kind': 'tv',
            'cover_url': f'/covers/{basename}',
            'title': safe_stem,
        }
    elif safe_stem.startswith('tmdb_') and safe_stem.count('_') == 1:
        tmdb_id = safe_stem[len('tmdb_'):]
        inferred_item = {
            'subject_id': safe_stem,
            'tmdb_id': tmdb_id,
            'kind': 'movie',
            'cover_url': f'/covers/{basename}',
            'title': safe_stem,
        }

    try:
        if inferred_item:
            refreshed = ensure_cover_available(inferred_item)
            refreshed_path = local_cover_file_from_url(refreshed)
            if refreshed_path and refreshed_path.exists() and refreshed_path.is_file():
                return FileResponse(refreshed_path)
    except Exception:
        pass

    # Slow path: resolve non-TMDB/numeric/local historical covers via DB.
    conn = None
    try:
        conn = get_conn()
        row = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=? LIMIT 1', (safe_stem,)).fetchone()
        if row:
            item = dict(row)
            refreshed = ensure_cover_available(item)
            refreshed_path = local_cover_file_from_url(refreshed)
            if refreshed_path and refreshed_path.exists() and refreshed_path.is_file():
                return FileResponse(refreshed_path)
    except Exception:
        pass
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    raise HTTPException(404, 'Cover not found')


def get_conn():
    return MySQLConn()


def metadata_enrichment_missing(item) -> bool:
    if not item:
        return False
    if not str(item.get('tmdb_id') or '').strip():
        return False
    if str(item.get('kind') or '').strip().lower() not in {'movie', 'tv'}:
        return False
    fields = ['year', 'url', 'intro', 'summary', 'genres', 'countries', 'directors', 'actors']
    return any(not item.get(field) for field in fields)


def _start_metadata_worker_if_needed():
    global _metadata_worker_started
    with _metadata_lock:
        if _metadata_worker_started:
            return
        worker = threading.Thread(target=_metadata_enrichment_worker, name='media-hub-metadata-enricher', daemon=True)
        worker.start()
        _metadata_worker_started = True


def enqueue_metadata_enrichment(item):
    if not metadata_enrichment_missing(item):
        return
    subject_id = str(item.get('subject_id') or '').strip()
    tmdb_id = str(item.get('tmdb_id') or '').strip()
    kind = str(item.get('kind') or '').strip().lower()
    if not subject_id or not tmdb_id or kind not in {'movie', 'tv'}:
        return
    retry_key = f'{subject_id}:{tmdb_id}:{kind}'
    retry_after = _metadata_retry_after.get(retry_key)
    if retry_after and datetime.utcnow() < retry_after:
        return
    with _metadata_lock:
        if retry_key in _metadata_pending:
            return
        _metadata_pending.add(retry_key)
    _start_metadata_worker_if_needed()
    _metadata_queue.put((retry_key, subject_id, tmdb_id, kind))


def _metadata_enrichment_worker():
    while True:
        retry_key, subject_id, tmdb_id, kind = _metadata_queue.get()
        try:
            conn = get_conn()
            try:
                row = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=? LIMIT 1', (subject_id,)).fetchone()
                if not row:
                    continue
                current = dict(row)
                if not metadata_enrichment_missing(current):
                    _metadata_retry_after.pop(retry_key, None)
                    continue
                raw = tmdb_fetch_detail(tmdb_id, media_type=kind, append_to_response='credits')
                enriched = extract_tmdb_enrichment_fields(raw, kind)
                updates = {}
                for field in ['year', 'url', 'intro', 'summary', 'genres', 'countries', 'directors', 'actors', 'douban_rating', 'douban_rating_count']:
                    if not current.get(field) and enriched.get(field):
                        updates[field] = enriched[field]
                if updates:
                    set_clause = ', '.join(f'{field}=?' for field in updates)
                    conn.execute(
                        f'UPDATE douban_watch_history SET {set_clause} WHERE subject_id=?',
                        list(updates.values()) + [subject_id]
                    )
                    conn.commit()
                _metadata_retry_after.pop(retry_key, None)
            finally:
                conn.close()
        except Exception as e:
            _metadata_retry_after[retry_key] = datetime.utcnow() + timedelta(seconds=METADATA_ENRICH_RETRY_COOLDOWN_SECONDS)
            log_tmdb_failure('metadata_enrich', f'{type(e).__name__}: {e}', {
                'subject_id': subject_id,
                'tmdb_id': tmdb_id,
                'kind': kind,
            })
        finally:
            with _metadata_lock:
                _metadata_pending.discard(retry_key)
            _metadata_queue.task_done()


def ensure_schema(conn):
    # MySQL: schema pre-created, no-op
    pass


def read_douban_cookie():
    try:
        return json.loads(COOKIE_PATH.read_text()).get('cookie', '').strip()
    except Exception:
        return ''


def write_douban_cookie(cookie: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_PATH.write_text(json.dumps({'cookie': cookie.strip()}, ensure_ascii=False, indent=2))


def read_tmdb_key():
    try:
        return json.loads(TMDB_KEY_PATH.read_text()).get('api_key', '').strip()
    except Exception:
        return ''


def tmdb_probe():
    key = read_tmdb_key()
    if not key:
        return {'ok': False, 'configured': False, 'message': '未配置 TMDB API Key'}
    try:
        r = requests.get('https://api.themoviedb.org/3/configuration', params={'api_key': key}, timeout=15)
        if r.ok:
            return {'ok': True, 'configured': True, 'message': 'TMDB Key 可用'}
        log_tmdb_failure('probe', f'TMDB 返回 {r.status_code}', {'status_code': r.status_code, 'body': r.text[:400]})
        return {'ok': False, 'configured': True, 'message': f'TMDB 返回 {r.status_code}'}
    except Exception as e:
        log_tmdb_failure('probe', f'TMDB 探测失败：{e}')
        return {'ok': False, 'configured': True, 'message': f'TMDB 探测失败：{e}'}


def douban_probe(cookie: str | None = None):
    cookie = (cookie or read_douban_cookie()).strip()
    if not cookie:
        return {'ok': False, 'configured': False, 'message': '未配置 Douban Cookie'}
    req = urllib.request.Request(
        'https://movie.douban.com/subject/1292052/',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://movie.douban.com/',
            'Cookie': cookie,
        },
    )
    try:
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', 'ignore')
        blocked = '禁止访问' in html or '异常请求' in html
        return {
            'ok': not blocked,
            'configured': True,
            'message': 'Cookie 可用' if not blocked else 'Cookie 已配置，但 Douban 当前拒绝访问',
        }
    except Exception as e:
        return {'ok': False, 'configured': True, 'message': f'探测失败：{e}'}


def douban_search_fallback(query: str, kind: str = 'movie', limit: int = 20):
    conn = get_conn()
    sql = 'SELECT * FROM douban_watch_history WHERE 1=1'
    params = []
    if kind == 'movie':
        sql += ' AND kind="movie"'
    elif kind == 'tv':
        sql += ' AND kind="tv" AND genres NOT LIKE "%综艺%"'
    elif kind == 'variety':
        sql += ' AND (genres LIKE "%综艺%" OR title LIKE "%脱口秀%" OR title LIKE "%歌手%")'
    if query:
        sql += ' AND (title LIKE ? OR genres LIKE ? OR actors LIKE ? OR directors LIKE ? OR summary LIKE ?)'
        like = f'%{query}%'
        params += [like] * 5
    sql += ' ORDER BY douban_rating DESC, douban_rating_count DESC, year DESC LIMIT ?'
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        items.append(item)
    return items


def tmdb_kind_config(kind: str):
    if kind == 'movie':
        return {'media_type': 'movie', 'discover_path': '/discover/movie', 'discover_params': {}}
    if kind == 'variety':
        return {'media_type': 'tv', 'discover_path': '/discover/tv', 'discover_params': {'with_genres': '10764|10767'}}
    return {'media_type': 'tv', 'discover_path': '/discover/tv', 'discover_params': {'without_genres': '10764,10767'}}


def tmdb_image_url(path: str | None):
    if not path:
        return None
    return f'https://image.tmdb.org/t/p/w500{path}'


def tmdb_fetch_detail(tmdb_id: str, media_type: str = 'movie', append_to_response: str = ''):
    api_key = read_tmdb_key()
    if not api_key:
        raise RuntimeError('TMDB API key missing')
    media_type = 'tv' if str(media_type).lower() == 'tv' else 'movie'
    url = f'https://api.themoviedb.org/3/{media_type}/{tmdb_id}'
    params = {'api_key': api_key, 'language': 'zh-CN'}
    if append_to_response:
        params['append_to_response'] = append_to_response
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def tmdb_to_item(raw: dict, media_type: str):
    title = raw.get('title') or raw.get('name') or '未命名'
    year_raw = raw.get('release_date') or raw.get('first_air_date') or ''
    year = int(year_raw[:4]) if year_raw[:4].isdigit() else None
    genres = '/'.join(str(g) for g in raw.get('genre_ids', [])) if raw.get('genre_ids') else ''
    overview = raw.get('overview') or ''
    tmdb_id = str(raw.get('id', ''))
    sid = f"tmdb:{media_type}:{tmdb_id}"
    return {
        'subject_id': sid,
        'tmdb_id': tmdb_id,
        'title': title,
        'kind': 'movie' if media_type == 'movie' else 'tv',
        'year': year,
        'url': f'https://www.themoviedb.org/{media_type}/{raw.get("id")}',
        'intro': overview,
        'summary': overview,
        'genres': genres,
        'douban_rating': round((raw.get('vote_average') or 0), 1),
        'douban_rating_count': raw.get('vote_count') or 0,
        'cover_url': tmdb_image_url(raw.get('poster_path')),
        '_cover_url': tmdb_image_url(raw.get('poster_path')),
        '_cover_style': cover_style({'title': title}),
        '_stars': rating_stars(raw.get('vote_average')),
        '_first_genre': '',
        '_first_country': '',
        'status': None,
        'source': 'tmdb',
        'countries': '',
    }


def join_names(values, limit=None):
    items = [str(v).strip() for v in (values or []) if str(v).strip()]
    if limit is not None:
        items = items[:limit]
    return '/'.join(items)


def extract_tmdb_enrichment_fields(raw: dict, media_type: str) -> dict:
    release_raw = raw.get('release_date') or raw.get('first_air_date') or ''
    year = int(release_raw[:4]) if release_raw[:4].isdigit() else None
    genres = join_names([g.get('name') for g in raw.get('genres', []) if isinstance(g, dict)])
    countries = join_names(
        [c.get('name') for c in raw.get('production_countries', []) if isinstance(c, dict)] or
        [c.get('iso_3166_1') for c in raw.get('production_countries', []) if isinstance(c, dict)] or
        raw.get('origin_country', [])
    )
    credits = raw.get('credits') or {}
    cast = credits.get('cast') or []
    crew = credits.get('crew') or []
    if media_type == 'movie':
        directors = join_names([p.get('name') for p in crew if p.get('job') == 'Director'], limit=5)
    else:
        directors = join_names(
            [p.get('name') for p in raw.get('created_by', []) if isinstance(p, dict)] or
            [p.get('name') for p in crew if p.get('job') in {'Director', 'Series Director'}],
            limit=5
        )
    actors = join_names([p.get('name') for p in cast if isinstance(p, dict)], limit=12)
    overview = (raw.get('overview') or '').strip()
    return {
        'year': year,
        'url': f'https://www.themoviedb.org/{media_type}/{raw.get("id")}' if raw.get('id') else None,
        'intro': overview or None,
        'summary': overview or None,
        'genres': genres or None,
        'countries': countries or None,
        'directors': directors or None,
        'actors': actors or None,
        'douban_rating': round((raw.get('vote_average') or 0), 1) if raw.get('vote_average') else None,
        'douban_rating_count': raw.get('vote_count') or None,
    }


def normalize_title(s: str) -> str:
    """Strip punctuation/spaces for fuzzy comparison."""
    if not s:
        return ''
    import unicodedata
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'[\s\-_·:：、，,。.]+', '', s)
    return s.lower()


def match_local_status(conn, item: dict) -> dict:
    """Check if a TMDB item already exists in local DB by tmdb_id or fuzzy title match.
    Returns the item dict with status/subject_id filled from local DB if found."""
    tmdb_id = item.get('tmdb_id', '')
    norm_title = normalize_title(item.get('title', ''))

    # 1. Try exact tmdb_id match
    if tmdb_id:
        row = conn.execute(
            'SELECT * FROM douban_watch_history WHERE tmdb_id=? OR subject_id=?',
            (tmdb_id, f'tmdb:{item["kind"]}:{tmdb_id}')
        ).fetchone()
        if row:
            item = dict(row)
            item['_cover_style'] = cover_style(row)
            item['_cover_url'] = cover_url(row)
            item['_stars'] = rating_stars(item.get('douban_rating'))
            item['_first_genre'] = first_genre(item)
            item['_first_country'] = first_country(item)
            item['_matched'] = 'tmdb_id'
            return item

    # 2. Try fuzzy title match (same normalized title, same kind, year close)
    year = item.get('year')
    kind = item.get('kind')
    candidates = conn.execute(
        'SELECT * FROM douban_watch_history WHERE kind=? AND status IS NOT NULL',
        (kind,)
    ).fetchall()
    for row in candidates:
        row_title = normalize_title(row['title'])
        if row_title and row_title == norm_title:
            matched = dict(row)
            matched.update({k: v for k, v in item.items()
                           if k not in matched or not matched[k]})
            matched['_cover_style'] = cover_style(row)
            matched['_cover_url'] = cover_url(row)
            matched['_stars'] = rating_stars(matched.get('douban_rating'))
            matched['_first_genre'] = first_genre(matched)
            matched['_first_country'] = first_country(matched)
            matched['_matched'] = 'title'
            return matched

    item['status'] = None
    return item


def match_local_status_batch(conn, items: list) -> list:
    """Batch version: match all TMDB items against local DB in 2 queries.
    1. Bulk tmdb_id IN lookup
    2. Bulk normalized title lookup
    Returns items with local status merged in.
    """
    if not items:
        return items

    # Collect all tmdb_ids and normalized titles for batch lookup
    tmdb_ids = [item.get('tmdb_id', '') for item in items if item.get('tmdb_id')]
    kinds = [item.get('kind') for item in items]
    norm_titles = {normalize_title(item.get('title', '')): i for i, item in enumerate(items) if item.get('title')}

    # 1. Bulk tmdb_id match
    local_by_tmdb = {}
    if tmdb_ids:
        placeholders = ','.join(['?'] * len(tmdb_ids))
        rows = conn.execute(
            f'SELECT * FROM douban_watch_history WHERE tmdb_id IN ({placeholders}) OR subject_id LIKE \'tmdb:%%\'',
            tmdb_ids
        ).fetchall()
        for row in rows:
            sid = dict(row).get('subject_id', '')
            tid = dict(row).get('tmdb_id', '')
            if tid in tmdb_ids:
                local_by_tmdb[tid] = dict(row)

    # 2. Bulk title match
    local_by_title = {}
    all_rows = conn.execute(
        'SELECT * FROM douban_watch_history WHERE status IS NOT NULL'
    ).fetchall()
    title_map = {normalize_title(r['title']): dict(r) for r in all_rows if r['title']}

    # Merge results
    result = []
    for item in items:
        tmdb_id = item.get('tmdb_id', '')
        norm_title = normalize_title(item.get('title', ''))
        matched = None
        match_type = None

        # Prefer tmdb_id match
        if tmdb_id and tmdb_id in local_by_tmdb:
            matched = local_by_tmdb[tmdb_id]
            match_type = 'tmdb_id'
        # Then title match
        elif norm_title and norm_title in title_map:
            matched = title_map[norm_title]
            match_type = 'title'

        if matched:
            merged = dict(matched)
            # Overlay TMDB data for fields the local row might not have
            for k, v in item.items():
                if k not in merged or not merged[k]:
                    merged[k] = v
            merged['_matched'] = match_type
            merged['_cover_style'] = cover_style(matched)
            merged['_cover_url'] = cover_url(matched)
            merged['_stars'] = rating_stars(merged.get('douban_rating'))
            merged['_first_genre'] = first_genre(merged)
            merged['_first_country'] = first_country(merged)
            result.append(merged)
        else:
            item['status'] = None
            result.append(item)

    return result


    item['status'] = None
    return item


# 佳奕口味画像排序（按个人观看历史频率）
MOVIE_GENRE_ORDER = [
    ('动作', '28'), ('冒险', '12'), ('奇幻', '14'), ('喜剧', '35'), ('科幻', '878'),
    ('剧情', '18'), ('动画', '16'), ('惊悚', '53'), ('悬疑', '9648'), ('爱情', '10749'),
    ('犯罪', '80'), ('古装', '36|10768'), ('恐怖', '27'),
    ('家庭', '10751'), ('灾难', '10752'), ('传记', '36'), ('战争', '10752'), ('纪录片', '99'),
    ('音乐', '10402'), ('同性', '10749'), ('历史', '36'), ('歌舞', '10402'), ('武侠', '10768'),
    ('运动', '18'), ('儿童', '10762'),
]
TV_GENRE_ORDER = [
    ('剧情', '18'), ('悬疑', '9648'), ('奇幻', '10765'), ('动作', '10759'), ('惊悚', '53'),
    ('古装', '10768'), ('恐怖', '27'), ('科幻', '10765'), ('爱情', '10749'), ('犯罪', '80'),
    ('冒险', '12'), ('家庭', '10751'), ('喜剧', '35'), ('真人秀', '10764'), ('脱口秀', '10767'),
    ('动画', '16'), ('纪录片', '99'), ('历史', '10768'), ('战争', '10768'), ('武侠', '10768'),
    ('同性', '10767'), ('音乐', '10402'), ('儿童', '10762'), ('运动', '18'),
]

def tmdb_genre_map(kind: str):
    if kind == 'movie':
        return dict(MOVIE_GENRE_ORDER)
    return dict(TV_GENRE_ORDER)


def tmdb_discover(kind: str = 'movie', query: str = '', sort: str = 'popularity',
                   region: str = '', year: str = '', genre: str = '', page: int = 1, limit: int = 20):
    key = read_tmdb_key()
    if not key:
        return {'items': [], 'total_pages': 0, 'total_results': 0, 'page': page}
    cfg = tmdb_kind_config(kind)

    sort_map = {
        'popularity': 'popularity.desc',
        'rating':    'vote_average.desc',
        'year':      'primary_release_date.desc' if kind == 'movie' else 'first_air_date.desc',
        'trending':  'vote_count.desc',
    }
    sort_by = sort_map.get(sort, 'popularity.desc')

    if query:
        path = f'/search/{cfg["media_type"]}'
        params = {
            'api_key': key,
            'query': query,
            'language': 'zh-CN',
            'page': page,
            'include_adult': 'false',
        }
    else:
        path = cfg['discover_path']
        params = {
            'api_key': key,
            'language': 'zh-CN',
            'sort_by': sort_by,
            'page': page,
            'vote_count.gte': 20,
        }
        if region:
            params['with_origin_country'] = region.upper()
        if year:
            if year.isdigit():
                if kind == 'movie':
                    params['primary_release_year'] = year
                else:
                    params['first_air_date_year'] = year
            elif year.endswith('s') and year[:-1].isdigit():
                start = int(year[:-1])
                end = start + 9
                if kind == 'movie':
                    params['primary_release_date.gte'] = f'{start}-01-01'
                    params['primary_release_date.lte'] = f'{end}-12-31'
                else:
                    params['first_air_date.gte'] = f'{start}-01-01'
                    params['first_air_date.lte'] = f'{end}-12-31'
        if genre:
            genre_id = tmdb_genre_map(kind).get(genre)
            if genre_id:
                params['with_genres'] = genre_id
        params.update(cfg['discover_params'])

    try:
        r = requests.get(f'https://api.themoviedb.org/3{path}', params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        status_code = getattr(getattr(e, 'response', None), 'status_code', None)
        body = getattr(getattr(e, 'response', None), 'text', '')[:400] if getattr(e, 'response', None) is not None else ''
        log_tmdb_failure('discover', f'{type(e).__name__}: {e}', {
            'path': path,
            'kind': kind,
            'query': query,
            'sort': sort,
            'region': region,
            'year': year,
            'genre': genre,
            'page': page,
            'status_code': status_code,
            'body': body,
        })
        raise
    media_type = cfg['media_type']
    items = [tmdb_to_item(x, media_type) for x in data.get('results', [])[:limit]]
    return {
        'items': items,
        'total_pages': data.get('total_pages', 0),
        'total_results': data.get('total_results', 0),
        'page': page,
    }


def get_site_stats():
    cached = get_runtime_cache('site_stats')
    if cached is not None:
        return cached
    conn = get_conn()
    c = conn.cursor()
    visible = "COALESCE(recommend_feedback, '') != 'dislike'"
    c.execute(f'SELECT COUNT(*) as cnt FROM douban_watch_history WHERE {visible}')
    total = c.fetchone()['cnt']
    c.execute(f'SELECT COUNT(*) as cnt FROM douban_watch_history WHERE {visible} AND status="collect"')
    watched = c.fetchone()['cnt']
    c.execute(f'SELECT COUNT(*) as cnt FROM douban_watch_history WHERE {visible} AND status="wish"')
    wish = c.fetchone()['cnt']
    c.execute(f'SELECT COUNT(*) as cnt FROM douban_watch_history WHERE {visible} AND status="recommended"')
    recommended = c.fetchone()['cnt']
    c.execute(f'SELECT ROUND(AVG(douban_rating),1) as avg_r FROM douban_watch_history WHERE {visible} AND status="collect" AND douban_rating IS NOT NULL')
    row = c.fetchone()
    avg_rating = row['avg_r'] if row else None
    # Rating distribution (my_rating: 1-5)
    dist_rows = c.execute('''
        SELECT my_rating, COUNT(*) as cnt FROM douban_watch_history
        WHERE my_rating IS NOT NULL GROUP BY my_rating ORDER BY my_rating DESC
    ''').fetchall()
    rating_dist = []
    max_count = max((r['cnt'] for r in dist_rows), default=1)
    for r in dist_rows:
        label, count = r['my_rating'], r['cnt']
        rating_dist.append({
            'label': str(label) + '★',
            'count': count,
            'pct': round(count / max_count * 100)
        })
    conn.close()
    return set_runtime_cache('site_stats', {
        'total': total,
        'watched': watched,
        'wish': wish,
        'recommended': recommended,
        'avg_rating': avg_rating,
        'rating_dist': rating_dist,
    })


def split_multi(v):
    return [x.strip() for x in (v or '').split('/') if x.strip()]


def split_tokens(v):
    raw = str(v or '').strip()
    if not raw:
        return []
    for sep in [' / ', '/', '·', '、', ',', '，']:
        raw = raw.replace(sep, '|')
    return [x.strip() for x in raw.split('|') if x.strip()]


def load_profile(conn):
    cached = get_runtime_cache('profile')
    if cached is not None:
        return cached
    rows = conn.execute('SELECT * FROM douban_watch_history WHERE status="collect" AND my_rating IS NOT NULL').fetchall()
    high = [r for r in rows if (r['my_rating'] or 0) >= 4]
    low = [r for r in rows if (r['my_rating'] or 0) <= 2]
    genre_counter = Counter()
    country_counter = Counter()
    dislike_genres = Counter()
    dislike_countries = Counter()
    dislike_keywords = Counter()
    liked_titles = set()
    watched_titles = set()
    low_rated_titles = set()
    low_rated_franchises = set()
    for r in rows:
        title = str(r['title'] or '').strip()
        if title:
            watched_titles.add(normalize_title(title))
    for r in high:
        genre_counter.update(split_tokens(r['genres']))
        country_counter.update(split_tokens(r['countries']))
        if r['title']:
            liked_titles.add(normalize_title(r['title']))
    for r in low:
        dislike_genres.update(split_tokens(r['genres']))
        dislike_countries.update(split_tokens(r['countries']))
        if r['title']:
            norm = normalize_title(r['title'])
            low_rated_titles.add(norm)
            for token in ['哥斯拉','金刚','环太平洋','流浪地球','柯南','唐探','鱿鱼游戏']:
                if token in (r['title'] or ''):
                    low_rated_franchises.add(token)
        for kw in ['看睡着','昏昏欲睡','催眠','太慢','墨迹','无聊','不吸引','尴尬','不知所云','磨磨叽叽']:
            if kw in str(r['comment'] or ''):
                dislike_keywords[kw] += 1
    directors = Counter()
    actors = Counter()
    for r in high[:40]:
        directors.update(split_tokens(r['directors']))
        actors.update(split_tokens(r['actors']))
    return set_runtime_cache('profile', {
        'rated_count': len(rows),
        'high_rated_count': len(high),
        'top_genres': genre_counter.most_common(10),
        'top_countries': country_counter.most_common(8),
        'top_directors': [d for d, _ in directors.most_common(6)],
        'top_actors': [a for a, _ in actors.most_common(10)],
        'dislike_genres': dislike_genres,
        'dislike_countries': dislike_countries,
        'dislike_keywords': dislike_keywords,
        'watched_titles': watched_titles,
        'liked_titles': liked_titles,
        'low_rated_titles': low_rated_titles,
        'low_rated_franchises': low_rated_franchises,
    })


def make_recommendation_reason(item, profile, high_rated=None):
    reasons = []
    title = item.get('title') or '这部'
    genres = split_tokens(item.get('genres'))
    countries = split_tokens(item.get('countries'))
    summary = str(item.get('summary') or item.get('intro') or '').strip()
    profile_genres = {g for g, _ in profile['top_genres']}
    matched_genres = [g for g in genres if g in profile_genres]
    if summary:
        hook = summary[:68].rstrip('，。；;、 ')
        reasons.append(f'它最抓人的不是设定，而是{hook}')
    if matched_genres:
        reasons.append(f"你更容易吃「{' / '.join(matched_genres[:2])}」这类题材")
    if countries:
        profile_countries = {c for c, _ in profile['top_countries']}
        matched_countries = [c for c in countries if c in profile_countries]
        if matched_countries:
            reasons.append(f"产地「{' / '.join(matched_countries[:2])}」和你常看的重合")
    if item.get('douban_rating'):
        reasons.append(f"TMDB 口碑 {item.get('douban_rating')}，不是纯噱头型片单")
    if not reasons:
        reasons.append('它的剧情推进和你的高分片偏好更接近，不是那种容易把你看困的类型')
    return '；'.join(reasons) + '。'


def tmdb_recommendation_candidates(conn, limit=20):
    profile = load_profile(conn)
    candidates = []
    plans = [
        ('movie', 'popularity', 'US', ''), ('movie', 'rating', 'US', ''),
        ('movie', 'popularity', 'KR', ''), ('movie', 'rating', 'JP', ''),
        ('tv', 'popularity', 'US', ''), ('tv', 'rating', 'KR', ''),
        ('tv', 'rating', 'JP', ''), ('tv', 'trending', 'US', ''),
        ('tv', 'popularity', 'KR', '悬疑'), ('movie', 'rating', 'US', '犯罪'),
    ]
    seen = set()
    for kind, sort, region, genre in plans:
        try:
            result = tmdb_discover(kind=kind, sort=sort, region=region, genre=genre, page=1, limit=20)
            items = result.get('items') or []
        except Exception:
            items = []
        for item in items:
            norm = normalize_title(item.get('title') or '')
            if not norm or norm in seen:
                continue
            seen.add(norm)
            if norm in profile['watched_titles']:
                continue
            title = item.get('title') or ''
            if any(token in title for token in profile['low_rated_franchises']):
                continue
            # Use the discovered region as the country hint for scoring
            item['countries'] = region
            score = (item.get('douban_rating') or 0) * 0.9
            year = int(item.get('year') or 0) if str(item.get('year') or '').isdigit() else 0
            votes = item.get('douban_rating_count') or 0
            if year and year < 2018:
                score -= 2.2
                if year < 2010:
                    score -= 1.5
                if (item.get('douban_rating') or 0) >= 8.6 and votes >= 8000:
                    score += 2.6
            score += sum(cnt for g, cnt in profile['top_genres'] if g in split_tokens(item.get('genres'))) * 0.18
            score += sum(cnt for c, cnt in profile['top_countries'] if c in split_tokens(item.get('countries'))) * 0.14
            score -= sum(profile['dislike_genres'].get(g, 0) for g in split_tokens(item.get('genres'))) * 0.22
            score -= sum(profile['dislike_countries'].get(c, 0) for c in split_tokens(item.get('countries'))) * 0.12
            summary = str(item.get('summary') or item.get('intro') or '')
            if any(kw in summary for kw in ['慢热','家庭琐事','温吞']):
                score -= 1.2
            item['_score'] = score
            item['_reason'] = make_recommendation_reason(item, profile)
            item['_cover_style'] = cover_style(item)
            item['_cover_url'] = cover_url(item)
            item['_stars'] = rating_stars(item.get('douban_rating'))
            item['_first_genre'] = first_genre(item)
            item['_first_country'] = first_country(item)
            candidates.append(item)
    candidates.sort(key=lambda x: x.get('_score', 0), reverse=True)
    return candidates[:limit]


def cover_style(item):
    """Generate a deterministic gradient style for items without a cover image."""
    title = item['title'] or '?'
    hue = hash(title) % 360
    return f"background: linear-gradient(135deg, hsl({hue},55%,22%), hsl({(hue+40)%360},50%,15%));"


def normalize_cover_url(value):
    """Normalize cover URLs for browser compatibility.

    Douban sometimes serves poster URLs as .webp in DevTools/network logs.
    Some clients/rendering paths behave more reliably with .jpg, so normalize
    known doubanio poster links back to jpg.
    Also rewrite legacy local cover paths that used ':' in filenames, because
    browsers request them URL-encoded (%3A) and Starlette static serving may
    not resolve them reliably across environments.
    """
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    if 'doubanio.com/view/photo/' in value and value.endswith('.webp'):
        value = value[:-5] + '.jpg'
    if value.startswith('/covers/'):
        filename = value.split('/covers/', 1)[1]
        if ':' in filename:
            stem, dot, ext = filename.rpartition('.')
            safe_name = safe_subject_id(stem) + (dot + ext if dot else '')
            value = f'/covers/{safe_name}'
    return value


def safe_subject_id(subject_id: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', str(subject_id or '').strip())


def local_cover_path(subject_id: str, ext: str = 'jpg'):
    return COVERS_DIR / f'{safe_subject_id(subject_id)}.{ext}'


def local_cover_file_from_url(url: str | None):
    normalized = normalize_cover_url(url)
    if not normalized or not normalized.startswith('/covers/'):
        return None
    filename = normalized.split('/covers/', 1)[1]
    return COVERS_DIR / filename


def persist_cover_url(subject_id: str, cover_url_value: str):
    if not subject_id or not cover_url_value:
        return
    conn = None
    try:
        conn = get_conn()
        conn.execute('UPDATE douban_watch_history SET cover_url=? WHERE subject_id=?', (cover_url_value, subject_id))
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _start_cover_worker_if_needed():
    global _cover_worker_started
    with _cover_lock:
        if _cover_worker_started:
            return
        worker = threading.Thread(target=_cover_localize_worker, name='media-hub-cover-localizer', daemon=True)
        worker.start()
        _cover_worker_started = True


def enqueue_cover_localize(item):
    try:
        subject_id = str(item.get('subject_id') or '').strip()
        tmdb_id = str(item.get('tmdb_id') or '').strip()
        kind = str(item.get('kind') or '').strip().lower()
        cover = normalize_cover_url(item.get('cover_url'))
    except Exception:
        return
    if not subject_id or not tmdb_id or kind not in {'movie', 'tv'}:
        return
    if not cover or not cover.startswith('/covers/'):
        return
    local_path = local_cover_file_from_url(cover)
    if local_path and local_path.exists():
        return
    retry_key = f'{subject_id}:{tmdb_id}:{kind}'
    retry_after = _cover_retry_after.get(retry_key)
    if retry_after and datetime.utcnow() < retry_after:
        return
    with _cover_lock:
        if retry_key in _cover_pending:
            return
        _cover_pending.add(retry_key)
    _start_cover_worker_if_needed()
    _cover_queue.put((retry_key, subject_id, tmdb_id, kind))


def _cover_localize_worker():
    while True:
        retry_key, subject_id, tmdb_id, kind = _cover_queue.get()
        try:
            raw = tmdb_fetch_detail(tmdb_id, media_type=kind)
            poster_path = (raw or {}).get('poster_path')
            if poster_path:
                remote_url = tmdb_image_url(poster_path)
                if remote_url:
                    saved_url = download_cover_to_local(remote_url, subject_id)
                    persist_cover_url(subject_id, saved_url)
            _cover_retry_after.pop(retry_key, None)
        except Exception as e:
            _cover_retry_after[retry_key] = datetime.utcnow() + timedelta(seconds=COVER_RETRY_COOLDOWN_SECONDS)
            log_tmdb_failure('cover_localize_async', f'{type(e).__name__}: {e}', {
                'subject_id': subject_id,
                'tmdb_id': tmdb_id,
                'kind': kind,
            })
        finally:
            with _cover_lock:
                _cover_pending.discard(retry_key)
            _cover_queue.task_done()


def ensure_cover_available(item) -> str | None:
    """Ensure local cover file exists when cover_url points to /covers/... .

    If the local file is missing but tmdb_id is known, fetch poster from TMDB live,
    persist it locally, and return the refreshed local /covers/... URL.
    If TMDB poster cannot be resolved, fall back to the original normalized value.
    """
    try:
        value = item['cover_url']
    except Exception:
        value = item.get('cover_url') if hasattr(item, 'get') else None
    normalized = normalize_cover_url(value)
    if not normalized:
        return None
    if not normalized.startswith('/covers/'):
        return normalized
    local_path = local_cover_file_from_url(normalized)
    if local_path and local_path.exists():
        bump_request_metric('cover_local_hit', 1)
        _cover_retry_after.pop(normalized, None)
        return normalized
    bump_request_metric('cover_missing', 1)

    retry_after = _cover_retry_after.get(normalized)
    if retry_after and datetime.utcnow() < retry_after:
        return normalized

    tmdb_id = None
    kind = None
    title = None
    try:
        tmdb_id = item['tmdb_id']
    except Exception:
        tmdb_id = item.get('tmdb_id') if hasattr(item, 'get') else None
    try:
        kind = item['kind']
    except Exception:
        kind = item.get('kind') if hasattr(item, 'get') else None
    try:
        title = item['title']
    except Exception:
        title = item.get('title') if hasattr(item, 'get') else None

    tmdb_id = str(tmdb_id or '').strip()
    kind = str(kind or '').strip().lower()
    if not tmdb_id or kind not in {'movie', 'tv'}:
        return normalized

    try:
        bump_request_metric('cover_tmdb_attempt', 1)
        raw = tmdb_fetch_detail(tmdb_id, media_type=kind)
        poster_path = (raw or {}).get('poster_path')
        if poster_path:
            remote_url = tmdb_image_url(poster_path)
            if remote_url:
                subject_id = str(item.get('subject_id') if hasattr(item, 'get') else item['subject_id'])
                try:
                    saved_url = download_cover_to_local(remote_url, subject_id)
                    persist_cover_url(subject_id, saved_url)
                    _cover_retry_after.pop(normalized, None)
                    return saved_url
                except Exception as e:
                    _cover_retry_after[normalized] = datetime.utcnow() + timedelta(seconds=COVER_RETRY_COOLDOWN_SECONDS)
                    log_tmdb_failure('download_cover_to_local', f'{type(e).__name__}: {e}', {
                        'subject_id': subject_id,
                        'tmdb_id': tmdb_id,
                        'kind': kind,
                        'title': title,
                        'remote_url': remote_url,
                        'covers_dir': str(COVERS_DIR),
                    })
                    return remote_url
    except Exception as e:
        bump_request_metric('cover_tmdb_fail', 1)
        _cover_retry_after[normalized] = datetime.utcnow() + timedelta(seconds=COVER_RETRY_COOLDOWN_SECONDS)
        log_tmdb_failure('ensure_cover_available', f'{type(e).__name__}: {e}', {
            'tmdb_id': tmdb_id,
            'kind': kind,
            'title': title,
            'cover_url': normalized,
        })
    return normalized


def download_cover_to_local(url: str, subject_id: str) -> str:
    """Download remote cover to local static storage and return served URL path."""
    normalized = normalize_cover_url(url)
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://movie.douban.com/',
    }
    resp = requests.get(normalized, headers=headers, timeout=20)
    resp.raise_for_status()

    content_type = (resp.headers.get('Content-Type') or '').lower()
    if 'png' in content_type:
        ext = 'png'
    elif 'webp' in content_type:
        ext = 'webp'
    else:
        ext = 'jpg'

    # Prefer jpg for normalized douban poster links even if extension parsing is noisy.
    m = re.search(r'\.([a-zA-Z0-9]+)(?:\?|$)', normalized)
    if m and m.group(1).lower() in {'jpg', 'jpeg', 'png', 'webp'}:
        ext = 'jpg' if m.group(1).lower() == 'jpeg' else m.group(1).lower()

    for old in COVERS_DIR.glob(f'{subject_id}.*'):
        try:
            old.unlink()
        except OSError:
            pass

    path = local_cover_path(subject_id, ext)
    path.write_bytes(resp.content)
    return f'/covers/{path.name}'


def cover_url(item):
    """Return normalized cover URL or None. Works for sqlite3.Row and dict."""
    try:
        enqueue_metadata_enrichment(dict(item) if not isinstance(item, dict) else item)
    except Exception:
        pass
    try:
        value = item['cover_url']
    except Exception:
        value = item.get('cover_url') if hasattr(item, 'get') else None
    normalized = normalize_cover_url(value)
    if normalized and normalized.startswith('/covers/'):
        local_path = local_cover_file_from_url(normalized)
        if local_path and local_path.exists():
            bump_request_metric('cover_local_hit', 1)
            return normalized
        bump_request_metric('cover_missing', 1)
        try:
            enqueue_cover_localize(dict(item) if not isinstance(item, dict) else item)
        except Exception:
            pass
        return None
    if normalized:
        return normalized
    poster_path = None
    try:
        poster_path = item['poster_path']
    except Exception:
        poster_path = item.get('poster_path') if hasattr(item, 'get') else None
    if poster_path:
        return tmdb_image_url(poster_path)
    return None


def rating_stars(rating):
    """Convert a 10-point Douban rating (0-10) to a 5-star display string."""
    if not rating:
        return ''
    stars = round(rating / 2)  # Convert 10-point to 5-star
    full = min(5, max(0, stars))
    return '★' * full + '☆' * (5 - full)


def first_genre(item):
    """Return the first genre from a slash-separated genres string, mapping TMDB ids to labels when needed."""
    genres = (item.get('genres') or '').strip()
    if not genres:
        return ''
    first = genres.split('/')[0].strip()
    if first.isdigit():
        kind = item.get('kind') or 'movie'
        for label, gid in (MOVIE_GENRE_ORDER if kind == 'movie' else TV_GENRE_ORDER):
            if first in gid.split('|'):
                return label
    return first


def first_country(item):
    countries = split_tokens(item.get('countries'))
    return countries[0] if countries else ''


def display_rating(value):
    if value in (None, '', 0):
        return '-'
    try:
        return f"{float(value):.1f}"
    except Exception:
        return str(value)


def display_kind(value):
    mapping = {
        'movie': '电影',
        'tv': '剧集',
        'show': '综艺',
        'anime': '动画',
    }
    return mapping.get((value or '').lower(), value or '内容')




def cache_recommendations(conn, items, cache_key='default'):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute('DELETE FROM recommendation_cache WHERE cache_key=?', (cache_key,))
    for idx, item in enumerate(items, start=1):
        tmdb_id = str(item.get('tmdb_id') or item.get('subject_id') or '').replace('tmdb:', '')
        subject_id = f'tmdb:{tmdb_id}' if tmdb_id else str(item.get('subject_id') or '')
        poster = item.get('_cover_url') or item.get('cover_url') or cover_url(item)
        local_cover = None
        if poster and tmdb_id:
            try:
                local_cover = download_cover_to_local(poster, subject_id)
            except Exception:
                local_cover = poster
        conn.execute("""INSERT OR REPLACE INTO recommendation_cache (
                cache_key, tmdb_id, subject_id, title, kind, year, url, intro, summary,
                tmdb_rating, tmdb_vote_count, genres, countries, poster_url, cover_url,
                score, reason, rank_order, generated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cache_key, tmdb_id, subject_id, item.get('title'), item.get('kind'), item.get('year'), item.get('url'),
                item.get('intro'), item.get('summary'), item.get('douban_rating'), item.get('douban_rating_count'),
                item.get('genres'), item.get('countries'), poster, local_cover, item.get('_score'), item.get('_reason'), idx, now
            )
        )
    conn.commit()


def recommendation_order_sql(sort: str = 'date') -> str:
    if sort == 'rating':
        return 'COALESCE(douban_rating, 0) DESC, COALESCE(recommended_at, "") DESC'
    if sort == 'year':
        return 'COALESCE(year, 0) DESC, COALESCE(recommended_at, "") DESC'
    return 'COALESCE(recommend_rank, 9999), COALESCE(recommended_at, "") DESC'


def count_recommended_items(conn) -> int:
    row = conn.execute(
        'SELECT COUNT(*) as cnt FROM douban_watch_history WHERE status="recommended" AND COALESCE(recommend_feedback, "") != "dislike"'
    ).fetchone()
    return int((row or {}).get('cnt') or 0)


def load_recommended_items(conn, profile=None, limit: int | None = None, offset: int = 0, sort: str = 'date'):
    sql = f'''
        SELECT * FROM douban_watch_history
        WHERE status="recommended" AND COALESCE(recommend_feedback, "") != "dislike"
        ORDER BY {recommendation_order_sql(sort)}
    '''
    params = []
    if limit is not None:
        sql += ' LIMIT ? OFFSET ?'
        params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    profile_data = profile
    need_profile = any(not dict(r).get('recommendation_note') for r in rows)
    if profile_data is None and need_profile:
        profile_data = load_profile(conn)
    items = []
    for r in rows:
        item = dict(r)
        item['_reason'] = item.get('recommendation_note') or make_recommendation_reason(item, profile_data or {})
        item['_score'] = item.get('recommend_rank') or 0
        item['_cover_url'] = cover_url(item)
        item['_cover_style'] = cover_style(item)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        item['_display_rating'] = display_rating(item.get('douban_rating'))
        item['_display_kind'] = display_kind(item.get('kind'))
        items.append(item)
    return items


def current_featured_bucket(now=None):
    now = now or datetime.now(BEIJING_TZ)
    return now.strftime('%Y%m%d%H')


def featured_candidates(items, limit=8):
    if not items:
        return []
    return items[:limit] if len(items) >= limit else items


def stable_pick_index(items, bucket, salt='default'):
    if not items:
        return 0
    subject_ids = '|'.join(str(item.get('subject_id') or '') for item in items)
    digest = hashlib.sha256(f'{bucket}|{salt}|{subject_ids}'.encode('utf-8')).hexdigest()
    return int(digest[:8], 16) % len(items)


def pick_featured_item(items, request=None, limit=8):
    candidates = featured_candidates(items, limit=limit)
    if not candidates:
        return None, current_featured_bucket()
    bucket = current_featured_bucket()
    cookie_value = ((request.cookies.get('featured_pick') if request else '') or '').strip()
    if ':' in cookie_value:
        cookie_bucket, cookie_subject_id = cookie_value.split(':', 1)
        if cookie_bucket == bucket:
            matched = next((item for item in candidates if item.get('subject_id') == cookie_subject_id), None)
            if matched:
                return matched, bucket
    return candidates[stable_pick_index(candidates, bucket)], bucket


def pick_alternate_featured_item(items, request=None, limit=8):
    candidates = featured_candidates(items, limit=limit)
    if not candidates:
        return None, current_featured_bucket()
    current_item, bucket = pick_featured_item(candidates, request=request, limit=limit)
    if len(candidates) <= 1:
        return current_item, bucket
    remaining = [item for item in candidates if item.get('subject_id') != current_item.get('subject_id')]
    next_index = stable_pick_index(remaining, bucket, salt=f'shuffle|{current_item.get("subject_id")}')
    return remaining[next_index], bucket


def load_cached_recommendations(conn, cache_key='default', max_age_hours=12):
    rows = conn.execute(
        "SELECT * FROM recommendation_cache WHERE cache_key=? AND generated_at >= datetime('now', ?) ORDER BY rank_order ASC",
        (cache_key, f'-{max_age_hours} hours')
    ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        title = str(item.get('title') or '')
        if not re.search(r'[一-鿿]', title):
            continue
        item['douban_rating'] = item.get('tmdb_rating')
        item['douban_rating_count'] = item.get('tmdb_vote_count')
        item['_reason'] = item.get('reason')
        item['_score'] = item.get('score')
        item['_cover_url'] = item.get('cover_url') or item.get('poster_url')
        item['_cover_style'] = cover_style(item)
        item['_stars'] = rating_stars(item.get('tmdb_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        item['_display_rating'] = display_rating(item.get('tmdb_rating'))
        item['_display_kind'] = display_kind(item.get('kind'))
        local = conn.execute(
            'SELECT subject_id,status,my_rating,comment,watched_date,watch_count,recommendation_note FROM douban_watch_history WHERE subject_id=? OR tmdb_id=? LIMIT 1',
            (item.get('subject_id'), str(item.get('tmdb_id') or '')),
        ).fetchone()
        if local:
            local = dict(local)
            item.update({k: v for k, v in local.items() if v is not None})
            if local.get('recommendation_note'):
                item['_reason'] = local['recommendation_note']
        items.append(item)
    return items


def upsert_recommendation_item(conn, payload: dict, target_status: str | None = None, watched_date: str | None = None, my_rating=None, comment=None, watch_count=None):
    subject_id = str(payload.get('subject_id') or '').strip()
    tmdb_id = str(payload.get('tmdb_id') or '').strip()
    title = (payload.get('title') or '未命名').strip()
    if not subject_id:
        raise HTTPException(400, 'subject_id required')
    existing = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=? OR (tmdb_id=? AND tmdb_id!="") LIMIT 1', (subject_id, tmdb_id)).fetchone()
    rec_note = (payload.get('recommendation_note') or payload.get('_reason') or '').strip() or None
    raw_cover_url = normalize_cover_url(payload.get('cover_url') or payload.get('_cover_url'))
    final_cover_url = raw_cover_url or (existing['cover_url'] if existing else None)
    should_download_cover = bool(raw_cover_url and raw_cover_url.startswith('http') and not (existing and existing['cover_url']))
    if should_download_cover:
        try:
            final_cover_url = download_cover_to_local(raw_cover_url, subject_id)
        except Exception:
            final_cover_url = raw_cover_url
    final_watch_count = watch_count if watch_count is not None else (existing['watch_count'] if existing and existing['watch_count'] else (1 if target_status == 'collect' else None))
    final_status = target_status or (existing['status'] if existing else 'wish')
    recommended_at = payload.get('recommended_at') or (existing['recommended_at'] if existing and final_status == 'recommended' else None)
    recommend_rank = payload.get('recommend_rank') if payload.get('recommend_rank') is not None else (existing['recommend_rank'] if existing and final_status == 'recommended' else None)
    recommend_source = payload.get('recommend_source') or (existing['recommend_source'] if existing and final_status == 'recommended' else None)
    if existing:
        conn.execute(
            '''UPDATE douban_watch_history SET
                title=?, kind=?, year=?, url=?, intro=?, summary=?, douban_rating=?, douban_rating_count=?,
                genres=?, countries=?, directors=?, actors=?, status=?, watched_date=COALESCE(?, watched_date),
                watch_count=COALESCE(?, watch_count), my_rating=COALESCE(?, my_rating), comment=COALESCE(?, comment),
                tmdb_id=COALESCE(?, tmdb_id), cover_url=COALESCE(?, cover_url), recommendation_note=COALESCE(?, recommendation_note),
                recommended_at=?, recommend_rank=?, recommend_source=?,
                rating_source=CASE WHEN ? IS NOT NULL THEN "user" ELSE rating_source END,
                comment_source=CASE WHEN ? IS NOT NULL THEN "user" ELSE comment_source END
               WHERE subject_id=?''',
            (
                title, payload.get('kind'), payload.get('year'), payload.get('url'), payload.get('intro'), payload.get('summary'),
                payload.get('douban_rating'), payload.get('douban_rating_count'), payload.get('genres'), payload.get('countries'),
                payload.get('directors'), payload.get('actors'), final_status, watched_date, final_watch_count, my_rating, comment,
                tmdb_id or None, final_cover_url, rec_note, recommended_at, recommend_rank, recommend_source, my_rating, comment, existing['subject_id']
            )
        )
        subject_id = existing['subject_id']
    else:
        conn.execute(
            '''INSERT INTO douban_watch_history (
                subject_id,title,kind,year,url,intro,watched_date,my_rating,comment,douban_rating,douban_rating_count,
                directors,actors,countries,genres,summary,status,cover_url,watch_count,rating_source,comment_source,tmdb_id,recommendation_note,
                recommended_at,recommend_rank,recommend_source,added_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))''',
            (
                subject_id, title, payload.get('kind'), payload.get('year'), payload.get('url'), payload.get('intro'),
                watched_date, my_rating, comment, payload.get('douban_rating'), payload.get('douban_rating_count'), payload.get('directors'),
                payload.get('actors'), payload.get('countries'), payload.get('genres'), payload.get('summary'), final_status,
                final_cover_url, final_watch_count, 'user' if my_rating is not None else 'douban',
                'user' if comment is not None else 'douban', tmdb_id or None, rec_note, recommended_at, recommend_rank, recommend_source
            )
        )
    conn.commit()
    row = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    return dict(row) if row else None

@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()
    rows = conn.execute('SELECT status, COUNT(*) as cnt FROM douban_watch_history GROUP BY status').fetchall()
    counts = {r['status']: r['cnt'] for r in rows}
    profile = load_profile(conn)
    recs = load_recommended_items(conn, profile=profile, limit=8, sort='date')
    recent_rows = conn.execute('SELECT * FROM douban_watch_history WHERE status="collect" AND COALESCE(recommend_feedback, "") != "dislike" ORDER BY watched_date DESC LIMIT 8').fetchall()
    recent = []
    for r in recent_rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        recent.append(item)
    year_rows = conn.execute("""
        SELECT substr(watched_date, 1, 4) AS period, COUNT(*) AS total
        FROM douban_watch_history
        WHERE status='collect' AND watched_date IS NOT NULL AND watched_date != '' AND COALESCE(recommend_feedback, '') != 'dislike'
        GROUP BY substr(watched_date, 1, 4)
        ORDER BY period ASC
    """).fetchall()
    month_rows = conn.execute("""
        SELECT substr(watched_date, 1, 7) AS period, COUNT(*) AS total
        FROM douban_watch_history
        WHERE status='collect' AND watched_date IS NOT NULL AND watched_date != '' AND COALESCE(recommend_feedback, '') != 'dislike'
        GROUP BY substr(watched_date, 1, 7)
        ORDER BY period ASC
    """).fetchall()
    yearly_stats = [dict(r) for r in year_rows if r['period']]
    current_year = str(datetime.now(ZoneInfo('Asia/Shanghai')).year)
    current_year_watched = next((item['total'] for item in yearly_stats if item['period'] == current_year), 0)
    month_by_year = {}
    for r in month_rows:
        period = r['period']
        if not period:
            continue
        year = period[:4]
        month_by_year.setdefault(year, []).append({'period': period, 'total': r['total']})
    month_years = sorted(month_by_year.keys())
    selected_month_year = month_years[-1] if month_years else None
    monthly_stats = month_by_year.get(selected_month_year, [])
    tonight_pick, featured_bucket = pick_featured_item(recs, request=request, limit=8)
    return templates.TemplateResponse('index.html', {
        'request': request,
        'counts': counts,
        'profile': profile,
        'recent': recent,
        'surprise': dict(tonight_pick) if tonight_pick else None,
        'featured_bucket': featured_bucket,
        'site_stats': get_site_stats(),
        'yearly_stats': yearly_stats,
        'current_year': current_year,
        'current_year_watched': current_year_watched,
        'monthly_stats': monthly_stats,
        'month_by_year': month_by_year,
        'month_years': month_years,
        'selected_month_year': selected_month_year,
    })


def build_library_items(conn, status='all', kind='all', q='', sort='date', limit=200):
    sql = 'SELECT * FROM douban_watch_history WHERE 1=1'
    params = []
    if status == 'dislike':
        sql += ' AND COALESCE(recommend_feedback, "") = "dislike"'
    else:
        sql += ' AND COALESCE(recommend_feedback, "") != "dislike"'
        if status != 'all':
            sql += ' AND status=?'
            params.append(status)
    if kind != 'all':
        sql += ' AND kind=?'
        params.append(kind)
    if q:
        sql += ' AND (title LIKE ? OR genres LIKE ? OR countries LIKE ? OR actors LIKE ? OR directors LIKE ?)'
        like = f'%{q}%'
        params += [like] * 5
    if sort == 'rating':
        sql += ' ORDER BY douban_rating DESC, watched_date DESC LIMIT ?'
    elif sort == 'year':
        sql += ' ORDER BY year DESC, watched_date DESC LIMIT ?'
    elif sort == 'title':
        sql += ' ORDER BY title ASC LIMIT ?'
    else:
        sql += ' ORDER BY watched_date DESC, douban_rating DESC LIMIT ?'
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        items.append(item)
    return items


@app.post('/api/douban-cookie', response_class=JSONResponse)
async def save_douban_cookie(request: Request):
    payload = await request.json()
    cookie = (payload.get('cookie') or '').strip()
    if not cookie:
        raise HTTPException(400, 'cookie is required')
    write_douban_cookie(cookie)
    return douban_probe(cookie)


@app.get('/discover', response_class=HTMLResponse)
def discover(request: Request,
             kind: str   = Query('movie'),
             q: str      = Query(''),
             sort: str   = Query('popularity'),
             region: str = Query(''),
             year: str   = Query(''),
             genre: str  = Query(''),
             page: int   = Query(1)):
    tmdb_status = tmdb_probe()
    source = 'tmdb' if tmdb_status.get('ok') else 'local'
    if source == 'tmdb':
        result = tmdb_discover(kind=kind, query=q, sort=sort, region=region, year=year, genre=genre, page=page, limit=20)
        # Batch match all TMDB items against local DB for watch status
        conn = get_conn()
        items = match_local_status_batch(conn, result['items'])
        conn.close()
        mode = 'search' if q else 'discover'
        total_pages = result['total_pages']
        total_results = result['total_results']
    else:
        if q:
            items = douban_search_fallback(q, kind=kind, limit=60)
            mode = 'search'
        else:
            conn = get_conn()
            sql = 'SELECT * FROM douban_watch_history WHERE COALESCE(recommend_feedback, "") != "dislike"'
            params = []
            if kind == 'movie':
                sql += ' AND kind="movie"'
            elif kind == 'tv':
                sql += ' AND kind="tv" AND genres NOT LIKE "%综艺%"'
            elif kind == 'variety':
                sql += ' AND (genres LIKE "%综艺%" OR title LIKE "%脱口秀%" OR title LIKE "%歌手%")'
            if sort == 'rating':
                sql += ' ORDER BY douban_rating DESC, year DESC LIMIT 60'
            elif sort == 'year':
                sql += ' ORDER BY year DESC, douban_rating DESC LIMIT 60'
            else:
                sql += ' ORDER BY douban_rating DESC, douban_rating_count DESC, year DESC LIMIT 60'
            rows = conn.execute(sql, params).fetchall()
            items = []
            for r in rows:
                item = dict(r)
                item['_cover_style'] = cover_style(r)
                item['_cover_url'] = cover_url(r)
                item['_stars'] = rating_stars(item.get('douban_rating'))
                item['_first_genre'] = first_genre(item)
                item['_first_country'] = first_country(item)
                items.append(item)
            mode = 'discover'
        total_pages = 1
        total_results = len(items)

    genre_map = tmdb_genre_map(kind)
    ordered = MOVIE_GENRE_ORDER if kind == 'movie' else TV_GENRE_ORDER
    all_genres = [(label, gid) for label, gid in ordered if label in genre_map]
    top_genres = all_genres[:7]
    extra_genres = all_genres[7:]

    return templates.TemplateResponse('discover.html', {
        'request': request,
        'items': items,
        'kind': kind,
        'q': q,
        'sort': sort,
        'region': region,
        'year': year,
        'genre': genre,
        'top_genres': top_genres,
        'extra_genres': extra_genres,
        'year_options': [str(y) for y in range(2026, 2019, -1)],
        'page': page,
        'total_pages': total_pages,
        'total_results': total_results,
        'mode': mode,
        'source': source,
        'tmdb_probe': tmdb_status,
        'site_stats': get_site_stats(),
    })


@app.get('/watchlist', response_class=HTMLResponse)
def watchlist(request: Request, kind: str = Query('all'), q: str = Query(''), sort: str = Query('date'), added_order: str = Query('desc'), page: int = Query(1)):
    PAGE_SIZE = 20
    conn = get_conn()
    items, total = build_wish_items_paged(conn, kind=kind, q=q, sort=sort, added_order=added_order, page=page, page_size=PAGE_SIZE)
    return templates.TemplateResponse('library.html', {
        'request': request,
        'items': items,
        'status': 'wish',
        'kind': kind,
        'q': q,
        'sort': sort,
        'added_order': added_order,
        'page': page,
        'total': total,
        'page_size': PAGE_SIZE,
        'page_mode': 'watchlist',
        'site_stats': get_site_stats(),
    })


def build_wish_items_paged(conn, kind='all', q='', sort='date', added_order='desc', page=1, page_size=40):
    offset = (page - 1) * page_size
    sql = 'SELECT * FROM douban_watch_history WHERE status="wish" AND COALESCE(recommend_feedback, "") != "dislike"'
    params = []
    if kind != 'all':
        sql += ' AND kind=?'
        params.append(kind)
    if q:
        sql += ' AND (title LIKE ? OR genres LIKE ? OR countries LIKE ? OR actors LIKE ? OR directors LIKE ?)'
        like = f'%{q}%'
        params += [like] * 5
    order_dir = 'DESC' if added_order == 'desc' else 'ASC'
    if sort == 'rating':
        order = f'douban_rating DESC, added_at {order_dir}'
    elif sort == 'year':
        order = f'year DESC, added_at {order_dir}'
    elif sort == 'title':
        order = 'title ASC'
    else:
        order = f'added_at {order_dir}'
    where = sql.replace('SELECT *', 'SELECT COUNT(*) as cnt')
    total = conn.execute(where, params).fetchone()['cnt']
    sql += f' ORDER BY {order} LIMIT ? OFFSET ?'
    rows = conn.execute(sql, params + [page_size, offset]).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        items.append(item)
    return items, total


def build_library_items_wish(conn, kind='all', q='', sort='date', added_order='desc', limit=300):
    sql = 'SELECT * FROM douban_watch_history WHERE status="wish"'
    params = []
    if kind != 'all':
        sql += ' AND kind=?'
        params.append(kind)
    if q:
        sql += ' AND (title LIKE ? OR genres LIKE ? OR countries LIKE ? OR actors LIKE ? OR directors LIKE ?)'
        like = f'%{q}%'
        params += [like] * 5
    # Default: order by added_at (newest first = desc)
    order_dir = 'DESC' if added_order == 'desc' else 'ASC'
    if sort == 'rating':
        sql += f' ORDER BY douban_rating DESC, added_at {order_dir} LIMIT ?'
    elif sort == 'year':
        sql += f' ORDER BY year DESC, added_at {order_dir} LIMIT ?'
    elif sort == 'title':
        sql += f' ORDER BY title ASC LIMIT ?'
    else:
        sql += f' ORDER BY added_at {order_dir} LIMIT ?'
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        items.append(item)
    return items


def build_library_items_paged(conn, status='all', kind='all', q='', sort='date', page=1, page_size=40):
    """Paginated version of library items builder. Returns (items, total_count)."""
    offset = (page - 1) * page_size

    # Build WHERE clause
    where = []
    params = []
    if status == 'dislike':
        where.append('COALESCE(recommend_feedback, "") = "dislike"')
    else:
        where.append('COALESCE(recommend_feedback, "") != "dislike"')
        if status != 'all':
            where.append('status=?')
            params.append(status)
    if kind != 'all':
        where.append('kind=?')
        params.append(kind)
    if q:
        where.append('(title LIKE ? OR genres LIKE ? OR countries LIKE ? OR actors LIKE ? OR directors LIKE ?)')
        like = f'%{q}%'
        params += [like] * 5
    where_clause = ' AND '.join(where)

    # Total count
    total = conn.execute(f'SELECT COUNT(*) as cnt FROM douban_watch_history WHERE {where_clause}', params).fetchone()['cnt']

    # Order
    if sort == 'rating':
        order = 'douban_rating DESC, watched_date DESC'
    elif sort == 'year':
        order = 'year DESC, watched_date DESC'
    elif sort == 'title':
        order = 'title ASC'
    else:
        order = 'watched_date DESC, douban_rating DESC'

    sql = f'SELECT * FROM douban_watch_history WHERE {where_clause} ORDER BY {order} LIMIT ? OFFSET ?'
    rows = conn.execute(sql, params + [page_size, offset]).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        item['_first_country'] = first_country(item)
        items.append(item)
    return items, total


@app.get('/library', response_class=HTMLResponse)
def library(request: Request, status: str = Query('collect'), kind: str = Query('all'), q: str = Query(''), sort: str = Query('date'), page: int = Query(1)):
    PAGE_SIZE = 20
    conn = get_conn()
    items, total = build_library_items_paged(conn, status=status, kind=kind, q=q, sort=sort, page=page, page_size=PAGE_SIZE)
    return templates.TemplateResponse('library.html', {
        'request': request,
        'items': items,
        'status': status,
        'kind': kind,
        'q': q,
        'sort': sort,
        'page': page,
        'total': total,
        'page_size': PAGE_SIZE,
        'page_mode': 'library',
        'site_stats': get_site_stats(),
    })


@app.get('/recommendations', response_class=HTMLResponse)
def recommendations(request: Request, sort: str = Query('date'), page: int = Query(1)):
    PAGE_SIZE = 20
    conn = get_conn()
    profile = None
    featured_recs = load_recommended_items(conn, limit=8, sort='date')
    if sort == 'random':
        profile = load_profile(conn)
        recs_with_reason = load_recommended_items(conn, profile=profile, sort='date')
        random.shuffle(recs_with_reason)
        total = len(recs_with_reason)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * PAGE_SIZE
        paged_recs = recs_with_reason[offset:offset + PAGE_SIZE]
    else:
        total = count_recommended_items(conn)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * PAGE_SIZE
        paged_recs = load_recommended_items(conn, limit=PAGE_SIZE, offset=offset, sort=sort)
    tonight_pick, featured_bucket = pick_featured_item(featured_recs, request=request, limit=8)
    return templates.TemplateResponse('recommendations.html', {
        'request': request,
        'recs': paged_recs,
        'surprise': dict(tonight_pick) if tonight_pick else None,
        'today_pick': dict(tonight_pick) if tonight_pick else None,
        'featured_bucket': featured_bucket,
        'sort': sort,
        'page': page,
        'total': total,
        'page_size': PAGE_SIZE,
        'total_pages': total_pages,
        'last_updated': (lambda dt: (dt + timedelta(hours=8)).strftime('%m-%d %H:%M') if dt else '')(
            (tonight_pick.get('recommended_at') if isinstance(tonight_pick.get('recommended_at'), datetime)
             else (datetime.strptime(tonight_pick['recommended_at'], '%Y-%m-%d %H:%M:%S') if tonight_pick and tonight_pick.get('recommended_at') else None))
        ) if tonight_pick and tonight_pick.get('recommended_at') else '',
        'site_stats': get_site_stats(),
    })


@app.post('/api/featured/shuffle', response_class=JSONResponse)
def shuffle_featured(request: Request):
    conn = get_conn()
    featured_recs = load_recommended_items(conn)
    picked, bucket = pick_alternate_featured_item(featured_recs, request=request, limit=8)
    if not picked:
        raise HTTPException(404, 'No recommendations available')
    response = JSONResponse({'ok': True, 'subject_id': picked.get('subject_id'), 'bucket': bucket})
    response.set_cookie('featured_pick', f'{bucket}:{picked.get("subject_id")}', max_age=7200, path='/', samesite='lax')
    return response


@app.get('/api/surprise', response_class=JSONResponse)
def surprise_me():
    """Return a random recommendation from the top candidates."""
    conn = get_conn()
    profile = load_profile(conn)
    recs = tmdb_recommendation_candidates(conn, limit=30)
    if not recs:
        raise HTTPException(404, 'No recommendations available')
    high_rated = [dict(r) for r in conn.execute(
        'SELECT * FROM douban_watch_history WHERE status="collect" AND my_rating >= 4'
    ).fetchall()]
    recs_with_score = []
    for r in recs:
        rec = dict(r)
        genre_counter = Counter(g for g, _ in profile['top_genres'])
        country_counter = Counter(c for c, _ in profile['top_countries'])
        rec['_score'] = (
            (rec['douban_rating'] or 0) * 0.8 +
            sum(genre_counter[g] for g in split_multi(rec['genres'])) * 0.35 +
            sum(country_counter[c] for c in split_multi(rec['countries'])) * 0.25
        )
        rec['_reason'] = make_recommendation_reason(r, profile, high_rated)
        rec['_cover_style'] = cover_style(r)
        rec['_cover_url'] = cover_url(r)
        recs_with_score.append(rec)
    picked = random.choice(recs_with_score[:20]) if recs_with_score else None
    if not picked:
        raise HTTPException(404, 'No recommendations available')
    return dict(picked)


@app.get('/api/item/{subject_id}', response_class=JSONResponse)
def get_item(subject_id: str):
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')
    return dict(item)


@app.post('/api/watchlist/import-tmdb', response_class=JSONResponse)
async def import_tmdb_to_watchlist(request: Request):
    payload = await request.json()
    subject_id = payload.get('subject_id')
    if not subject_id:
        raise HTTPException(400, 'subject_id required')
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if item:
        if item['status'] != 'collect':
            conn.execute('UPDATE douban_watch_history SET status="wish" WHERE subject_id=?', (subject_id,))
    else:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tmdb_id = subject_id.split(':')[-1] if subject_id.startswith('tmdb:') else ''
        conn.execute(
            '''INSERT INTO douban_watch_history (
                subject_id, tmdb_id, title, kind, year, url, intro, summary, douban_rating, douban_rating_count,
                status, cover_url, watched_date, watch_count, added_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "wish", ?, NULL, 1, ?)''',
            (
                subject_id,
                tmdb_id,
                payload.get('title') or '未命名',
                payload.get('kind'),
                payload.get('year'),
                payload.get('url'),
                payload.get('intro'),
                payload.get('summary'),
                payload.get('douban_rating'),
                payload.get('douban_rating_count'),
                payload.get('cover_url'),
                now,
            )
        )
    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    return {'ok': True, 'item': dict(updated)}


@app.post('/api/watchlist/add/{subject_id}', response_class=JSONResponse)
def add_to_watchlist(subject_id: str):
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')
    if item['status'] != 'collect':
        conn.execute('UPDATE douban_watch_history SET status="wish" WHERE subject_id=?', (subject_id,))
    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    return {'ok': True, 'item': dict(updated)}


@app.post('/api/feedback/{subject_id}', response_class=JSONResponse)
async def set_feedback(subject_id: str, request: Request, feedback: str = Query(...)):
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')
    if feedback not in {'like', 'dislike', 'clear'}:
        raise HTTPException(400, 'feedback must be like/dislike/clear')
    payload = await request.json()
    dislike_reason = (payload.get('dislike_reason') or '').strip() if isinstance(payload, dict) else ''
    if feedback == 'dislike' and not dislike_reason:
        dislike_reason = item['dislike_reason'] or ''
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_feedback = None if feedback == 'clear' else feedback
    new_status = item['status']
    if feedback == 'like' and item['status'] != 'collect':
        new_status = 'wish'
    if feedback == 'clear':
        dislike_reason = None
    conn.execute(
        'UPDATE douban_watch_history SET recommend_feedback=?, feedback_updated_at=?, dislike_reason=?, status=? WHERE subject_id=?',
        (new_feedback, now, dislike_reason, new_status, subject_id)
    )
    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    return {'ok': True, 'item': dict(updated), 'feedback': new_feedback, 'status': updated['status'], 'dislike_reason': updated['dislike_reason']}


@app.post('/api/watch/{subject_id}', response_class=JSONResponse)
async def mark_watched(subject_id: str, request: Request):
    """Mark an item as watched; recommendation items are first persisted into the library."""
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=? OR tmdb_id=? LIMIT 1', (subject_id, subject_id.replace('tmdb:', ''))).fetchone()
    payload = await request.json()
    now = payload.get('watched_date') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    watch_count = payload.get('watch_count')
    if watch_count is None:
        watch_count = (item['watch_count'] if item and item['watch_count'] else 1)
    else:
        watch_count = max(int(watch_count), 1)
    my_rating = payload.get('my_rating')
    comment = payload.get('comment')
    if item and not payload:
        if item['status'] == 'collect':
            conn.execute('UPDATE douban_watch_history SET status="wish" WHERE subject_id=?', (item['subject_id'],))
            conn.commit()
            return {'ok': True, 'subject_id': item['subject_id'], 'status': 'wish'}
        conn.execute(
            'UPDATE douban_watch_history SET status="collect", watched_date=?, watch_count=? WHERE subject_id=?',
            (now, max(watch_count, 1), item['subject_id'])
        )
        conn.commit()
        return {'ok': True, 'subject_id': item['subject_id'], 'status': 'collect', 'watched_date': now, 'watch_count': max(watch_count, 1)}

    data = dict(item) if item else {'subject_id': subject_id}
    data.update(payload or {})
    if 'recommendation_note' not in data:
        data['recommendation_note'] = payload.get('_reason') or payload.get('reason')
    saved = upsert_recommendation_item(conn, data, target_status='collect', watched_date=now, my_rating=my_rating, comment=comment, watch_count=watch_count)
    return {'ok': True, 'subject_id': saved['subject_id'], 'status': 'collect', 'watched_date': saved['watched_date'], 'watch_count': saved.get('watch_count') or 1, 'item': saved}


@app.post('/api/want/{subject_id}', response_class=JSONResponse)
async def add_to_wishlist(subject_id: str, request: Request):
    conn = get_conn()
    existing = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=? OR tmdb_id=? LIMIT 1', (subject_id, subject_id.replace('tmdb:', ''))).fetchone()
    payload = await request.json()
    data = dict(existing) if existing else {'subject_id': subject_id}
    data.update(payload or {})
    if 'recommendation_note' not in data:
        data['recommendation_note'] = payload.get('_reason') or payload.get('reason')
    saved = upsert_recommendation_item(conn, data, target_status='wish')
    conn.execute('UPDATE douban_watch_history SET recommend_feedback=NULL, feedback_updated_at=? WHERE subject_id=?', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), saved['subject_id']))
    conn.commit()
    saved = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (saved['subject_id'],)).fetchone()
    return {'ok': True, 'subject_id': saved['subject_id'], 'status': 'wish', 'item': dict(saved)}


@app.post('/api/rewatch/{subject_id}', response_class=JSONResponse)
def add_rewatch(subject_id: str):
    """Record another watch of an item (increments watch_count, adds timestamp)."""
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    current_count = (item['watch_count'] or 1)
    conn.execute(
        'UPDATE douban_watch_history SET status="collect", watched_date=?, watch_count=? WHERE subject_id=?',
        (now, current_count + 1, subject_id)
    )
    conn.commit()
    return {'ok': True, 'subject_id': subject_id, 'watched_date': now, 'watch_count': current_count + 1}


@app.put('/api/rate/{subject_id}', response_class=JSONResponse)
def update_rating(subject_id: str, my_rating: int = None, comment: str = None, watched_date: str = None):
    """Update personal rating, comment, and watched date for an item. Marks source as user-edited."""
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')
    if my_rating is not None:
        conn.execute('UPDATE douban_watch_history SET my_rating=?, rating_source="user" WHERE subject_id=?', (my_rating, subject_id))
    if comment is not None:
        conn.execute('UPDATE douban_watch_history SET comment=?, comment_source="user" WHERE subject_id=?', (comment, subject_id))
    if watched_date is not None:
        conn.execute('UPDATE douban_watch_history SET watched_date=? WHERE subject_id=?', (watched_date, subject_id))
    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    return dict(updated)


@app.post('/api/edit/{subject_id}', response_class=JSONResponse)
async def edit_item(subject_id: str, request: Request):
    """Edit an item from JSON body: rating, comment, watched date, watch count, cover_url."""
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')

    payload = await request.json()
    my_rating = payload.get('my_rating')
    comment = payload.get('comment')
    watched_date = payload.get('watched_date')
    watch_count = payload.get('watch_count')
    cover_url = payload.get('cover_url')
    recommendation_note = payload.get('recommendation_note')

    if my_rating is not None:
        conn.execute('UPDATE douban_watch_history SET my_rating=?, rating_source="user" WHERE subject_id=?', (my_rating, subject_id))
    if comment is not None:
        conn.execute('UPDATE douban_watch_history SET comment=?, comment_source="user" WHERE subject_id=?', (comment, subject_id))
    if watched_date is not None:
        conn.execute('UPDATE douban_watch_history SET watched_date=? WHERE subject_id=?', (watched_date, subject_id))
    if watch_count is not None:
        conn.execute('UPDATE douban_watch_history SET watch_count=? WHERE subject_id=?', (watch_count, subject_id))
    if cover_url is not None:
        final_cover_url = normalize_cover_url(cover_url)
        if final_cover_url and final_cover_url.startswith('http'):
            try:
                final_cover_url = download_cover_to_local(final_cover_url, subject_id)
            except Exception:
                # Fallback to remote URL if local caching fails.
                final_cover_url = normalize_cover_url(cover_url)
        conn.execute('UPDATE douban_watch_history SET cover_url=? WHERE subject_id=?', (final_cover_url, subject_id))
    if recommendation_note is not None:
        conn.execute('UPDATE douban_watch_history SET recommendation_note=? WHERE subject_id=?', (recommendation_note, subject_id))

    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    conn.close()
    return dict(updated)


@app.get('/api/library/search', response_class=JSONResponse)
def api_library_search(q: str = Query(''), limit: int = Query(10)):
    """Search local library for merge/discover purposes."""
    conn = get_conn()
    if q:
        rows = conn.execute(
            'SELECT * FROM douban_watch_history WHERE status != "recommended" AND title LIKE ? ORDER BY status="wish" DESC, douban_rating DESC LIMIT ?',
            (f'%{q}%', limit)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM douban_watch_history WHERE status != "recommended" ORDER BY douban_rating DESC LIMIT ?',
            (limit,)
        ).fetchall()
    conn.close()
    return {'items': [dict(r) for r in rows]}


@app.post('/api/merge', response_class=JSONResponse)
async def api_merge(request: Request):
    """Merge a discover/TMDB item into an existing local item.
    Target keeps user rating/comment; TMDB metadata overlays target. If source exists locally, delete it."""
    payload = await request.json()
    source_id = payload.get('source_subject_id')
    target_id = payload.get('target_subject_id')

    if not source_id or not target_id:
        raise HTTPException(400, 'source_subject_id and target_subject_id required')

    conn = get_conn()
    source_row = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (source_id,)).fetchone()
    target = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (target_id,)).fetchone()

    if not target:
        raise HTTPException(404, 'Target item not found')

    source = dict(source_row) if source_row else {
        'subject_id': source_id,
        'tmdb_id': payload.get('tmdb_id') or (source_id.split(':')[-1] if str(source_id).startswith('tmdb:') else ''),
        'title': payload.get('title'),
        'kind': payload.get('kind'),
        'year': payload.get('year'),
        'url': payload.get('url'),
        'intro': payload.get('intro'),
        'summary': payload.get('summary'),
        'genres': payload.get('genres') or '',
        'douban_rating': payload.get('douban_rating'),
        'douban_rating_count': payload.get('douban_rating_count'),
        'cover_url': payload.get('cover_url')
    }

    updates = {}
    for field in ['tmdb_id', 'title', 'kind', 'year', 'url', 'intro', 'summary',
                  'genres', 'douban_rating', 'douban_rating_count', 'cover_url']:
        if source.get(field):
            updates[field] = source.get(field)
    updates['status'] = 'collect'
    if not target['watched_date']:
        updates['watched_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if updates.get('cover_url') and str(updates['cover_url']).startswith('http'):
        try:
            updates['cover_url'] = download_cover_to_local(updates['cover_url'], target_id)
        except Exception:
            updates['cover_url'] = normalize_cover_url(updates['cover_url'])

    set_clause = ', '.join(f'{k}=?' for k in updates.keys())
    conn.execute(
        f'UPDATE douban_watch_history SET {set_clause} WHERE subject_id=?',
        list(updates.values()) + [target_id]
    )

    if source_row and source_id != target_id:
        conn.execute('DELETE FROM douban_watch_history WHERE subject_id=?', (source_id,))

    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (target_id,)).fetchone()
    conn.close()
    return {'ok': True, 'item': dict(updated)}


@app.post('/api/mark-watched', response_class=JSONResponse)
async def api_mark_watched(request: Request):
    """Mark a TMDB item as watched. Creates local record if needed with full data + cover."""
    payload = await request.json()
    subject_id = payload.get('subject_id')
    if not subject_id:
        raise HTTPException(400, 'subject_id required')

    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()

    now = payload.get('watched_date') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if item:
        # Update existing
        if item['status'] != 'collect':
            conn.execute(
                'UPDATE douban_watch_history SET status="collect", watched_date=? WHERE subject_id=?',
                (now, subject_id)
            )
    else:
        # Create new
        tmdb_id = subject_id.split(':')[-1] if subject_id.startswith('tmdb:') else ''
        cover_url = payload.get('cover_url') or ''
        final_cover = cover_url
        if final_cover and final_cover.startswith('http'):
            try:
                final_cover = download_cover_to_local(final_cover, subject_id)
            except Exception:
                final_cover = normalize_cover_url(cover_url)

        conn.execute(
            '''INSERT INTO douban_watch_history (
                subject_id, tmdb_id, title, kind, year, url, intro, summary, genres,
                douban_rating, douban_rating_count, status, cover_url, watched_date,
                watch_count, added_at, my_rating, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "collect", ?, ?, 1, datetime("now"), ?, ?)''',
            (
                subject_id, tmdb_id,
                payload.get('title') or '未命名',
                payload.get('kind'),
                payload.get('year'),
                payload.get('url'),
                payload.get('intro') or '',
                payload.get('summary') or '',
                '',
                payload.get('douban_rating'),
                payload.get('douban_rating_count'),
                final_cover,
                now,
                payload.get('my_rating'),
                payload.get('comment'),
            )
        )

    # Update rating and comment if provided
    rating = payload.get('my_rating')
    comment = payload.get('comment')
    if rating is not None:
        conn.execute('UPDATE douban_watch_history SET my_rating=?, rating_source="user" WHERE subject_id=?', (rating, subject_id))
    if comment:
        conn.execute('UPDATE douban_watch_history SET comment=?, comment_source="user" WHERE subject_id=?', (comment, subject_id))

    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    conn.close()
    return {'ok': True, 'item': dict(updated)}


@app.delete('/api/delete/{subject_id}', response_class=JSONResponse)
def delete_item(subject_id: str):
    """Delete a local item by subject_id."""
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        conn.close()
        raise HTTPException(404, 'Item not found')
    conn.execute('DELETE FROM douban_watch_history WHERE subject_id=?', (subject_id,))
    conn.commit()
    conn.close()
    return {'ok': True, 'subject_id': subject_id}


@app.post('/api/generate-note', response_class=JSONResponse)
async def generate_note(request: Request):
    import json as _json, asyncio as _asyncio, requests as _req, re as _re
    payload = await request.json()

    title = payload.get('title', '')
    genres = payload.get('genres', '')
    plot = payload.get('plot', '')
    user_high_rated = payload.get('user_high_rated', [])
    user_dislike_topics = payload.get('dislike_topics', [])
    user_prefer_genres = payload.get('user_prefer_genres', [])

    prompt = f"""为以下影视内容写一段推荐语，40-80字，只输出推荐语本身。

要求：结合作者偏好来写，有观点有钩子。不写\"如果你喜欢X\"套话，不以\"该片讲述了\"开头。

作者偏好 - 最近喜欢：{', '.join(user_high_rated[:6]) or '无'}；反感：{', '.join(user_dislike_topics[:6]) or '无'}；偏好题材：{', '.join(user_prefer_genres[:4]) or '无'}

待推荐：{title}（{genres}）
剧情：{plot[:200] if plot else '暂无简介'}"""

    def _call_llm():
        _proxies = {'http': 'http://192.168.50.209:7890', 'https': 'http://192.168.50.209:7890'}
        try:
            resp = _req.post(
                'http://host.docker.internal:18789/api/generate',
                json={'model': 'qwen2.5', 'prompt': prompt, 'stream': False, 'options': {'temperature': 0.8, 'num_predict': 200}},
                proxies=_proxies, timeout=60
            )
            return resp.json().get('response', '').strip()
        except Exception:
            return None

    note = await _asyncio.to_thread(_call_llm)
    if note:
        note = _re.sub(r'^["""\'\s]+|["""\'\s]+$', '', note)

    return {'note': note, 'title': title}
