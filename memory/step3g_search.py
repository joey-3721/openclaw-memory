import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,85937,95396,95479,96571,99494,13855,155,264660,329865,396535,397567,435601,488623,496243,4977,568160,581528,670,687163,756999,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Search 悬疑犯罪韩剧 by keyword
print("=== Search: 韩国 悬疑 剧 ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "韩国 悬疑 犯罪 剧", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:10]:
    tid = item["id"]
    if tid not in ALREADY:
        print(f"  {tid} | {item.get('name')} | {item.get('original_name')} | rating:{item.get('vote_average')} votes:{item.get('vote_count')}")

# Search Big / 비기جب
print("\n=== Search: Big 韩国 ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": "Big", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:10]:
    tid = item["id"]
    if tid not in ALREADY and item.get("original_language") == "ko":
        print(f"  {tid} | {item.get('name')} | {item.get('original_name')} | rating:{item.get('vote_average')} votes:{item.get('vote_count')}")

# Search Moving (韩剧)
print("\n=== Search: Moving (韩剧) ===")
r = requests.get("https://api.themoviedb.org/3/search/tv", params={
    "api_key": KEY, "language": "zh-CN", "query": " Moving", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:10]:
    tid = item["id"]
    if tid not in ALREADY and item.get("original_language") == "ko":
        print(f"  {tid} | {item.get('name')} | {item.get('original_name')} | rating:{item.get('vote_average')} votes:{item.get('vote_count')}")

# Check Hellbound details
print("\n=== Hellbound (106651) details ===")
r = requests.get("https://api.themoviedb.org/3/tv/106651", params={
    "api_key": KEY, "language": "zh-CN",
    "append_to_response": "credits"
}, proxies=P, timeout=15)
d = r.json()
print(f"Name: {d.get('name')} ({d.get('original_name')})")
print(f"Rating: {d.get('vote_average')}, Votes: {d.get('vote_count')}")
print(f"Genres: {[g['name'] for g in d.get('genres', [])]}")
print(f"Countries: {d.get('origin_country', [])}")
print(f"Year: {d.get('first_air_date', '')[:4]}")
print(f"Seasons: {len(d.get('seasons', []))}")
print(f"Overview: {d.get('overview', '')[:200]}")
