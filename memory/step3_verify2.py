import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Verify The Glory details
print("=== The Glory (136283) ===")
r = requests.get("https://api.themoviedb.org/3/tv/136283", params={
    "api_key": KEY, "language": "zh-CN",
    "append_to_response": "credits,keywords"
}, proxies=P, timeout=15)
d = r.json()
print(f"Name: {d.get('name')}")
print(f"Original Name: {d.get('original_name')}")
print(f"Rating: {d.get('vote_average')}, Votes: {d.get('vote_count')}")
print(f"Year: {d.get('first_air_date', '')[:4]}")
print(f"Genres: {[g['name'] for g in d.get('genres', [])]}")
print(f"Countries: {d.get('origin_country', [])}")
print(f"Language: {d.get('original_language')}")
print(f"Seasons: {len(d.get('seasons', []))}")
for s in d.get("seasons", []):
    if s["season_number"] > 0:
        print(f"  Season {s['season_number']}: {s['name']}, eps: {s['episode_count']}, rating: {s.get('vote_average', 'N/A')}")
print(f"\nOverview: {d.get('overview', '')}")
print(f"\nDirector/Creator:")
for c in d.get("credits", {}).get("crew", []):
    if c["job"] in ["Director", "Creator"]:
        print(f"  {c['job']}: {c['name']}")
print(f"\nTop Cast:")
for c in d.get("credits", {}).get("cast", [])[:8]:
    print(f"  {c['name']}: {c['character']}")
print(f"\nKeywords:")
for k in d.get("keywords", {}).get("results", [])[:10]:
    print(f"  {k['name']}")
