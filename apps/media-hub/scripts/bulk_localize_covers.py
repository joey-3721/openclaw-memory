#!/usr/bin/env python3
import html as html_lib
import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

import requests

DB = '/data/douban_media.db'
COVERS = Path('/data/covers')
COVERS.mkdir(parents=True, exist_ok=True)
COOKIE = 'bid=Zj9fdsB8LCA; ap_v=0,6.0; dbcl2="163684336:0n8KIpKblpM"; ck=tF4U'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36'


def normalize_title(title):
    if not title:
        return ''
    title = title.strip().split('/')[0].strip()
    title = re.sub(r'\s+', '', title)
    title = re.sub(r'[·:：\-—_\|（）()\[\]【】,，\.。!！?？]', '', title)
    return title.lower()


def extract_title(html):
    for p in [
        r'<title>\s*(.*?)\s*\(豆瓣\)\s*</title>',
        r'<meta\s+property="og:title"\s+content="([^"]+)"',
        r'<span\s+property="v:itemreviewed">\s*(.*?)\s*</span>',
    ]:
        m = re.search(p, html, re.I | re.S)
        if m:
            return html_lib.unescape(m.group(1)).strip()
    return None


def extract_cover(html):
    for p in [
        r'id="mainpic"[^>]*>\s*<a[^>]*>\s*<img[^>]+src="([^"]+)"',
        r'<meta\s+property="og:image"\s+content="([^"]+)"',
        r'src="(https://img\d+\.doubanio\.com/view/photo/s_ratio_poster/public/p\d+\.[^"]+)"',
        r'src="(https://img\d+\.doubanio\.com/view/photo/l_ratio_poster/public/p\d+\.[^"]+)"',
    ]:
        m = re.search(p, html, re.I | re.S)
        if m:
            return m.group(1)
    return None


def normalize_cover_url(url):
    if not url:
        return None
    url = url.strip()
    if 'doubanio.com/view/photo/' in url and url.endswith('.webp'):
        url = url[:-5] + '.jpg'
    return url


def download_cover(url, sid):
    url = normalize_cover_url(url)
    r = requests.get(url, headers={'User-Agent': UA, 'Referer': 'https://movie.douban.com/'}, timeout=20)
    r.raise_for_status()
    ext = 'jpg'
    m = re.search(r'\.([a-zA-Z0-9]+)(?:\?|$)', url)
    if m and m.group(1).lower() in {'jpg', 'jpeg', 'png', 'webp'}:
        ext = 'jpg' if m.group(1).lower() == 'jpeg' else m.group(1).lower()
    for old in COVERS.glob(f'{sid}.*'):
        try:
            old.unlink()
        except Exception:
            pass
    path = COVERS / f'{sid}.{ext}'
    path.write_bytes(r.content)
    return f'/covers/{path.name}'


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute("select subject_id,title,cover_url from douban_watch_history where subject_id is not null order by watched_date desc").fetchall()
    print(f'Bulk refreshing {len(rows)} items...', flush=True)
    updated = skipped = failed = mismatch = 0
    bad = []

    for i, (sid, title, old_cover) in enumerate(rows, start=1):
        try:
            req = urllib.request.Request(
                f'https://movie.douban.com/subject/{sid}/',
                headers={'User-Agent': UA, 'Referer': 'https://movie.douban.com/', 'Cookie': COOKIE},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode('utf-8', 'ignore')
            page_title = extract_title(html)
            cover = extract_cover(html)
            n_db = normalize_title(title)
            n_page = normalize_title(page_title or '')
            title_match = ((n_db in n_page) or (n_page in n_db)) if (n_db and n_page) else False
            if not cover:
                failed += 1
                bad.append((sid, title, 'no_cover', page_title))
            elif not title_match:
                mismatch += 1
                failed += 1
                bad.append((sid, title, 'title_mismatch', page_title))
            else:
                local_url = download_cover(cover, sid)
                if local_url != old_cover:
                    conn.execute('update douban_watch_history set cover_url=? where subject_id=?', (local_url, sid))
                    updated += 1
                else:
                    skipped += 1
        except Exception as e:
            failed += 1
            bad.append((sid, title, str(e)[:120], None))
        if i % 25 == 0 or i == len(rows):
            print(f'{i}/{len(rows)} updated={updated} skipped={skipped} failed={failed} mismatches={mismatch}', flush=True)
        time.sleep(0.15)

    conn.commit()
    conn.close()
    print('SAMPLE_BAD ' + json.dumps(bad[:20], ensure_ascii=False), flush=True)
    print(json.dumps({'updated': updated, 'skipped': skipped, 'failed': failed, 'mismatch': mismatch}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
