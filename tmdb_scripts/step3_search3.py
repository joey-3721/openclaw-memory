import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY_REC = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,83907,95396,95479,96571,99494,1376434,13855,155,264660,280,290098,329865,396535,397567,435601,488623,496243,4977,530254,568160,581528,670,679,687163,752,756999,78,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Search for specific shows
queries = [
    ("search/tv", {"query": "Signal 2016 Korean"}),
    ("search/tv", {"query": "Moving 2023 Korean Disney"}),
    ("search/tv", {"query": "Sweet Home 2019 Korean"}),
    ("search/tv", {"query": "地狱风暴 Korean"}),
    ("search/tv", {"query": "Dustcraft Korean"}),
    ("search/tv", {"query": "气球韩国"}),
    ("search/tv", {"query": "连接戛纳韩国"}),
]

for ep, params in queries:
    url = f"https://api.themoviedb.org/3/{ep}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", **params}, proxies=P, timeout=15)
    d = r.json()
    if "results" in d and d["results"]:
        for item in d["results"][:3]:
            item_id = item["id"]
            in_rec = "ALREADY" if item_id in ALREADY_REC else "NEW"
            print(f"[{in_rec}] {item.get('name', item.get('title'))} | ID={item_id} | rating={item.get('vote_average')} | votes={item.get('vote_count')} | overview={item.get('overview','')[:80]}")
    print()
