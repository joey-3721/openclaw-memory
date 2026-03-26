import sys, os, requests

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Search: Korean thriller/crime TV
print("=== Korean Thriller TV ===")
r = requests.get("https://api.themoviedb.org/3/discover/tv",
    params={"api_key": KEY, "language": "zh-CN", "with_genres": "18,80", "with_original_language": "ko",
            "sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "page": 1},
    proxies=P, timeout=15)
data = r.json()
for item in data.get("results", [])[:5]:
    print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"), item.get("overview", "")[:100])

# Search: US sci-fi/horror TV
print("\n=== US Sci-fi/Horror TV ===")
r = requests.get("https://api.themoviedb.org/3/discover/tv",
    params={"api_key": KEY, "language": "zh-CN", "with_genres": "10765,10751", "with_original_language": "en",
            "sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "page": 1},
    proxies=P, timeout=15)
data = r.json()
for item in data.get("results", [])[:5]:
    print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"), item.get("overview", "")[:100])

# Search: Japanese anime TV
print("\n=== Japanese Anime TV ===")
r = requests.get("https://api.themoviedb.org/3/discover/tv",
    params={"api_key": KEY, "language": "zh-CN", "with_origin_country": "JP", "with_genres": "16",
            "sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "page": 1},
    proxies=P, timeout=15)
data = r.json()
for item in data.get("results", [])[:5]:
    print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"), item.get("overview", "")[:100])

# Search: Korean thriller Movies
print("\n=== Korean Thriller Movies ===")
r = requests.get("https://api.themoviedb.org/3/discover/movie",
    params={"api_key": KEY, "language": "zh-CN", "with_genres": "53,80", "with_original_language": "ko",
            "sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "page": 1},
    proxies=P, timeout=15)
data = r.json()
for item in data.get("results", [])[:5]:
    print(item.get("title"), item.get("id"), item.get("vote_average"), item.get("vote_count"), item.get("overview", "")[:100])
