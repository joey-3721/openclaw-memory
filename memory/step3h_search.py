import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,85937,95396,95479,96571,99494,13855,155,264660,329865,396535,397567,435601,488623,496243,4977,568160,581528,670,687163,756999,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Try Korean titles with English
searches = [
    ("Moving Disney", "tv", "Moving Disney"),
    ("My Name", "tv", "My Name"),
    ("All of Us Are Dead", "tv", "All of Us Are Dead"),
    ("Sweet Home", "tv", "Sweet Home"),
    ("Kingdom", "tv", "Kingdom"),
    ("Crime Quest", "tv", "crime"),
]

for label, typ, query in searches:
    print(f"\n=== {label} ===")
    r = requests.get(f"https://api.themoviedb.org/3/search/{typ}", params={
        "api_key": KEY, "language": "zh-CN", "query": query, "page": 1
    }, proxies=P, timeout=15)
    for item in r.json().get("results", [])[:8]:
        tid = item["id"]
        orig_lang = item.get("original_language", "")
        orig_c = item.get("origin_country", [])
        vote_avg = item.get("vote_average", 0)
        vote_cnt = item.get("vote_count", 0)
        orig_name = item.get("original_name", "")
        # Filter for Korean (ko) if searching for Korean content
        if tid not in ALREADY and orig_lang == "ko":
            flag = "**" if vote_avg >= 7.5 and vote_cnt >= 200 else "  "
            print(f"{flag} {tid} | {item.get('name')} | {orig_name} | {orig_c} | rating:{vote_avg} votes:{vote_cnt}")
        elif tid not in ALREADY:
            if "ko" in str(orig_c).lower() or orig_lang == "ko":
                flag = "**" if vote_avg >= 7.5 and vote_cnt >= 200 else "  "
                print(f"{flag} {tid} | {item.get('name')} | {orig_name} | {orig_c} | rating:{vote_avg} votes:{vote_cnt}")
