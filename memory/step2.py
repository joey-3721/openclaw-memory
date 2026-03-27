import sys
sys.path.insert(0,"/app")
import app as m
conn = m.get_conn()
rows = conn.execute("SELECT title,my_rating,genres,countries,comment FROM douban_watch_history WHERE status='collect' AND my_rating>=4 ORDER BY my_rating DESC LIMIT 20").fetchall()
for r in rows:
    print("LIKED:", r["title"], r["my_rating"], r["genres"], r["countries"])
rows2 = conn.execute("SELECT title,comment FROM douban_watch_history WHERE status='collect' AND my_rating<=2 AND my_rating>0").fetchall()
for r in rows2:
    print("DISLIKED:", r["title"], r["comment"])
already = conn.execute("SELECT tmdb_id FROM douban_watch_history WHERE status='recommended'").fetchall()
print("ALREADY_REC:", [r["tmdb_id"] for r in already])
conn.close()
