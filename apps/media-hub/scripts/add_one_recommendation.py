#!/usr/bin/env python3
"""
add_one_recommendation.py — 向 Media Hub MySQL 生产库新增一条推荐

用法（必须在 media-hub-test 容器内执行）：
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
    --rank 1

安全规则：
  - 直接写入 MySQL 生产库（通过 app.get_conn()）
  - 自动下载封面到 /app/covers/
  - 自动去重（检查 tmdb_id + title 是否已存在）
  - 封面不可用时拒绝写入
"""

import argparse
import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

COVERS_DIR = Path(os.getenv("MEDIA_HUB_COVERS_DIR", "/app/covers"))

sys.path.insert(0, "/app")
import app as media_app


def get_tmdb_key():
    try:
        return media_app.read_tmdb_key()
    except Exception:
        secrets_path = Path("/app/config/secrets/tmdb.json")
        if secrets_path.exists():
            return json.loads(secrets_path.read_text()).get("api_key", "").strip()
        return os.getenv("TMDB_API_KEY", "")


def download_cover(tmdb_id, tmdb_type, poster_path=None):
    """Download cover from TMDB. Returns local /covers/... path or None."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    key = get_tmdb_key()

    if not poster_path and key:
        endpoint = "tv" if tmdb_type == "tv" else "movie"
        url = f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}?api_key={key}&language=zh-CN"
        try:
            resp = urllib.request.urlopen(url, context=ctx, timeout=15)
            data = json.loads(resp.read())
            poster_path = data.get("poster_path")
        except Exception as e:
            print(f"WARN: failed to fetch TMDB detail: {e}")

    if not poster_path:
        return None

    prefix = "tmdb_tv_" if tmdb_type == "tv" else "tmdb_"
    local_name = f"{prefix}{tmdb_id}.jpg"
    local_path = COVERS_DIR / local_name

    if local_path.exists() and local_path.stat().st_size > 1000:
        print(f"Cover already exists: {local_path} ({local_path.stat().st_size} bytes)")
        return f"/covers/{local_name}"

    img_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
    try:
        urllib.request.urlretrieve(img_url, str(local_path))
        size = local_path.stat().st_size
        if size < 1000:
            print(f"ERROR: cover too small ({size} bytes), likely broken")
            local_path.unlink(missing_ok=True)
            return None
        print(f"Cover downloaded: {local_path} ({size} bytes)")
        return f"/covers/{local_name}"
    except Exception as e:
        print(f"ERROR: failed to download cover: {e}")
        return None


def check_duplicate(conn, tmdb_id, title):
    """Check if item already exists in MySQL DB."""
    cur = conn.execute(
        "SELECT title, status FROM douban_watch_history WHERE tmdb_id=%s OR title=%s",
        (str(tmdb_id), title),
    )
    return cur.fetchall()


def insert_recommendation(conn, item):
    """Insert one recommendation into MySQL production DB via REPLACE INTO."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """REPLACE INTO douban_watch_history
        (subject_id, title, kind, year, url, intro, summary,
         genres, countries, cover_url, status, tmdb_id,
         recommendation_note, recommended_at, recommend_rank,
         recommend_source, douban_rating, douban_rating_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
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
        ),
    )
    conn.commit()
    print(f"OK: inserted '{item['title']}' as recommended (tmdb_id={item['tmdb_id']}) -> MySQL")


def main():
    parser = argparse.ArgumentParser(description="Add one recommendation to Media Hub MySQL")
    parser.add_argument("--tmdb-id", required=True)
    parser.add_argument("--tmdb-type", default="movie", choices=["movie", "tv"])
    parser.add_argument("--title", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--genres", default="")
    parser.add_argument("--countries", default="")
    parser.add_argument("--rating", type=float, default=0)
    parser.add_argument("--votes", type=int, default=0)
    parser.add_argument("--intro", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--note", required=True, help="个性化推荐语")
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument("--poster-path", default=None, help="TMDB poster_path e.g. /xxx.jpg")
    parser.add_argument("--force", action="store_true", help="Skip duplicate check")
    args = parser.parse_args()

    conn = media_app.get_conn()

    # Duplicate check
    if not args.force:
        dupes = check_duplicate(conn, args.tmdb_id, args.title)
        if dupes:
            print(f"DUPLICATE found: {dupes}")
            print("Use --force to override.")
            conn.close()
            sys.exit(1)

    # Download cover
    cover_url = download_cover(args.tmdb_id, args.tmdb_type, args.poster_path)
    if not cover_url:
        print("ERROR: cover unavailable, aborting (skill rule: cover must be valid)")
        conn.close()
        sys.exit(1)

    prefix = "tmdb_tv_" if args.tmdb_type == "tv" else "tmdb_"
    subject_id = f"{prefix}{args.tmdb_id}"
    endpoint = "tv" if args.tmdb_type == "tv" else "movie"

    item = {
        "subject_id": subject_id,
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
    conn.close()


if __name__ == "__main__":
    main()
