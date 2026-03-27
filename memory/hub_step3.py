import requests, os, sys

PROXIES = {"http":"http://192.168.50.209:7890","https":"http://192.168.50.209:7890"}

def search_tmdb(query, media_type='tv'):
    url = f"https://api.themoviedb.org/3/search/{media_type}"
    params = {"api_key": KEY, "query": query, "language": "zh-CN", "page": 1}
    r = requests.get(url, params=params, proxies=PROXIES, timeout=15)
    return r.json()

def get_details(tmdb_id, media_type):
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    params = {"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}
    r = requests.get(url, params=params, proxies=PROXIES, timeout=15)
    return r.json()

sys.path.insert(0, "/app")
import app as m
KEY = m.read_tmdb_key()

ALREADY = ['127529', '11423', '27205', '283566', '500664', '518068', '766507', '110356', '117376', '125988', '135340', '1411', '1429', '209867', '220542', '226529', '230923', '31911', '60625', '64840', '66330', '70626', '76479', '85937', '95396', '95479', '96571', '99494', '329865', '435601', '488623', '4977', '581528', '670', '687163', '838209', '100088', '108261', '108284', '110534', '119051', '129552', '135238', '13916', '155226', '200709', '218230', '253905', '280945', '64010', '67915', '73944', '87108', '90447', '90814', '94954', '96648', '99966']

# 候选：韩国悬疑/犯罪/奇幻
candidates = [
    ("299537", "movie"),    # Avengers: Endgame
    ("1418", "tv"),         # The Wire
    ("45788", "tv"),        # Dark - 德语
    ("60625", "tv"),        # 复仇者联盟 - 已推荐
    ("94699", "tv"),        # Moving (韩剧)
    ("215527", "tv"),       # Signal
    ("66732", "tv"),        # 浪漫刺客?
    ("152801", "tv"),       # 隧道
    ("1416", "tv"),         # 行尸走肉
    ("2316", "tv"),         # 越狱
]

# Let's do fresh searches instead
# Search Korean thriller
print("=== 搜索韩国悬疑 ===")
result = search_tmdb("Signal 韩国 悬疑", "tv")
for item in result.get('results', [])[:5]:
    print(item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

result = search_tmdb("moving 韩国 奇幻", "tv")
for item in result.get('results', [])[:5]:
    print(item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

result = search_tmdb("怪物 韩国 悬疑", "tv")
for item in result.get('results', [])[:5]:
    print(item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

print("=== 搜索美国科幻惊悚 ===")
result = search_tmdb("last of us", "tv")
for item in result.get('results', [])[:5]:
    print(item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

result = search_tmdb(" Severance ", "tv")
for item in result.get('results', [])[:5]:
    print(item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

print("=== 搜索日本动画 ===")
result = search_tmdb("寄生兽医", "tv")
for item in result.get('results', [])[:5]:
    print(item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))

result = search_tmdb("death note", "tv")
for item in result.get('results', [])[:5]:
    print(item.get('id'), item.get('name'), item.get('vote_average'), item.get('vote_count'), item.get('original_language'))
