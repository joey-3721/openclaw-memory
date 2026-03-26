import sys, os, requests, json
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY_REC = [127529,11423,27205,283566,500664,518068,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,95396,95479,96571,99494,1376434,13855,155,264660,280,290098,329865,396535,397567,435601,488623,496243,4977,530254,568160,581528,670,679,687163,752,756999,78,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Try direct ID lookups for known Korean shows
# Sweet Home = 95479??? No wait, 95479 was listed as ALREADY_REC for something
# Let me look for specific shows by searching
search_terms = [
    "Signal 2016",
    "Moving 2023 Korean",
    "Sweet Home Netflix",
]

for term in search_terms:
    url = "https://api.themoviedb.org/3/search/tv"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "query": term}, proxies=P, timeout=15)
    d = r.json()
    print(f"Search '{term}': {json.dumps(d.get('results', [])[:2], ensure_ascii=False)}")

# Try discover Korean fantasy/thriller
url = "https://api.themoviedb.org/3/discover/tv"
params = {
    "api_key": KEY,
    "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "vote_count.gte": 200,
    "vote_average.gte": 7.8,
    "with_origin_country": "KR",
    "with_genres": "18,10765",  # drama, sci-fi & fantasy
}
r = requests.get(url, params=params, proxies=P, timeout=15)
d = r.json()
print("\nKorean TV discoveries:")
for item in d.get("results", [])[:10]:
    item_id = item["id"]
    in_rec = "ALREADY" if item_id in ALREADY_REC else "NEW"
    print(f"[{in_rec}] {item.get('name')} | ID={item_id} | rating={item.get('vote_average')} | votes={item.get('vote_count')} | first_air={item.get('first_air_date')}")
