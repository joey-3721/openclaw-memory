import sys, os, requests, json
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
sys.path.insert(0,"/app")
import app as m
KEY = m.read_tmdb_key()
P = {"http":"http://192.168.50.209:7890","https":"http://192.168.50.209:7890"}

# Check Upgrade (2018)
r = requests.get("https://api.themoviedb.org/3/movie/500664",
    params={"api_key":KEY,"language":"zh-CN","append_to_response":"credits,genres"},
    proxies=P, timeout=15)
d = r.json()
print("Status for 500664:", r.status_code)
print("Title:", d.get("title"), "/", d.get("original_title"))
print("Rating:", d.get("vote_average"), "Votes:", d.get("vote_count"))
print("Year:", str(d.get("release_date", ""))[:4])
print("Overview:", d.get("overview","")[:300])
genres = [g["name"] for g in d.get("genres", [])]
print("Genres:", genres)

# Check other candidates
for mid, label in [(94605, "Arcane"), (95557, "Invincible"), (500664, "Upgrade")]:
    r = requests.get(f"https://api.themoviedb.org/3/tv/{mid}" if mid not in [500664] else f"https://api.themoviedb.org/3/movie/{mid}",
        params={"api_key":KEY,"language":"zh-CN","append_to_response":"credits,genres"},
        proxies=P, timeout=15)
    d = r.json()
    print(f"\n=== {label} ({mid}) ===")
    print("Name:", d.get("name", d.get("title")))
    print("Rating:", d.get("vote_average"), "Votes:", d.get("vote_count"))
    print("Overview:", d.get("overview","")[:200])
    genres = [g["name"] for g in d.get("genres", [])]
    print("Genres:", genres)
