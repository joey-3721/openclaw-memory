import sys, os, requests, json
sys.path.insert(0,"/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http":"http://192.168.50.209:7890","https":"http://192.168.50.209:7890"}

already = [127529, 11423, 27205, 283566, 500664, 518068, 766507, 110356, 117376, 125988, 135340, 1411, 1429, 209867, 220542, 226529, 230923, 31911, 60625, 64840, 66330, 70626, 76479, 85937, 95396, 95479, 96571, 99494, 155, 329865, 435601, 488623, 496243, 4977, 581528, 670, 687163, 838209, 9323, 950396, 100088, 108261, 108284, 110316, 110534, 119051, 124364, 127532, 129552, 13916, 1415, 155226, 200709, 235577, 246, 253905, 280945, 64010, 67915, 72548, 73944, 83097, 87108, 90447, 90814, 92685, 9343, 94954, 95557, 96648, 96777, 99966]

def search(query, endpoint="search/movie"):
    url = f"https://api.themoviedb.org/3/{endpoint}"
    r = requests.get(url, params={"api_key": KEY, "query": query, "language": "zh-CN"}, proxies=P, timeout=15)
    return r.json()

def get_detail(tmdb_id, type_="movie"):
    url = f"https://api.themoviedb.org/3/{type_}/{tmdb_id}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
    return r.json()

# Search for Korean thriller/crime/fantasy series
print("=== 韩国悬疑/犯罪/奇幻 ===")
results = search("韩国 悬疑 电视剧", "search/tv")
for item in results.get("results", [])[:5]:
    print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"))

print("\n=== 美国科幻/惊悚 ===")
results = search("美国 科幻 惊悚 电视剧", "search/tv")
for item in results.get("results", [])[:5]:
    print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"))

print("\n=== 日本动画 ===")
results = search("日本 动画", "search/tv")
for item in results.get("results", [])[:5]:
    print(item.get("name"), item.get("id"), item.get("vote_average"), item.get("vote_count"))
