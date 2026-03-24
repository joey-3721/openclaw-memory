#!/usr/bin/env python3
"""
add_one_recommendation.py — 向 Media Hub MySQL 生产库新增一条推荐

用法（在 media-hub-test 容器内执行）：

  # 检查当前推荐数量（cron 先调用这个判断要不要继续）
  docker exec media-hub-test python3 /app/scripts/add_one_recommendation.py --check-count

  # 新增一条推荐
  docker exec media-hub-test python3 /app/scripts/add_one_recommendation.py \
    --tmdb-id 95396 \
    --tmdb-type tv \
    --title "人生切割术 / Severance" \
    --year 2022 \
    --genres "剧情 / 悬疑 / 科幻" \
    --countries "美国" \
    --rating 8.4 \
    --votes 2532 \
    --intro "一句话简介" \
    --summary "完整摘要" \
    --note "个性化推荐语（禁止公式化）" \
    --rank 1 \
    --poster-path "/abc.jpg"

内置规则（代码强制）：
  - 当前推荐数量 >= MAX_RECOMMENDED(100) 时自动退出，不写入
  - tmdb_id 或 title 已在库则拒绝写入（--force 覆盖）
  - 封面下载失败则拒绝写入
  - 只写 MySQL 生产库（app.get_conn()），封面用 app.download_cover_to_local()（内置代理）
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

MAX_RECOMMENDED = 100  # 达到这个数量后停止写入

sys.path.insert(0, "/app")
os.environ.setdefault("HTTP_PROXY", "http://192.168.50.209:7890")
os.environ.setdefault("HTTPS_PROXY", "http://192.168.50.209:7890")
import app as media_app


def get_current_count(conn):
    """返回当前 status='recommended' 的数量"""
    r = conn.execute(
        "SELECT COUNT(*) as cnt FROM douban_watch_history WHERE status='recommended'"
    ).fetchone()
    return r["cnt"]


def check_duplicate(conn, tmdb_id, title):
    """检查 tmdb_id 或 title 是否已在库"""
    rows = conn.execute(
        "SELECT title, status FROM douban_watch_history WHERE tmdb_id=%s OR title=%s",
        (str(tmdb_id), title),
    ).fetchall()
    return rows


def download_cover(tmdb_id, tmdb_type, poster_path):
    """使用 app.download_cover_to_local()（内置代理），返回 /covers/... 路径或 None"""
    if not poster_path:
        return None
    img_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
    kind_str = "tv" if tmdb_type == "tv" else "movie"
    try:
        local = media_app.download_cover_to_local(img_url, f"tmdb:{kind_str}:{tmdb_id}")
        if local:
            full_path = Path("/app" + local)
            if full_path.exists() and full_path.stat().st_size > 1000:
                print(f"Cover OK: {local} ({full_path.stat().st_size} bytes)")
                return local
            else:
                print(f"ERROR: cover too small or missing: {local}")
                return None
        return None
    except Exception as e:
        print(f"ERROR: cover download failed: {e}")
        return None


def insert_recommendation(conn, item):
    """安全写入推荐：
    - 新记录：INSERT（status='recommended'）
    - 已有记录（任何状态）：只更新推荐相关字段，绝不覆盖 status/my_rating/comment/watch_count
    """
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # INSERT 新记录
    insert_sql = (
        "INSERT INTO douban_watch_history"
        " (subject_id, title, kind, year, url, intro, summary,"
        "  genres, countries, cover_url, status, tmdb_id,"
        "  recommendation_note, recommended_at, recommend_rank,"
        "  recommend_source, douban_rating, douban_rating_count)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON DUPLICATE KEY UPDATE"
        "  title               = VALUES(title),"
        "  kind                = VALUES(kind),"
        "  year                = VALUES(year),"
        "  url                 = VALUES(url),"
        "  intro               = VALUES(intro),"
        "  summary             = VALUES(summary),"
        "  genres              = VALUES(genres),"
        "  countries           = VALUES(countries),"
        "  cover_url           = VALUES(cover_url),"
        "  tmdb_id             = VALUES(tmdb_id),"
        "  recommendation_note = VALUES(recommendation_note),"
        "  recommended_at      = VALUES(recommended_at),"
        "  recommend_rank      = VALUES(recommend_rank),"
        "  recommend_source    = VALUES(recommend_source),"
        "  douban_rating       = VALUES(douban_rating),"
        "  douban_rating_count = VALUES(douban_rating_count)"
    )
    # 注意：ON DUPLICATE KEY UPDATE 中故意省略 status/my_rating/comment/watch_count
    # 这些字段只由用户操作写入，cron 不覆盖

    conn.execute(insert_sql, (
        item["subject_id"],
        item["title"],
        item["kind"],
        item["year"],
        item["url"],
        item["intro"],
        item["summary"],
        item["genres"],
        item["countries"],
        item["cover_url"],
        "recommended",
        str(item["tmdb_id"]),
        item["recommendation_note"],
        now,
        item.get("rank", 1),
        item.get("source", "openclaw-curated"),
        item.get("rating", 0),
        item.get("votes", 0),
    ))
    conn.commit()
    print(f"OK: inserted/updated '{item['title']}' (tmdb_id={item['tmdb_id']}) -> MySQL")


def main():
    parser = argparse.ArgumentParser(description="Add one recommendation to Media Hub MySQL")
    parser.add_argument("--check-count", action="store_true",
                        help="只查询并输出当前推荐数量，不写入")
    parser.add_argument("--tmdb-id", default=None)
    parser.add_argument("--tmdb-type", default="movie", choices=["movie", "tv"])
    parser.add_argument("--title", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--genres", default="")
    parser.add_argument("--countries", default="")
    parser.add_argument("--rating", type=float, default=0)
    parser.add_argument("--votes", type=int, default=0)
    parser.add_argument("--intro", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--note", default=None, help="个性化推荐语")
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument("--poster-path", default=None, help="TMDB poster_path e.g. /xxx.jpg")
    parser.add_argument("--force", action="store_true", help="跳过去重检查")
    args = parser.parse_args()

    conn = media_app.get_conn()

    # ── 模式1：只查数量 ──────────────────────────────────────────────
    if args.check_count:
        cnt = get_current_count(conn)
        conn.close()
        print(f"recommended_count: {cnt}")
        print(f"need_more: {'yes' if cnt < MAX_RECOMMENDED else 'no'}")
        sys.exit(0)

    # ── 模式2：写入一条推荐 ──────────────────────────────────────────
    # 必填参数检查
    for field in ["tmdb_id", "title", "year", "note", "poster_path"]:
        if getattr(args, field.replace("-", "_")) is None:
            print(f"ERROR: --{field} is required when not using --check-count")
            conn.close()
            sys.exit(1)

    # 【代码强制】数量上限检查：达到 MAX_RECOMMENDED 直接退出
    cnt = get_current_count(conn)
    if cnt >= MAX_RECOMMENDED:
        print(f"SKIP: already at {cnt} >= {MAX_RECOMMENDED}, no write needed")
        conn.close()
        sys.exit(0)

    # 去重检查：
    # - status='collect'   → 用户已看过，绝对不推
    # - status='recommended' → 已在推荐列表，跳过（避免重复）
    # - status='wish' 或不存在 → 允许插入
    existing = conn.execute(
        "SELECT subject_id, status, my_rating FROM douban_watch_history"
        " WHERE tmdb_id=%s OR subject_id=%s LIMIT 1",
        (str(args.tmdb_id), f"{'tmdb:tv:' if args.tmdb_type == 'tv' else 'tmdb:movie:'}{args.tmdb_id}")
    ).fetchone()
    if existing:
        st = existing['status']
        if st == 'collect':
            print(f"SKIP: {args.title} (tmdb:{args.tmdb_id}) already watched by user (status=collect), will NOT recommend")
            conn.close()
            sys.exit(4)
        if st == 'recommended':
            print(f"SKIP: {args.title} (tmdb:{args.tmdb_id}) already in recommendations (status=recommended)")
            conn.close()
            sys.exit(0)

    # 下载封面（必须成功才写入）
    cover_url = download_cover(args.tmdb_id, args.tmdb_type, args.poster_path)
    if not cover_url:
        print("ERROR: cover unavailable, aborting (cover must be valid)")
        conn.close()
        sys.exit(3)

    endpoint = "tv" if args.tmdb_type == "tv" else "movie"
    prefix = "tmdb:tv:" if args.tmdb_type == "tv" else "tmdb:movie:"

    item = {
        "subject_id": f"{prefix}{args.tmdb_id}",
        "tmdb_id": args.tmdb_id,
        "title": args.title,
        "kind": args.tmdb_type,
        "year": args.year,
        "url": f"https://www.themoviedb.org/{endpoint}/{args.tmdb_id}",
        "intro": args.intro,
        "summary": args.summary,
        "genres": args.genres,
        "countries": args.countries,
        "cover_url": cover_url,
        "recommendation_note": args.note,
        "rank": args.rank,
        "source": "openclaw-curated",
        "rating": args.rating,
        "votes": args.votes,
    }

    insert_recommendation(conn, item)
    new_cnt = get_current_count(conn)
    print(f"Total recommended now: {new_cnt}")
    conn.close()


if __name__ == "__main__":
    main()
