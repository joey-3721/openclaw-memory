import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,85937,95396,95479,96571,99494,13855,155,264660,329865,396535,397567,435601,488623,496243,4977,568160,581528,670,687163,756999,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Check specific Korean show IDs
ids_to_check = [
    33119,   # Signal
    130718,  # D.P.
    131583,  # Squid Game (鱿鱼游戏)
    95403,   # Sweet Home
    141809,  # Moving
    234989,  # 地狱公转 / Hypernap
    135157,  # 甜蜜家园 / Sweet Home (actually movie?)
    111497,  # 医生们
    83875,   # 太阳的后裔
    71446,   # 浪漫满屋
    152997,  # 恶鬼
    136087,  # 贞伊
    119861,  # 三日一生
    128621,  # 鱿鱼游戏: 对战留白 (uncanny)
    234989,
    84773,   # The Glory
    213227,  # 杀死伊芙
    2316,    # The Usual Suspects (not KR)
]

for tid in ids_to_check:
    if tid in ALREADY:
        print(f"{tid}: ALREADY recommended, skipping")
        continue
    r = requests.get(f"https://api.themoviedb.org/3/tv/{tid}", params={
        "api_key": KEY,
        "language": "zh-CN",
        "append_to_response": "credits"
    }, proxies=P, timeout=15)
    d = r.json()
    if d.get("success") == False:
        print(f"{tid}: NOT FOUND")
        continue
    orig_lang = d.get("original_language")
    vote_avg = d.get("vote_average")
    vote_cnt = d.get("vote_count")
    genres = [g["name"] for g in d.get("genres", [])]
    orig_c = d.get("origin_country", [])
    name = d.get("name", d.get("title"))
    overview = d.get("overview", "")[:100]
    print(f"{tid} | {name} | {orig_lang} | {orig_c} | rating:{vote_avg} votes:{vote_cnt} | {genres} | {overview}")
