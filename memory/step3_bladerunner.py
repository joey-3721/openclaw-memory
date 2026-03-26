import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

conn = m.get_conn()
already = set(str(r["tmdb_id"]) for r in conn.execute("SELECT tmdb_id FROM douban_watch_history WHERE status='recommended'").fetchall())
watched = set(str(r["tmdb_id"]) for r in conn.execute("SELECT tmdb_id FROM douban_watch_history WHERE status IN ('watched','collect','dropped')").fetchall())
conn.close()

# Check Blade Runner (78)
r = requests.get("https://api.themoviedb.org/3/movie/78", params={
    "api_key": KEY, "language": "zh-CN",
    "append_to_response": "credits"
}, proxies=P, timeout=15)
d = r.json()
print(f"=== Blade Runner (78) ===")
print(f"Title: {d.get('title')}")
print(f"Original: {d.get('original_title')}")
print(f"Rating: {d.get('vote_average')}, Votes: {d.get('vote_count')}")
print(f"Year: {d.get('release_date', '')[:4]}")
print(f"Genres: {[g['name'] for g in d.get('genres', [])]}")
print(f"Countries: {d.get('production_countries', [])[:3]}")
print(f"Runtime: {d.get('runtime')} min")
print(f"Overview: {d.get('overview', '')[:300]}")
print(f"\nDirector:")
for c in d.get("credits", {}).get("crew", []):
    if c["job"] == "Director":
        print(f"  {c['name']}")
print(f"\nTop Cast:")
for c in d.get("credits", {}).get("cast", [])[:5]:
    print(f"  {c['name']}: {c['character']}")
print(f"\nIn ALREADY_REC: {'78' in already}")
print(f"In WATCHED: {'78' in watched}")
print(f"Poster: {d.get('poster_path')}")

# Also check V for Vendetta (752)
r2 = requests.get("https://api.themoviedb.org/3/movie/752", params={
    "api_key": KEY, "language": "zh-CN",
    "append_to_response": "credits"
}, proxies=P, timeout=15)
d2 = r2.json()
print(f"\n=== V for Vendetta (752) ===")
print(f"Title: {d2.get('title')}")
print(f"Rating: {d2.get('vote_average')}, Votes: {d2.get('vote_count')}")
print(f"Year: {d2.get('release_date', '')[:4]}")
print(f"Genres: {[g['name'] for g in d2.get('genres', [])]}")
print(f"Overview: {d2.get('overview', '')[:200]}")
print(f"\nDirector:")
for c in d2.get("credits", {}).get("crew", []):
    if c["job"] == "Director":
        print(f"  {c['name']}")
print(f"\nIn ALREADY_REC: {'752' in already}")
print(f"In WATCHED: {'752' in watched}")
