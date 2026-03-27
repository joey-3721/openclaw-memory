import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

conn = m.get_conn()
already_ids = set(str(r["tmdb_id"]) for r in conn.execute("SELECT tmdb_id FROM douban_watch_history WHERE status='recommended'").fetchall())
conn.close()

# Search US sci-fi/thriller movies
r = requests.get("https://api.themoviedb.org/3/discover/movie", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "vote_average.gte": 7.5,
    "vote_count.gte": 500,
    "with_genres": "878,53",  # Sci-Fi, Thriller
    "with_origin_countries": ["US"],
    "page": 1
}, proxies=P, timeout=15)
data = r.json()
print("=== US Sci-fi/Thriller Movies ===")
for item in data.get("results", [])[:20]:
    tid = str(item["id"])
    flag = "GOOD" if tid not in already_ids else "ALREADY"
    print(f"{flag}: {item['id']} | {item['title']} | {item.get('original_title')} | rating:{item['vote_average']} votes:{item['vote_count']}")
