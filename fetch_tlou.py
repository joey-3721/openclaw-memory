import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m
KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Fetch The Last of Us details
tmdb_id = 100088
url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
d = r.json()
print("Title:", d.get("name"), d.get("original_name"))
print("Rating:", d.get("vote_average"), "Votes:", d.get("vote_count"))
print("Year:", (d.get("first_air_date") or "")[:4], "-", (d.get("last_air_date") or "")[:4])
print("Genres:", [g["name"] for g in d.get("genres", [])])
print("Countries:", [c["name"] for c in d.get("production_countries", [])])
print("Poster:", d.get("poster_path"))
print("Overview:", d.get("overview"))
print("\nSeasons:", len(d.get("seasons", [])))
for s in d.get("seasons", []):
    print(f"  Season {s['season_number']}: {s['name']} ({s['episode_count']} eps)")
