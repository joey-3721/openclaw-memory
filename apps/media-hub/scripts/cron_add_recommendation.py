#!/usr/bin/env python3
"""
cron_add_recommendation.py
每30分钟自动追加一条推荐到本地缓存。
读取用户最近观看/评分历史，结合TMDB发现候选，
生成hook风格推荐语，写入主库 status='recommended'。

安全规则：只写入 MEDIA_HUB_DB 指定的路径，
不允许覆盖任何 workspace 副本或开发路径。
"""
import os, sys, random, re
from datetime import datetime, timedelta

# 强制只写生产库，禁止写入 workspace 开发副本
DB_PATH = os.environ.get('MEDIA_HUB_DB', '/app/data/douban_media.db')
SAFE_PATHS = ('/app/data', '/app/covers')
if not DB_PATH.startswith(SAFE_PATHS):
    raise RuntimeError(
        f'[cron_add_recommendation] 危险：拒绝写入非生产路径 {DB_PATH}！'
        '只允许写入 /app/data/* 或通过 docker exec 在容器内运行。'
    )

sys.path.insert(0, '/app')
os.environ.setdefault('MEDIA_HUB_DB', DB_PATH)
os.environ.setdefault('MEDIA_HUB_COVERS_DIR', '/app/covers')
os.environ.setdefault('HTTP_PROXY', 'http://192.168.50.209:7890')
os.environ.setdefault('HTTPS_PROXY', 'http://192.168.50.209:7890')

import app
import requests

TMDB_KEY = app.read_tmdb_key()
PROXIES = {'http': 'http://192.168.50.209:7890', 'https': 'http://192.168.50.209:7890'}

# ---------------------------------------------------------------------
# 口味画像
# ---------------------------------------------------------------------
def load_profile(conn):
    rows = conn.execute(
        'SELECT * FROM douban_watch_history WHERE status="collect" AND my_rating IS NOT NULL'
    ).fetchall()
    high = [r for r in rows if (r['my_rating'] or 0) >= 4]
    low = [r for r in rows if (r['my_rating'] or 0) <= 2]
    genre_counter = __import__('collections', fromlist=['Counter']).Counter()
    country_counter = __import__('collections', fromlist=['Counter']).Counter()
    dislike_genres = __import__('collections', fromlist=['Counter']).Counter()
    dislike_keywords = __import__('collections', fromlist=['Counter']).Counter()
    watched_titles = set()
    low_franchise = set()
    for r in rows:
        t = str(r['title'] or '').strip()
        if t:
            watched_titles.add(app.normalize_title(t))
        genres_str = str(r['genres'] or '')
        countries_str = str(r['countries'] or '')
        if (r['my_rating'] or 0) >= 4:
            for g in app.split_tokens(genres_str):
                genre_counter[g] += 1
            for c in app.split_tokens(countries_str):
                country_counter[c] += 1
        if (r['my_rating'] or 0) <= 2:
            for kw in ['看睡着', '昏昏欲睡', '催眠', '太慢', '墨迹', '无聊', '不吸引', '尴尬', '不知所云', '磨磨叽叽']:
                if kw in str(r['comment'] or ''):
                    dislike_keywords[kw] += 1
            for bad in ['哥斯拉', '金刚', '环太平洋', '流浪地球', '唐探', '柯南', '鱿鱼游戏']:
                if bad in (r['title'] or ''):
                    low_franchise.add(bad)
    top_genres = genre_counter.most_common(8)
    top_countries = country_counter.most_common(6)
    return {
        'watched_titles': watched_titles,
        'top_genres': top_genres,
        'top_countries': top_countries,
        'dislike_keywords': dislike_keywords,
        'low_franchise': low_franchise,
    }


# ---------------------------------------------------------------------
# 候选抓取
# ---------------------------------------------------------------------
def fetch_candidates(profile, max_candidates=30):
    """从TMDB discover抓候选，排除已看/老片/烂 franchise。"""
    candidates = []
    slices = [
        {'media': 'movie', 'sort': 'popularity.desc',  'year_gte': '2022-01-01'},
        {'media': 'movie', 'sort': 'vote_average.desc', 'year_gte': '2023-01-01', 'vote_count_gte': 1000},
        {'media': 'tv',    'sort': 'popularity.desc',  'year_gte': '2022-01-01'},
        {'media': 'tv',    'sort': 'vote_average.desc', 'year_gte': '2023-01-01', 'vote_count_gte': 800},
    ]
    for sl in slices:
        params = {
            'api_key': TMDB_KEY,
            'sort_by': sl['sort'],
            'language': 'zh-CN',
            'include_adult': 'false',
            'page': random.randint(1, 3),
        }
        params['primary_release_date.gte' if sl['media'] == 'movie' else 'first_air_date.gte'] = sl['year_gte']
        if 'vote_count_gte' in sl:
            params['vote_count.gte'] = sl['vote_count_gte']
        url = f"https://api.themoviedb.org/3/discover/{sl['media']}"
        try:
            r = requests.get(url, params=params, proxies=PROXIES, timeout=25)
            for raw in (r.json().get('results') or []):
                title = raw.get('title') or raw.get('name') or ''
                # 必须有中文
                if not re.search(r'[\u4e00-\u9fff]', title):
                    continue
                # 排除已看
                if app.normalize_title(title) in profile['watched_titles']:
                    continue
                # 排除老片（默认2018前降权，太老跳过）
                release = raw.get('release_date') or raw.get('first_air_date') or ''
                try:
                    yr = int(release[:4])
                except:
                    yr = 0
                if yr < 2018:
                    continue
                # 排除烂 franchise
                if any(bad in title for bad in profile['low_franchise']):
                    continue
                # 打分
                vote_avg = raw.get('vote_average') or 0
                vote_cnt = raw.get('vote_count') or 0
                genre_ids = raw.get('genre_ids') or []
                genre_overlap = sum(
                    cnt for g, cnt in profile['top_genres']
                    if g in genre_ids
                )
                score = vote_avg * 0.6 + (vote_cnt / 1000) * 0.2 + genre_overlap * 0.2
                if yr < 2022:
                    score -= 1.5
                raw['_score'] = score
                raw['_yr'] = yr
                candidates.append((sl['media'], raw))
        except Exception as e:
            print(f'[cron] fetch error: {e}', file=sys.stderr)
    # 去重&排序
    seen = set()
    deduped = []
    for media, raw in candidates:
        t = raw.get('title') or raw.get('name', '')
        if t not in seen:
            seen.add(t)
            deduped.append((media, raw))
    deduped.sort(key=lambda x: x[1].get('_score', 0), reverse=True)
    return deduped[:max_candidates]


# ---------------------------------------------------------------------
# 推荐语生成（hook风格，不用模板）
# ---------------------------------------------------------------------
REASON_TPLS = [
    '它的开局很像某种日常，但很快你就会发现这不是——{hook}。节奏很压，不给你走神的机会。',
    '{hook}。这是它最抓人的地方，也是你一旦开始就停不下来的原因。',
    '如果你喜欢{genre}类型的片，这部很可能让你一口气看完。开局钩子很重，{hook}。',
    '它有一个很危险的特点：看起来很平常，但越往后越让你放不下。{hook}',
    '{hook}。这是整部片最核心的那句话，也是你会被拽进去的原因。',
]

def make_reason(item, profile):
    title = item.get('title') or ''
    overview = str(item.get('overview') or item.get('intro') or '').strip()
    genres = app.split_tokens(item.get('genres') or '')
    top_genre = next((g for g, _ in profile['top_genres'] if g in genres), '这个题材')

    # 从简介里抽一句作为hook
    hook = ''
    if overview:
        # 取第一个句号或逗号前的完整小句
        s = re.sub(r'[\n\r]+', '', overview)
        cuts = re.split(r'[。；！？]', s)
        hook = next((c.strip() for c in cuts if len(c.strip()) > 15 and c.strip()), overview[:60])

    tpl = random.choice(REASON_TPLS)
    return tpl.format(hook=hook[:80], genre=top_genre)


# ---------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------
def main():
    conn = app.get_conn()
    profile = load_profile(conn)

    # 已有推荐里已有哪些标题
    existing = app.load_recommended_items(conn)
    existing_titles = {r.get('title') for r in existing}
    next_rank = len(existing) + 1

    # 抓候选
    candidates = fetch_candidates(profile)
    # 过滤已存在于缓存的
    candidates = [(m, r) for m, r in candidates if (r.get('title') or r.get('name', '')) not in existing_titles]

    if not candidates:
        print('[cron] no new candidates')
        return

    # 选得分最高的
    media, chosen = candidates[0]
    item = app.tmdb_to_item(chosen, media)
    title = chosen.get('title') or chosen.get('name', '')
    item['title'] = title
    item['year'] = chosen.get('_yr') or item.get('year')
    rating = chosen.get('vote_average', 0)
    votes = chosen.get('vote_count', 0)
    item['douban_rating'] = rating
    item['douban_rating_count'] = votes

    reason = make_reason(item, profile)
    item['_reason'] = reason
    item['_score'] = rating
    item['_cover_style'] = app.cover_style(item)
    item['_cover_url'] = app.cover_url(item)
    item['_stars'] = app.rating_stars(rating)
    item['_first_genre'] = app.first_genre(item)

    # 下载封面
    poster_url = app.tmdb_image_url(chosen.get('poster_path'))
    if poster_url and item.get('tmdb_id'):
        try:
            local_cover = app.download_cover_to_local(poster_url, f"tmdb:{item['tmdb_id']}")
            item['cover_url'] = local_cover
        except Exception:
            item['cover_url'] = poster_url
    else:
        item['cover_url'] = ''

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    item['recommendation_note'] = reason
    item['recommended_at'] = now
    item['recommend_rank'] = next_rank
    item['recommend_source'] = 'cron'
    saved = app.upsert_recommendation_item(conn, item, target_status='recommended')
    conn.execute('UPDATE douban_watch_history SET recommended_at=?, recommend_rank=?, recommend_source=? WHERE subject_id=?', (now, next_rank, 'cron', saved['subject_id']))
    conn.commit()
    print(f'[cron] added: {title} | rank {next_rank} | reason: {reason[:40]}...')


if __name__ == '__main__':
    main()
