#!/usr/bin/env python3
"""
Fetch cover image URLs from Douban subject pages and update the database.
Run standalone: python3 fetch_covers.py [--db <path>] [--limit 50] [--cookie <cookie>]
"""
import argparse
import re
import sqlite3
import sys
import time
import urllib.request

DEFAULT_DB = "/home/node/.openclaw/workspace-user1/douban/douban_media.db"
DEFAULT_COOKIE = 'bid=Zj9fdsB8LCA; ap_v=0,6.0; dbcl2="163684336:0n8KIpKblpM"; ck=tF4U'


def fetch_cover(session, sid):
    url = f'https://movie.douban.com/subject/{sid}/'
    req = urllib.request.Request(url, headers=session.headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        m = re.search(r'id="mainpic"[^>]*>\s*<img[^>]+src="(https://img9\.doubanio\.com[^"]+)"', html)
        if not m:
            m = re.search(r'src="(https://img9\.doubanio\.com/view/photo/s_ratio_poster/public/p\d+\.jpg)"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Fetch cover images from Douban")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--cookie", default=DEFAULT_COOKIE)
    ap.add_argument("--limit", type=int, default=100, help="Max items to fetch")
    ap.add_argument("--status", default=None, help="Filter by status (collect/wish)")
    args = ap.parse_args()

    session = urllib.request.Request
    class Session:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Cookie': args.cookie,
            'Referer': 'https://movie.douban.com/',
        }
    s = Session()

    conn = sqlite3.connect(args.db)
    sql = "SELECT subject_id, title FROM douban_watch_history WHERE (cover_url IS NULL OR cover_url='') AND subject_id IS NOT NULL"
    params = []
    if args.status:
        sql += " AND status=?"
        params.append(args.status)
    sql += " ORDER BY watched_date DESC LIMIT ?"
    params.append(args.limit)
    items = conn.execute(sql, params).fetchall()

    print(f"Fetching covers for {len(items)} items...")
    updated = 0
    for i, (sid, title) in enumerate(items):
        cover = fetch_cover(s, sid)
        if cover:
            conn.execute("UPDATE douban_watch_history SET cover_url=? WHERE subject_id=?", (cover, sid))
            updated += 1
        sys.stdout.write(f"\r  {i+1}/{len(items)}: {title[:30]} -> {'OK' if cover else 'FAIL'}")
        sys.stdout.flush()
        time.sleep(0.5)

    conn.commit()
    print(f"\nDone. Updated {updated}/{len(items)} cover URLs.")
    conn.close()


if __name__ == "__main__":
    main()
