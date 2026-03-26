import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,85937,95396,95479,96571,99494,13855,155,264660,329865,396535,397567,435601,488623,496243,4977,568160,581528,670,687163,756999,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Get trending Korean TV (Korean + TV)
print("=== Trending Korean TV ===")
r = requests.get("https://api.themoviedb.org/3/trending/tv/week", params={
    "api_key": KEY, "language": "zh-CN", "page": 1
}, proxies=P, timeout=15)
for item in r.json().get("results", [])[:30]:
    tid = item["id"]
    orig_lang = item.get("original_language", "")
    orig_c = item.get("origin_country", [])
    vote_avg = item.get("vote_average", 0)
    vote_cnt = item.get("vote_count", 0)
    if orig_lang == "ko" and tid not in ALREADY:
        flag = "**" if vote_avg >= 7.5 and vote_cnt >= 200 else "  "
        print(f"{flag} {tid} | {item.get('name')} | {item.get('original_name')} | {orig_c} | rating:{vote_avg} votes:{vote_cnt}")

# Also check discover TV with Korean orig lang
print("\n=== Discover TV Korean (vote>=7.0, count>=500) ===")
r = requests.get("https://api.themoviedb.org/3/discover/tv", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "vote_average.gte": 7.5,
    "vote_count.gte": 500,
    "with_original_language": "ko",
    "page": 1
}, proxies=P, timeout=15)
data = r.json()
for item in data.get("results", [])[:20]:
    tid = item["id"]
    if tid not in ALREADY:
        flag = "**" if item.get("vote_average",0) >= 7.5 and item.get("vote_count",0) >= 200 else "  "
        print(f"{flag} {tid} | {item.get('name')} | {item.get('original_name')} | rating:{item.get('vote_average')} votes:{item.get('vote_count')}")
