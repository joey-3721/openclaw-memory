import sys, os, requests, json

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m
KEY = m.read_tmdb_key()
PROXIES = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Get full details for 记忆之夜 (TMDB 488623)
print("=== 记忆之夜 Full Details ===")
r = requests.get("https://api.themoviedb.org/3/movie/488623", params={
    "api_key": KEY, "language": "zh-CN",
    "append_to_response": "credits,alternative_titles"
}, proxies=PROXIES, timeout=15)
d = r.json()
print(f"Title (CN): {d.get('title')}")
print(f"Title (Original): {d.get('original_title')}")
print(f"Release: {d.get('release_date')}")
print(f"Rating: {d.get('vote_average')}/10 ({d.get('vote_count')} votes)")
print(f"Genres: {[g['name'] for g in d.get('genres', [])]}")
print(f"Countries: {[c['name'] for c in d.get('production_countries', [])]}")
print(f"Runtime: {d.get('runtime')} min")
print(f"Tagline: {d.get('tagline')}")
print(f"Overview: {d.get('overview')}")
print(f"Poster: {d.get('poster_path')}")
print(f"IMDB: {d.get('imdb_id')}")
print(f"\nCredits (top 10):")
for c in (d.get("credits", {}).get("cast", [])[:10]):
    print(f"  {c['name']} as {c['character']}")
print(f"\nDirector:")
for c in d.get("credits", {}).get("crew", []):
    if c["job"] == "Director":
        print(f"  {c['name']}")

# Alternative titles
alts = d.get("alternative_titles", {}).get("titles", [])
for a in alts:
    print(f"Alt title: {a['title']} ({a['iso_3166_1']})")
