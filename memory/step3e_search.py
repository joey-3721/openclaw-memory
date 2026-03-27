import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,85937,95396,95479,96571,99494,13855,155,264660,329865,396535,397567,435601,488623,496243,4977,568160,581528,670,687163,756999,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Search TMDB for Korean thriller shows
print("=== Search: Kingdom (韩剧) ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "Kingdom 韩国", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:5]:
    print(item["id"], item["name"], item.get("original_name"), item["vote_average"], item["vote_count"])

# Search for Signal (信号)
print("\n=== Search: Signal 韩国 犯罪 ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "Signal", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:5]:
    print(item["id"], item["name"], item.get("original_name"), item["vote_average"], item["vote_count"])

# Search for Sweet Home
print("\n=== Search: Sweet Home ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "Sweet Home", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:5]:
    print(item["id"], item["name"], item.get("original_name"), item["vote_average"], item["vote_count"])

# Search for D.P. Korean military
print("\n=== Search: D.P. Korean ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "D.P.", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:5]:
    print(item["id"], item["name"], item.get("original_name"), item["vote_average"], item["vote_count"])

# Search for moving Korean superhero
print("\n=== Search: Moving 韩国 异能 ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "Moving 韩国", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:5]:
    print(item["id"], item["name"], item.get("original_name"), item["vote_average"], item["vote_count"])

# Search for Hellbound Korean
print("\n=== Search: Hellbound 地狱公转 ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "Hellbound", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:5]:
    print(item["id"], item["name"], item.get("original_name"), item["vote_average"], item["vote_count"])
