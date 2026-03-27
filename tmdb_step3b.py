import sys, os, requests

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Check specific candidates
candidates = [
    ("movie", 435601, "杀人优越权"),
    ("movie", 13855, "追击者"),
]

for media_type, tmdb_id, name in candidates:
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
    d = r.json()
    print(f"--- {name} ({tmdb_id}) ---")
    print("Title:", d.get("title") or d.get("name"))
    print("Rating:", d.get("vote_average"), "Votes:", d.get("vote_count"))
    print("Genres:", [g["name"] for g in d.get("genres", [])])
    print("Countries:", [c["name"] for c in d.get("production_countries", [])])
    print("Year:", (d.get("release_date") or d.get("first_air_date", ""))[:4])
    print("Overview:", d.get("overview", "")[:200])
    print()
