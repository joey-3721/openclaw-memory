import sys
sys.path.insert(0,'/app')
import app as m
conn=m.get_conn()
# Check watch history for specific titles
rows=conn.execute("SELECT tmdb_id, status, my_rating, title FROM douban_watch_history WHERE tmdb_id IN (66433, 221851, 136369)").fetchall()
for r in rows:
    print(f"tmdb_id={r['tmdb_id']} status={r['status']} rating={r['my_rating']} title={r['title']}")
conn.close()
