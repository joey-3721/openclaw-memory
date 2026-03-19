from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
from pathlib import Path
from collections import Counter
import random

BASE_DIR = Path(__file__).resolve().parent
import os
DB_PATH = Path(os.getenv('MEDIA_HUB_DB', str(BASE_DIR / 'douban_media.db')))

app = FastAPI(title='Media Hub')
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')
templates = Jinja2Templates(directory=str(BASE_DIR / 'templates'))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def split_multi(v):
    return [x.strip() for x in (v or '').split('/') if x.strip()]


def load_profile(conn):
    rows = conn.execute('SELECT * FROM douban_watch_history WHERE status="collect" AND my_rating IS NOT NULL').fetchall()
    high = [r for r in rows if r['my_rating'] >= 4]
    genre_counter = Counter()
    country_counter = Counter()
    for r in high:
        genre_counter.update(split_multi(r['genres']))
        country_counter.update(split_multi(r['countries']))
    return {
        'rated_count': len(rows),
        'high_rated_count': len(high),
        'top_genres': genre_counter.most_common(8),
        'top_countries': country_counter.most_common(6),
    }


def recommendation_candidates(conn):
    rows = conn.execute('SELECT * FROM douban_watch_history').fetchall()
    high = [r for r in rows if r['status'] == 'collect' and r['my_rating'] is not None and r['my_rating'] >= 4]
    wish = [r for r in rows if r['status'] == 'wish']
    genre_counter = Counter(); country_counter = Counter(); kind_counter = Counter()
    for r in high:
        genre_counter.update(split_multi(r['genres']))
        country_counter.update(split_multi(r['countries']))
        kind_counter.update([r['kind'] or 'unknown'])
    ranked = []
    for r in wish:
        score = (r['douban_rating'] or 0) * 0.8
        score += sum(genre_counter[g] for g in split_multi(r['genres'])) * 0.35
        score += sum(country_counter[c] for c in split_multi(r['countries'])) * 0.25
        score += kind_counter[r['kind'] or 'unknown'] * 0.5
        if r['kind'] == 'movie':
            score += 1.0
        ranked.append((score, r))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked]


@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()
    counts = dict(conn.execute('SELECT status, COUNT(*) FROM douban_watch_history GROUP BY status').fetchall())
    profile = load_profile(conn)
    recs = recommendation_candidates(conn)[:6]
    recent = conn.execute('SELECT * FROM douban_watch_history WHERE status="collect" ORDER BY watched_date DESC LIMIT 8').fetchall()
    return templates.TemplateResponse('index.html', {
        'request': request,
        'counts': counts,
        'profile': profile,
        'recs': recs,
        'recent': recent,
    })


@app.get('/library', response_class=HTMLResponse)
def library(request: Request, status: str = Query('collect'), kind: str = Query('all'), q: str = Query('')):
    conn = get_conn()
    sql = 'SELECT * FROM douban_watch_history WHERE 1=1'
    params = []
    if status != 'all':
        sql += ' AND status=?'
        params.append(status)
    if kind != 'all':
        sql += ' AND kind=?'
        params.append(kind)
    if q:
        sql += ' AND (title LIKE ? OR genres LIKE ? OR countries LIKE ? OR actors LIKE ? OR directors LIKE ?)'
        like = f'%{q}%'
        params += [like]*5
    sql += ' ORDER BY watched_date DESC, douban_rating DESC LIMIT 200'
    items = conn.execute(sql, params).fetchall()
    return templates.TemplateResponse('library.html', {
        'request': request,
        'items': items,
        'status': status,
        'kind': kind,
        'q': q,
    })


@app.get('/recommendations', response_class=HTMLResponse)
def recommendations(request: Request):
    conn = get_conn()
    recs = recommendation_candidates(conn)
    surprise = random.choice(recs[:10]) if recs else None
    return templates.TemplateResponse('recommendations.html', {
        'request': request,
        'recs': recs[:24],
        'surprise': surprise,
    })
