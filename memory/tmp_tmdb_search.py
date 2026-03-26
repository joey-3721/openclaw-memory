import sys, os, requests, json
sys.path.insert(0,"/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# 已推荐的ID（转整数）
already_ids = {int(x) for x in ['127529','11423','27205','283566','500664','518068','766507','110356','117376','125988','135340','1411','1429','209867','220542','226529','230923','31911','60625','64840','66330','70626','76479','85937','95396','95479','96571','99494','13855','155','264660','329865','396535','397567','435601','488623','496243','4977','568160','581528','670','687163','838209','9323','950396','100088','108261','108284','110316','110534','113268','119051','124364','127532','129552','13916','1415','155226','200709','235577','246','253905','280945','40075','42509','64010','65931','67915','72548','73944','75006','83097','87108','90447','90814','92685','92983','9343','94954','95557','96160','96648','96777','99966']}

# TMDB search endpoints - try Korean suspense/crime/fantasy
search_queries = [
    # ("search/tv", {"query": "kingdom", "language": "zh-CN"}),
    ("discover/tv", {"language": "zh-CN", "sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "with_genres": "18,10765", "without_genres": "16", "page": 1}),
    ("discover/movie", {"language": "zh-CN", "sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "with_genres": "878,53", "without_genres": "16", "page": 1}),
    ("discover/tv", {"language": "zh-CN", "sort_by": "vote_average.desc", "vote_count.gte": 200, "vote_average.gte": 7.5, "with_genres": "10765,18", "page": 1}),
]

for endpoint, params in search_queries:
    url = f"https://api.themoviedb.org/3/{endpoint}"
    params["api_key"] = KEY
    try:
        r = requests.get(url, params=params, proxies=P, timeout=15)
        d = r.json()
        results = d.get("results", [])
        print(f"\n=== {endpoint} ===")
        for item in results[:10]:
            tmdb_id = item.get("id", 0)
            if tmdb_id not in already_ids:
                title = item.get("name") or item.get("title", "")
                vote = item.get("vote_average", 0)
                votes = item.get("vote_count", 0)
                genre_ids = item.get("genre_ids", [])
                overview = item.get("overview", "")[:100]
                print(f"  [ID:{tmdb_id}] {title} | {vote}/{votes} | genres:{genre_ids} | {overview}")
    except Exception as e:
        print(f"Error: {e}")
