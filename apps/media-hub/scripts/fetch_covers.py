#!/usr/bin/env python3
"""
Fetch cover image URLs from Douban subject pages and update the database.

Default behavior:
- use Douban `subject_id` as the single source of truth
- fetch the subject page directly
- extract canonical poster URL from `#mainpic` or `og:image`
- optionally verify the fetched page title roughly matches the DB title

Run examples:
  python3 fetch_covers.py --limit 50
  python3 fetch_covers.py --status wish --cookie 'bid=...'
  python3 fetch_covers.py --force-refresh --limit 200
  python3 fetch_covers.py --subject-id 37507947 --verbose
"""
import argparse
import html as html_lib
import json
import re
import sqlite3
import sys
import time
import urllib.request
from urllib.error import HTTPError, URLError

DEFAULT_DB = "/home/node/.openclaw/workspace-user1/douban/douban_media.db"
DEFAULT_COOKIE = 'bid=Zj9fdsB8LCA; ap_v=0,6.0; dbcl2="163684336:0n8KIpKblpM"; ck=tF4U'
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36'


def normalize_title(title: str) -> str:
    if not title:
        return ''
    title = title.strip()
    title = title.split('/')[0].strip()
    title = re.sub(r'\s+', '', title)
    title = re.sub(r'[·:：\-—_\|（）()\[\]【】,，\.。!！?？]', '', title)
    return title.lower()


def extract_douban_title(html: str) -> str | None:
    patterns = [
        r'<title>\s*(.*?)\s*\(豆瓣\)\s*</title>',
        r'<meta\s+property="og:title"\s+content="([^"]+)"',
        r'<span\s+property="v:itemreviewed">\s*(.*?)\s*</span>',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            return html_lib.unescape(m.group(1)).strip()
    return None


def extract_cover_url(html: str) -> str | None:
    patterns = [
        r'id="mainpic"[^>]*>\s*<a[^>]*>\s*<img[^>]+src="([^"]+)"',
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
        r'src="(https://img\d+\.doubanio\.com/view/photo/s_ratio_poster/public/p\d+\.[^"]+)"',
        r'src="(https://img\d+\.doubanio\.com/view/photo/l_ratio_poster/public/p\d+\.[^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            return m.group(1)
    return None


def fetch_subject_page(sid: str, cookie: str | None = None) -> tuple[str | None, str | None]:
    url = f'https://movie.douban.com/subject/{sid}/'
    headers = {
        'User-Agent': USER_AGENT,
        'Referer': 'https://movie.douban.com/',
    }
    if cookie:
        headers['Cookie'] = cookie
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        return html, None
    except HTTPError as e:
        return None, f'HTTP {e.code}'
    except URLError as e:
        return None, f'URL error: {e.reason}'
    except Exception as e:
        return None, str(e)


def fetch_cover(cookie: str, sid: str, db_title: str | None = None):
    html, err = fetch_subject_page(sid, cookie)
    if not html:
        return {
            'ok': False,
            'cover_url': None,
            'page_title': None,
            'error': err,
            'title_match': None,
        }

    page_title = extract_douban_title(html)
    cover_url = extract_cover_url(html)
    title_match = None
    if db_title and page_title:
        n_db = normalize_title(db_title)
        n_page = normalize_title(page_title)
        title_match = (n_db in n_page) or (n_page in n_db)

    return {
        'ok': bool(cover_url),
        'cover_url': cover_url,
        'page_title': page_title,
        'error': None if cover_url else 'cover not found',
        'title_match': title_match,
    }


def main():
    ap = argparse.ArgumentParser(description='Fetch cover images from Douban subject pages')
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--cookie', default=DEFAULT_COOKIE)
    ap.add_argument('--limit', type=int, default=100, help='Max items to fetch')
    ap.add_argument('--status', default=None, help='Filter by status (collect/wish)')
    ap.add_argument('--subject-id', default=None, help='Refresh a single subject_id only')
    ap.add_argument('--force-refresh', action='store_true', help='Refresh even if cover_url already exists')
    ap.add_argument('--strict-title-check', action='store_true', help='Skip DB update if fetched page title mismatches DB title')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)

    if args.subject_id:
        sql = 'SELECT subject_id, title, cover_url FROM douban_watch_history WHERE subject_id=?'
        items = conn.execute(sql, (args.subject_id,)).fetchall()
    else:
        where = ['subject_id IS NOT NULL']
        params = []
        if not args.force_refresh:
            where.append("(cover_url IS NULL OR cover_url='')")
        if args.status:
            where.append('status=?')
            params.append(args.status)
        sql = f"SELECT subject_id, title, cover_url FROM douban_watch_history WHERE {' AND '.join(where)} ORDER BY watched_date DESC LIMIT ?"
        params.append(args.limit)
        items = conn.execute(sql, params).fetchall()

    print(f'Fetching covers for {len(items)} items...')
    updated = 0
    skipped = 0
    failed = 0

    for i, (sid, title, old_cover) in enumerate(items, start=1):
        result = fetch_cover(args.cookie, sid, title)
        ok = result['ok']
        page_title = result['page_title'] or 'N/A'
        cover = result['cover_url']
        title_match = result['title_match']

        should_update = ok
        if args.strict_title_check and title_match is False:
            should_update = False

        if should_update and cover and cover != old_cover:
            conn.execute('UPDATE douban_watch_history SET cover_url=? WHERE subject_id=?', (cover, sid))
            updated += 1
            status = 'UPDATED'
        elif should_update and cover == old_cover:
            skipped += 1
            status = 'UNCHANGED'
        else:
            failed += 1
            status = 'FAIL'

        sys.stdout.write(f"\r  {i}/{len(items)}: {title[:24]} -> {status}   ")
        sys.stdout.flush()

        if args.verbose or status == 'FAIL':
            print('\n' + json.dumps({
                'subject_id': sid,
                'db_title': title,
                'page_title': page_title,
                'title_match': title_match,
                'old_cover': old_cover,
                'new_cover': cover,
                'error': result['error'],
            }, ensure_ascii=False))

        time.sleep(0.4)

    conn.commit()
    conn.close()
    print(f"\nDone. Updated {updated}, unchanged {skipped}, failed {failed}.")


if __name__ == '__main__':
    main()
