import sys, os, requests

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

url = "https://api.themoviedb.org/3/movie/435601"
r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
d = r.json()

print("Title:", d.get("title"))
print("Original Title:", d.get("original_title"))
print("Rating:", d.get("vote_average"), "Votes:", d.get("vote_count"))
print("Genres:", [g["name"] for g in d.get("genres", [])])
print("Countries:", [c["name"] for c in d.get("production_countries", [])])
print("Year:", (d.get("release_date", ""))[:4])
print("Poster path:", d.get("poster_path"))
print("Overview:", d.get("overview", ""))

# Get credits
credits = d.get("credits", {})
cast = credits.get("cast", [])[:5]
print("\nTop cast:")
for c in cast:
    print(f"  {c['name']} as {c['character']}")
