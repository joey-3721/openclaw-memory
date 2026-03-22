#!/usr/bin/env python3
"""
smart_recommend.py
每次心跳时运行：
1. 读取用户最近观看历史（collect）和 dislike 理由
2. 从 TMDB 按用户口味挑候选
3. 针对每个候选：搜索剧情 + 为什么火
4. 调用大模型写针对用户的个性化推荐语
5. 写入数据库 status='recommended'

只写生产库 /app/data/douban_media.db
"""
import os, sys, json, random, re
from datetime import datetime

# 强制生产路径
DB_PATH = os.environ.get('MEDIA_HUB_DB', '/app/data/douban_media.db')
SAFE_PREFIX = ('/app/data', '/app/covers')
if not DB_PATH.startswith(SAFE_PREFIX):
    raise RuntimeError(f'[smart_recommend] 危险：拒绝写入 {DB_PATH}，只允许 /app/data/*')

sys.path.insert(0, '/app')
os.environ.setdefault('MEDIA_HUB_DB', DB_PATH)
os.environ.setdefault('MEDIA_HUB_COVERS_DIR', '/app/covers')
os.environ.setdefault('HTTP_PROXY', 'http://192.168.50.209:7890')
os.environ.setdefault('HTTPS_PROXY', 'http://192.168.50.209:7890')

import app
import requests

TMDB_KEY = app.read_tmdb_key()
PROXIES = {'http': 'http://192.168.50.209:7890', 'https': 'http://192.168.50.209:7890'}
LLM_URL = os.environ.get('LLM_URL', 'http://localhost:11434/api/generate')
LLM_MODEL = os.environ.get('LLM_MODEL', 'qwen2.5')

# ─────────────────────────────────────────────────────────
# 1. 读取用户口味
# ─────────────────────────────────────────────────────────
def load_user_taste():
    conn = app.get_conn()
    rows = conn.execute('''
        SELECT subject_id, title, kind, my_rating, comment, watched_date,
               genres, countries, directors, actors, recommendation_note, dislike_reason
        FROM douban_watch_history
        WHERE status IN ("collect", "wish") AND COALESCE(recommend_feedback, "") != "dislike"
        ORDER BY watched_date DESC LIMIT 200
    ''').fetchall()

    high_rated = [r for r in rows if (r['my_rating'] or 0) >= 4]
    low_rated = [r for r in rows if (r['my_rating'] or 0) <= 2]
    disliked = conn.execute('''
        SELECT subject_id, title, kind, my_rating, comment, dislike_reason, genres
        FROM douban_watch_history
        WHERE COALESCE(recommend_feedback, "") = "dislike" OR COALESCE(dislike_reason, "") != ""
        ORDER BY feedback_updated_at DESC LIMIT 30
    ''').fetchall()

    # 统计高频题材/国家
    genre_counter = __import__('collections', fromlist=['Counter']).Counter()
    country_counter = __import__('collections', fromlist=['Counter']).Counter()
    watched_titles = set()
    franchise_blacklist = set()

    NEG_KW = ['看睡着', '昏昏欲睡', '催眠', '太慢', '墨迹', '无聊', '不吸引', '尴尬', '不知所云', '磨磨叽叽', '催眠', '困']

    for r in rows:
        t = str(r['title'] or '').strip()
        if t:
            watched_titles.add(app.normalize_title(t))
        if (r['my_rating'] or 0) >= 4:
            for g in app.split_tokens(str(r['genres'] or '')):
                genre_counter[g] += 1
            for c in app.split_tokens(str(r['countries'] or '')):
                country_counter[c] += 1
        if (r['my_rating'] or 0) <= 2:
            for kw in NEG_KW:
                if kw in str(r['comment'] or ''):
                    franchise_blacklist.add(str(r['title'] or ''))

    for r in disliked:
        for kw in NEG_KW:
            if kw in str(r.get('comment') or '') or kw in str(r.get('dislike_reason') or ''):
                franchise_blacklist.add(str(r['title'] or ''))
        bad_franchises = ['哥斯拉', '金刚', '环太平洋', '流浪地球', '唐探', '柯南', '鱿鱼游戏', '复仇者联盟', '速度与激情']
        for b in bad_franchises:
            if b in str(r.get('title') or ''):
                franchise_blacklist.add(b)

    top_genres = [g for g, _ in genre_counter.most_common(6)]
    top_countries = [c for c, _ in country_counter.most_common(4)]

    # 构建不喜欢题材关键词
    dislike_topics = set()
    for r in disliked:
        for kw in str(r.get('dislike_reason') or '').split():
            if len(kw) >= 2:
                dislike_topics.add(kw)
        for kw in NEG_KW:
            if kw in str(r.get('dislike_reason') or '') or kw in str(r.get('comment') or ''):
                dislike_topics.add(kw)

    return {
        'watched_titles': watched_titles,
        'high_rated': [dict(r) for r in high_rated],
        'low_rated': [dict(r) for r in low_rated],
        'disliked': [dict(r) for r in disliked],
        'top_genres': top_genres,
        'top_countries': top_countries,
        'dislike_topics': list(dislike_topics)[:20],
        'franchise_blacklist': list(franchise_blacklist),
        'recent_high': [dict(r)['title'] for r in high_rated[:8]],
    }

# ─────────────────────────────────────────────────────────
# 2. 从 TMDB 拉候选
# ─────────────────────────────────────────────────────────
def fetch_tmdb_candidates(taste, max_candidates=40):
    """按用户口味画像从 TMDB discover 拉候选，过滤已看/不喜欢."""
    watched_norm = {app.normalize_title(t) for t in taste['watched_titles']}
    blacklist_norm = {app.normalize_title(t) for t in taste['franchise_blacklist']}
    all_bad = watched_norm | blacklist_norm

    slices = [
        {'media': 'movie', 'sort': 'popularity.desc', 'year_gte': '2022-01-01'},
        {'media': 'movie', 'sort': 'vote_average.desc', 'year_gte': '2023-01-01', 'vote_count_gte': 800},
        {'media': 'tv', 'sort': 'popularity.desc', 'year_gte': '2022-01-01'},
        {'media': 'tv', 'sort': 'vote_average.desc', 'year_gte': '2023-01-01', 'vote_count_gte': 600},
    ]

    candidates = []
    for sl in slices:
        params = {
            'api_key': TMDB_KEY,
            'sort_by': sl['sort'],
            'language': 'zh-CN',
            'include_adult': 'false',
            'page': random.randint(1, 4),
        }
        date_key = 'primary_release_date.gte' if sl['media'] == 'movie' else 'first_air_date.gte'
        params[date_key] = sl['year_gte']
        if 'vote_count_gte' in sl:
            params['vote_count.gte'] = sl['vote_count_gte']
        try:
            resp = requests.get(
                f"https://api.themoviedb.org/3/discover/{sl['media']}",
                params=params, proxies=PROXIES, timeout=20
            )
            data = resp.json()
        except Exception as e:
            print(f'[TMDB ERR] {e}')
            continue

        for item in (data.get('results') or []):
            title = item.get('title') or item.get('name') or ''
            norm = app.normalize_title(title)
            if norm in all_bad:
                continue
            # 过滤不喜欢题材
            overview = item.get('overview') or ''
            for kw in taste['dislike_topics']:
                if kw in overview or kw in title:
                    continue

            genre_ids = item.get('genre_ids', [])
            candidates.append({
                'tmdb_id': str(item['id']),
                'media_type': sl['media'],
                'title': title,
                'year': (item.get('release_date') or item.get('first_air_date') or '')[:4],
                'overview': overview,
                'vote_average': item.get('vote_average') or 0,
                'popularity': item.get('popularity') or 0,
                'genre_ids': genre_ids,
                'poster_path': item.get('poster_path'),
            })
            if len(candidates) >= max_candidates:
                break

    # 打分排序（偏好题材加权）
    genre_weight = {'剧情': 1.3, '悬疑': 1.3, '惊悚': 1.2, '科幻': 1.2,
                    '喜剧': 0.9, '恐怖': 0.8, '灾难': 0.9}
    scored = []
    for c in candidates:
        gbonus = sum(genre_weight.get(str(g), 1.0) for g in c['genre_ids'])
        score = c['vote_average'] * 0.4 + c['popularity'] * 0.001 + gbonus
        scored.append((score, random.random(), c))
    scored.sort(reverse=True)
    return [c for _, _, c in scored[:20]]

# ─────────────────────────────────────────────────────────
# 3. 搜索剧情和热度
# ─────────────────────────────────────────────────────────
def search_plot(title, year):
    """用 Google 风格搜索 title + 剧情/评价."""
    try:
        # 用 TMDB 中文详情补充剧情
        resp = requests.get(
            f'https://api.themoviedb.org/3/search/{random.choice(["movie","tv"])}',
            params={'api_key': TMDB_KEY, 'query': title, 'language': 'zh-CN'},
            proxies=PROXIES, timeout=15
        )
        data = resp.json()
        results = data.get('results') or []
        if results:
            top = results[0]
            detail_key = 'movie' if 'release_date' in top else 'tv'
            detail = requests.get(
                f'https://api.themoviedb.org/3/{detail_key}/{top["id"]}',
                params={'api_key': TMDB_KEY, 'language': 'zh-CN'},
                proxies=PROXIES, timeout=15
            ).json()
            return {
                'plot': top.get('overview') or detail.get('overview') or '',
                'genres': [g['name'] for g in detail.get('genres', [])],
                'rating': top.get('vote_average') or 0,
                'year': (top.get('release_date') or top.get('first_air_date') or year)[:4],
            }
    except Exception as e:
        print(f'[search_plot ERR] {title}: {e}')
    return {'plot': '', 'genres': [], 'rating': 0, 'year': year}

# ─────────────────────────────────────────────────────────
# 4. 调用大模型写推荐语
# ─────────────────────────────────────────────────────────
def write_recommendation_note(candidate, taste, plot_info):
    """专门调用大模型，为这个用户写一条个性化推荐语."""
    recent = ', '.join(taste['recent_high'][:6]) or '暂无'
    dislike = ', '.join(taste['dislike_topics'][:8]) or '暂无'
    genres = ', '.join(candidate.get('genres', candidate.get('genre_names', []))) or '未知'
    plot = plot_info.get('plot', '') or candidate.get('overview', '') or '暂无剧情简介'

    prompt = f"""你是一个资深影视推荐编辑，正在为一位有品位的用户写推荐语。

【用户背景】
- 最近喜欢的电影：《{recent}》
- 反感题材/关键词：{dislike}
- 偏好题材：{', '.join(taste['top_genres'][:4]) or '无明确偏好'}

【待推荐内容】
- 标题：{candidate.get('title', '')}
- 类型：{genres}
- 年份：{candidate.get('year', '')}
- 剧情简介：{plot[:300]}

【写作要求】
1. 只写一段，40-80字
2. 必须结合用户背景，指出"为什么此刻适合他"
3. 绝对不要写"如果你喜欢XX"这种套话
4. 绝对不要写"该片讲述了..."这种复述剧情的开头
5. 要有观点、有钩子，让用户想点开
6. 语气自然，像一个懂电影的朋友在推荐
7. 只输出推荐语，不要前缀后缀

【输出格式】
只输出推荐语本身，不要任何引号、括号、或附加说明。"""

    try:
        resp = requests.post(
            LLM_URL,
            json={'model': LLM_MODEL, 'prompt': prompt, 'stream': False, 'options': {'temperature': 0.8, 'num_predict': 200}},
            proxies=PROXIES, timeout=60
        )
        result = resp.json()
        note = (result.get('response') or '').strip()
        # 清理引号和多余空白
        note = re.sub(r'^["""\'\s]+|["""\'\s]+$', '', note)
        return note if len(note) >= 10 else None
    except Exception as e:
        print(f'[LLM ERR] {candidate.get("title")}: {e}')
        return None

# ─────────────────────────────────────────────────────────
# 5. 写入数据库
# ─────────────────────────────────────────────────────────
COLS = [
    'subject_id','tmdb_id','title','kind','year','intro','douban_rating',
    'cover_url','recommendation_note','status','recommended_at',
    'recommend_rank','recommend_source','url'
]

def insert_recommendation(conn, item):
    cols = [c for c in COLS if c in item and item[c] is not None]
    vals = [item[c] for c in cols]
    placeholders = ','.join(['?'] * len(cols))
    conn.execute(f'INSERT INTO douban_watch_history ({",".join(cols)}) VALUES ({placeholders})', vals)

# ─────────────────────────────────────────────────────────
# 5. 主流程
# ─────────────────────────────────────────────────────────
def main():
    print(f'[{datetime.now().strftime("%H:%M:%S")}] 开始智能推荐流程...')
    taste = load_user_taste()
    print(f'  口味画像：高评分{len(taste["high_rated"])}部, 不喜欢{len(taste["disliked"])}部, 偏好题材{taste["top_genres"]}')

    # 检查当前推荐数量
    conn = app.get_conn()
    current = conn.execute(
        "SELECT COUNT(*) FROM douban_watch_history WHERE status='recommended'"
    ).fetchone()[0]
    print(f'  当前推荐数量: {current}')
    if current >= 100:
        print('  已达阈值100条，跳过新增')
        return

    # 拉候选
    candidates = fetch_tmdb_candidates(taste, max_candidates=20)
    print(f'  候选数量: {len(candidates)}')

    # 已有推荐的 tmdb_id 避免重复
    existing = {r['tmdb_id'] for r in conn.execute(
        "SELECT tmdb_id FROM douban_watch_history WHERE tmdb_id IS NOT NULL AND tmdb_id != ''"
    ).fetchall()}
    new_items = []
    for c in candidates:
        if c['tmdb_id'] in existing:
            continue
        print(f'  处理: {c["title"]}')
        plot_info = search_plot(c['title'], c.get('year', ''))
        note = write_recommendation_note(c, taste, plot_info)
        if not note:
            note = f'值得一看的{c.get("media_type", "影视")}作品。'
        item = {
            'subject_id': f'tmdb:{c["media_type"]}:{c["tmdb_id"]}',
            'tmdb_id': c['tmdb_id'],
            'title': c['title'],
            'kind': c['media_type'],
            'year': c.get('year'),
            'intro': plot_info.get('plot', ''),
            'douban_rating': round(c.get('vote_average', 0) / 10, 2) if c.get('vote_average') else None,
            'cover_url': f"https://image.tmdb.org/t/p/w500{c['poster_path']}" if c.get('poster_path') else None,
            'recommendation_note': note,
            'status': 'recommended',
            'recommended_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'recommend_rank': len(new_items),
            'recommend_source': 'smart_v1',
        }
        new_items.append(item)
        if len(new_items) >= 1:
            break

    if new_items:
        for item in new_items:
            existing_row = conn.execute(
                'SELECT subject_id FROM douban_watch_history WHERE subject_id=?',
                (item['subject_id'],)
            ).fetchone()
            if not existing_row:
                insert_recommendation(conn, item)
                print(f'  ✅ 新增推荐: {item["title"]} - {item["recommendation_note"][:30]}...')
        conn.commit()
        print(f'  完成，新增{len(new_items)}条')
    else:
        print('  没有新增推荐')

if __name__ == '__main__':
    main()
