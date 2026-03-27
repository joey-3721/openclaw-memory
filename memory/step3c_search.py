import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,85937,95396,95479,96571,99494,13855,155,264660,329865,396535,397567,435601,488623,496243,4977,568160,581528,670,687163,756999,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Search Korean TV with origin_country
print("=== Korean TV (origin=KR) ===")
r = requests.get("https://api.themoviedb.org/3/discover/tv", params={
    "api_key": KEY,
    "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "vote_average.gte": 7.5,
    "vote_count.gte": 500,
    "with_origin_countries": "KR",
    "page": 1
}, proxies=P, timeout=15)
data = r.json()
for item in data.get("results", [])[:20]:
    if item["id"] not in ALREADY:
        print(item["id"], item["name"], item.get("original_name"), item["vote_average"], item["vote_count"])

# Search Korean movies
print("\n=== Korean Movies (origin=KR) ===")
r = requests.get("https://api.themoviedb.org/3/discover/movie", params={
    "api_key": KEY,
    "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "vote_average.gte": 7.0,
    "vote_count.gte": 500,
    "with_origin_countries": "KR",
    "page": 1
}, proxies=P, timeout=15)
data = r.json()
for item in data.get("results", [])[:20]:
    if item["id"] not in ALREADY:
        print(item["id"], item["title"], item.get("original_title"), item["vote_average"], item["vote_count"])
