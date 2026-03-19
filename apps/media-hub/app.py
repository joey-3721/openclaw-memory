from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
from pathlib import Path
from collections import Counter
import random
import hashlib
from datetime import datetime

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
    directors = Counter()
    actors = Counter()
    for r in high[:30]:
        directors.update(split_multi(r['directors']))
        actors.update(split_multi(r['actors']))
    return {
        'rated_count': len(rows),
        'high_rated_count': len(high),
        'top_genres': genre_counter.most_common(8),
        'top_countries': country_counter.most_common(6),
        'top_directors': [d for d, _ in directors.most_common(5)],
        'top_actors': [a for a, _ in actors.most_common(8)],
    }


def make_recommendation_reason(item, profile, high_rated=None):
    """Generate a human-readable reason why this item was recommended.
    
    Args:
        item: the candidate item dict
        profile: user taste profile dict
        high_rated: optional list of user's highly-rated items (dicts) for richer context
    """
    reasons = []
    genres = split_multi(item['genres'])
    countries = split_multi(item['countries'])
    directors = split_multi(item['directors'])
    actors = split_multi(item['actors'])

    # Genre match
    profile_genres = {g for g, _ in profile['top_genres']}
    matched_genres = [g for g in genres if g in profile_genres]
    if matched_genres:
        genre_str = '/'.join(matched_genres[:2])
        # Count how many highly-rated items share this genre
        if high_rated:
            genre_count = sum(1 for r in high_rated if any(g in profile_genres for g in split_multi(r.get('genres') or '')))
            if genre_count >= 3:
                reasons.append(f"「{genre_str}」是你最高频给高分的题材（共{genre_count}部）")
            else:
                reasons.append(f"你喜欢的「{genre_str}」")
        else:
            reasons.append(f"你喜欢的「{genre_str}」")

    # Country match
    profile_countries = {c for c, _ in profile['top_countries']}
    matched_countries = [c for c in countries if c in profile_countries]
    if matched_countries:
        reasons.append(f"产地「{'/'.join(matched_countries[:2])}」与你常看的一致")

    # Director match with personal rating context
    if any(d in profile['top_directors'] for d in directors):
        matched_dir = next((d for d in directors if d in profile['top_directors']), None)
        if matched_dir:
            # Find how user rated this director's works
            if high_rated:
                dir_rated = [r for r in high_rated if matched_dir in split_multi(r.get('directors') or '')]
                if dir_rated:
                    top = max(r.get('my_rating') or 0 for r in dir_rated)
                    reasons.append(f"导演{matched_dir}的作品你曾给 top{top} 分")
                else:
                    reasons.append(f"导演{matched_dir}的作品你给分很高")
            else:
                reasons.append(f"导演{matched_dir}的作品你给分很高")

    # Actor match
    matched_actors = [a for a in actors if a in profile['top_actors']]
    if len(matched_actors) >= 2:
        reasons.append(f"演员{matched_actors[0]}等是你熟悉的")
    elif len(matched_actors) == 1:
        reasons.append(f"有你眼熟的演员{matched_actors[0]}")

    # High rating on Douban
    if item['douban_rating'] and item['douban_rating'] >= 9.0:
        reasons.append(f"豆瓣 {item['douban_rating']} 分，超级口碑")
    elif item['douban_rating'] and item['douban_rating'] >= 8.5:
        reasons.append(f"豆瓣 {item['douban_rating']} 分，口碑扎实")
    elif item['douban_rating'] and item['douban_rating'] >= 8.0:
        reasons.append(f"豆瓣 {item['douban_rating']} 分，值得一看")

    # Year freshness for older items
    try:
        year = int(str(item.get('year') or 0)[:4])
        if year and year < 2000 and item.get('douban_rating'):
            reasons.append(f"{year}年经典老片，豆瓣仍有{item['douban_rating']}分")
    except:
        pass

    if not reasons:
        reasons.append(f"整体气质与你的观影偏好较为接近")

    return '；'.join(reasons) + '。'


def recommendation_candidates(conn, limit=30):
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
        # Skip if release date is in the future
        release_year = None
        if r['release_dates']:
            try:
                release_year = int(str(r['release_dates'])[:4])
            except:
                pass
        if release_year and release_year > 2026:
            continue

        score = (r['douban_rating'] or 0) * 0.8
        score += sum(genre_counter[g] for g in split_multi(r['genres'])) * 0.35
        score += sum(country_counter[c] for c in split_multi(r['countries'])) * 0.25
        score += kind_counter[r['kind'] or 'unknown'] * 0.5
        if r['kind'] == 'movie':
            score += 1.0
        ranked.append((score, r))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked[:limit]]


def cover_style(item):
    """Generate a deterministic gradient style for items without a cover image."""
    title = item['title'] or '?'
    hue = hash(title) % 360
    return f"background: linear-gradient(135deg, hsl({hue},55%,22%), hsl({(hue+40)%360},50%,15%));"


def cover_url(item):
    """Return cover URL or None. Works for sqlite3.Row and dict."""
    try:
        value = item['cover_url']
    except Exception:
        value = item.get('cover_url') if hasattr(item, 'get') else None
    return value or None


def rating_stars(rating):
    """Convert a 10-point Douban rating (0-10) to a 5-star display string."""
    if not rating:
        return ''
    stars = round(rating / 2)  # Convert 10-point to 5-star
    full = min(5, max(0, stars))
    return '★' * full + '☆' * (5 - full)


def first_genre(item):
    """Return the first genre from a slash-separated genres string."""
    genres = (item.get('genres') or '').strip()
    if not genres:
        return ''
    return genres.split('/')[0].strip()


@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()
    counts = dict(conn.execute('SELECT status, COUNT(*) FROM douban_watch_history GROUP BY status').fetchall())
    profile = load_profile(conn)
    rec_rows = recommendation_candidates(conn, limit=6)
    high_rated = [dict(r) for r in conn.execute(
        'SELECT * FROM douban_watch_history WHERE status="collect" AND my_rating >= 4'
    ).fetchall()]
    recs = []
    for r in rec_rows:
        rec = dict(r)
        rec['_reason'] = make_recommendation_reason(r, profile, high_rated)
        rec['_cover_style'] = cover_style(r)
        rec['_cover_url'] = cover_url(r)
        rec['_stars'] = rating_stars(rec.get('douban_rating'))
        rec['_first_genre'] = first_genre(rec)
        recs.append(rec)
    recent_rows = conn.execute('SELECT * FROM douban_watch_history WHERE status="collect" ORDER BY watched_date DESC LIMIT 8').fetchall()
    recent = []
    for r in recent_rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        recent.append(item)
    return templates.TemplateResponse('index.html', {
        'request': request,
        'counts': counts,
        'profile': profile,
        'recs': recs,
        'recent': recent,
    })


@app.get('/library', response_class=HTMLResponse)
def library(request: Request, status: str = Query('collect'), kind: str = Query('all'), q: str = Query(''), sort: str = Query('date')):
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
    if sort == 'rating':
        sql += ' ORDER BY douban_rating DESC, watched_date DESC LIMIT 200'
    elif sort == 'year':
        sql += ' ORDER BY year DESC, watched_date DESC LIMIT 200'
    elif sort == 'title':
        sql += ' ORDER BY title ASC LIMIT 200'
    else:
        sql += ' ORDER BY watched_date DESC, douban_rating DESC LIMIT 200'
    rows = conn.execute(sql, params).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item['_cover_style'] = cover_style(r)
        item['_cover_url'] = cover_url(r)
        item['_stars'] = rating_stars(item.get('douban_rating'))
        item['_first_genre'] = first_genre(item)
        items.append(item)
    return templates.TemplateResponse('library.html', {
        'request': request,
        'items': items,
        'status': status,
        'kind': kind,
        'q': q,
        'sort': sort,
    })


@app.get('/recommendations', response_class=HTMLResponse)
def recommendations(request: Request, sort: str = Query('score')):
    conn = get_conn()
    profile = load_profile(conn)
    recs = recommendation_candidates(conn, limit=60)
    high_rated = [dict(r) for r in conn.execute(
        'SELECT * FROM douban_watch_history WHERE status="collect" AND my_rating >= 4'
    ).fetchall()]
    # Attach reasons and scores
    recs_with_reason = []
    for r in recs:
        rec = dict(r)
        rec['_reason'] = make_recommendation_reason(r, profile, high_rated)
        rec['_cover_style'] = cover_style(r)
        rec['_cover_url'] = cover_url(r)
        rec['_stars'] = rating_stars(rec.get('douban_rating'))
        rec['_first_genre'] = first_genre(rec)
        # Compute match score
        genre_counter = Counter(g for g, _ in profile['top_genres'])
        country_counter = Counter(c for c, _ in profile['top_countries'])
        rec['_score'] = (
            (rec['douban_rating'] or 0) * 0.8 +
            sum(genre_counter[g] for g in split_multi(rec['genres'])) * 0.35 +
            sum(country_counter[c] for c in split_multi(rec['countries'])) * 0.25
        )
        recs_with_reason.append(rec)

    # Sort
    if sort == 'rating':
        recs_with_reason.sort(key=lambda x: x.get('douban_rating') or 0, reverse=True)
    elif sort == 'year':
        recs_with_reason.sort(key=lambda x: x.get('year') or 0, reverse=True)
    elif sort == 'random':
        random.shuffle(recs_with_reason)
    else:
        recs_with_reason.sort(key=lambda x: x['_score'], reverse=True)

    recs_with_reason = recs_with_reason[:24]
    # tonight pick: random from top-10 (true daily surprise, distinct from ranked list)
    tonight_pick = random.choice(recs_with_reason[:10]) if len(recs_with_reason) >= 10 else (recs_with_reason[0] if recs_with_reason else None)
    return templates.TemplateResponse('recommendations.html', {
        'request': request,
        'recs': recs_with_reason,
        'surprise': dict(tonight_pick) if tonight_pick else None,
        'today_pick': dict(tonight_pick) if tonight_pick else None,
        'sort': sort,
        'last_updated': datetime.now().strftime('%H:%M'),
    })


@app.get('/api/surprise', response_class=JSONResponse)
def surprise_me():
    """Return a random recommendation from the top candidates."""
    conn = get_conn()
    profile = load_profile(conn)
    recs = recommendation_candidates(conn, limit=30)
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


@app.post('/api/watch/{subject_id}', response_class=JSONResponse)
def mark_watched(subject_id: str):
    """Mark an item as watched, or re-watch if already watched."""
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')
    now = datetime.now().strftime('%Y-%m-%d')
    current_count = (item['watch_count'] or 1)
    # If user is marking as watched via this button, record it as a watch action
    conn.execute(
        'UPDATE douban_watch_history SET status="collect", watched_date=?, watch_count=? WHERE subject_id=?',
        (now, max(current_count, 1), subject_id)
    )
    conn.commit()
    return {'ok': True, 'subject_id': subject_id, 'watched_date': now, 'watch_count': max(current_count, 1)}


@app.post('/api/rewatch/{subject_id}', response_class=JSONResponse)
def add_rewatch(subject_id: str):
    """Record another watch of an item (increments watch_count, adds timestamp)."""
    conn = get_conn()
    item = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    if not item:
        raise HTTPException(404, 'Item not found')
    now = datetime.now().strftime('%Y-%m-%d')
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
def edit_item(subject_id: str, my_rating: int = None, comment: str = None, watched_date: str = None, watch_count: int = None):
    """Edit an item: rating, comment, watched date, watch count. Marks source as user-edited."""
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
    if watch_count is not None:
        conn.execute('UPDATE douban_watch_history SET watch_count=? WHERE subject_id=?', (watch_count, subject_id))
    conn.commit()
    updated = conn.execute('SELECT * FROM douban_watch_history WHERE subject_id=?', (subject_id,)).fetchone()
    return dict(updated)
