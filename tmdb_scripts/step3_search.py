import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Search Korean thriller/crime shows
endpoints = [
    ("search/tv", {"query": "Kingdom"}),
    ("search/tv", {"query": "Signal Korean thriller"}),
    ("search/movie", {"query": "Tunnel Korean crime"}),
    ("discover/tv", {"sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "with_genres": "18,10765", "with_origin_country": "KR"}),
    ("discover/movie", {"sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "with_genres": "878,53", "without_origin_country": "CN"}),
]

for ep, params in endpoints:
    url = f"https://api.themoviedb.org/3/{ep}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", **params}, proxies=P, timeout=15)
    d = r.json()
    if "results" in d:
        for item in d["results"][:5]:
            print(f"TV: {item.get('name', item.get('title'))} | {item.get('vote_average')} | {item.get('id')} | {item.get('overview','')[:100]}")
    elif "results" not in d:
        print(f"Response: {str(d)[:200]}")
