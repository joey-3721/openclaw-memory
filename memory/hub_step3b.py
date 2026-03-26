import requests, os, sys

PROXIES = {"http":"http://192.168.50.209:7890","https":"http://192.168.50.209:7890"}

sys.path.insert(0, "/app")
import app as m
KEY = m.read_tmdb_key()

ALREADY = ['127529', '11423', '27205', '283566', '500664', '518068', '766507', '110356', '117376', '125988', '135340', '1411', '1429', '209867', '220542', '226529', '230923', '31911', '60625', '64840', '66330', '70626', '76479', '85937', '95396', '95479', '96571', '99494', '329865', '435601', '488623', '4977', '581528', '670', '687163', '838209', '100088', '108261', '108284', '110534', '119051', '129552', '135238', '13916', '155226', '200709', '218230', '253905', '280945', '64010', '67915', '73944', '87108', '90447', '90814', '94954', '96648', '99966']

def get_details(tmdb_id, media_type):
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    params = {"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}
    r = requests.get(url, params=params, proxies=PROXIES, timeout=15)
    return r.json()

# Check Severance - already in list? 95396 is already rec
# Let's check if 95396 is in ALREADY
print("95396 in ALREADY:", "95396" in ALREADY)

# Search more
print("\n=== Severance details ===")
d = get_details("95396", "tv")
print(d.get('name'), d.get('vote_average'), d.get('vote_count'))
print(d.get('overview','')[:200])
print("genres:", [g['name'] for g in d.get('genres', [])])

print("\n=== Search Korean crime/thriller ===")
# Search for Korean shows
queries = [
    ("韩国 犯罪 悬疑", "tv"),
    ("韩剧 烧脑", "tv"),
    ("sweet home 怪物", "tv"),
    ("僵尸 韩国", "tv"),
]
for q, t in queries:
    url = f"https://api.themoviedb.org/3/search/{t}"
    params = {"api_key": KEY, "query": q, "language": "zh-CN", "page": 1}
    r = requests.get(url, params=params, proxies=PROXIES, timeout=15)
    for item in r.json().get('results', [])[:5]:
        if item.get('id') not in ALREADY and item.get('vote_count', 0) >= 200 and item.get('vote_average', 0) >= 7.0:
            print("CANDIDATE:", item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

print("\n=== More US sci-fi/thriller ===")
queries2 = [
    ("From", "tv"),
    ("The Night Agent", "tv"),
    ("The Fall of the House of Usher", "tv"),
    ("Love, Death & Robots", "tv"),
]
for q, t in queries2:
    url = f"https://api.themoviedb.org/3/search/{t}"
    params = {"api_key": KEY, "query": q, "language": "zh-CN", "page": 1}
    r = requests.get(url, params=params, proxies=PROXIES, timeout=15)
    for item in r.json().get('results', [])[:3]:
        if item.get('id') not in ALREADY and item.get('vote_count', 0) >= 200 and item.get('vote_average', 0) >= 7.0:
            print("CANDIDATE:", item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

print("\n=== Check specific Korean shows ===")
korean_shows = ["94699", "215527", "152801", "1418", "2316"]
for sid in korean_shows:
    if sid not in ALREADY:
        d = get_details(sid, "tv")
        print(f"ID {sid}:", d.get('name'), "| rating:", d.get('vote_average'), "| votes:", d.get('vote_count'), "| lang:", d.get('original_language'))
        print("  overview:", d.get('overview','')[:150])
        print("  genres:", [g['name'] for g in d.get('genres', [])])
