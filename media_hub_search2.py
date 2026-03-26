import sys, os, requests, json
sys.path.insert(0,"/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http":"http://192.168.50.209:7890","https":"http://192.168.50.209:7890"}

def get_detail(tmdb_id, type_="tv"):
    url = f"https://api.themoviedb.org/3/{type_}/{tmdb_id}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
    return r.json()

def discover(type_, genre_id, with_origin_country=None, sort_by="vote_average.desc", min_votes=200, min_score=7.5):
    url = f"https://api.themoviedb.org/3/discover/{type_}"
    params = {
        "api_key": KEY,
        "language": "zh-CN",
        "sort_by": sort_by,
        "vote_average.gte": min_score,
        "vote_count.gte": min_votes,
        "include_adult": False,
        "with_genres": genre_id
    }
    if with_origin_country:
        params["with_origin_country"] = with_origin_country
    r = requests.get(url, params=params, proxies=P, timeout=15)
    return r.json()

already = [127529, 11423, 27205, 283566, 500664, 518068, 766507, 110356, 117376, 125988, 135340, 1411, 1429, 209867, 220542, 226529, 230923, 31911, 60625, 64840, 66330, 70626, 76479, 85937, 95396, 95479, 96571, 99494, 155, 329865, 435601, 488623, 496243, 4977, 581528, 670, 687163, 838209, 9323, 950396, 100088, 108261, 108284, 110316, 110534, 119051, 124364, 127532, 129552, 13916, 1415, 155226, 200709, 235577, 246, 253905, 280945, 64010, 67915, 72548, 73944, 83097, 87108, 90447, 90814, 92685, 9343, 94954, 95557, 96648, 96777, 99966]

# Korean thriller TV - genre 9648=Crime, 18=Drama, 10765=Sci-Fi&Fantasy
print("=== 韩国悬疑/犯罪 TV ===")
r = discover("tv", "9648,18", with_origin_country="KR")
for item in r.get("results", []):
    if item.get("vote_count", 0) >= 200 and float(item.get("vote_average", 0)) >= 7.5 and item["id"] not in already:
        print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"), item.get("first_air_date", "")[:4], item.get("overview", "")[:100])

print("\n=== 美国科幻惊悚 TV ===")
r = discover("tv", "10765,878", with_origin_country="US")
for item in r.get("results", []):
    if item.get("vote_count", 0) >= 200 and float(item.get("vote_average", 0)) >= 7.5 and item["id"] not in already:
        print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"), item.get("first_air_date", "")[:4], item.get("overview", "")[:100])

print("\n=== 日本动画 TV 高分 ===")
r = discover("tv", "16", with_origin_country="JP")
for item in r.get("results", []):
    if item.get("vote_count", 0) >= 200 and float(item.get("vote_average", 0)) >= 7.5 and item["id"] not in already:
        print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"), item.get("first_air_date", "")[:4], item.get("overview", "")[:100])
