import sys, os, requests, json

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m
KEY = m.read_tmdb_key()
PROXIES = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

already_ids = ['11423','27205','283566','500664','518068','766507','110356','117376','125988','135157','135340','1411','1429','209867','220542','226529','230923','31911','60625','64840','66330','70626','76479','85937','95396','95479','96571','99494','637649','110534','127529','155226','200709','253905','280945','64010','73944','87108','94954','96648']

def check(media_type, tmdb_id, label=""):
    sid = str(tmdb_id)
    if sid in already_ids:
        print(f"[SKIP] {label or tmdb_id} already")
        return None
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=PROXIES, timeout=15)
        d = r.json()
        title = d.get("name") or d.get("title", "")
        year = (d.get("first_air_date") or d.get("release_date") or "")[:4]
        vote = d.get("vote_average", 0)
        votes = d.get("vote_count", 0)
        genres = [g["name"] for g in d.get("genres", [])]
        countries = [c["name"] for c in d.get("production_countries", [])]
        overview = d.get("overview", "")
        poster = d.get("poster_path", "")
        print(f"\n[NEW!] {label} | TMDB {tmdb_id} | {title} ({year})")
        print(f"  Rating: {vote}/10 ({votes} votes)")
        print(f"  Genres: {genres}")
        print(f"  Countries: {countries}")
        print(f"  Poster: {poster}")
        print(f"  Overview: {overview[:200]}")
        return {"id": tmdb_id, "type": media_type, "title": title, "year": year, "vote": vote, "votes": votes, "genres": genres, "countries": countries, "overview": overview, "poster": poster}
    except Exception as e:
        print(f"[ERR] {label} {tmdb_id}: {e}")
        return None

results = []

# 1. Korean thriller movies
print("=== Korean Thriller/Crime Movies ===")
r = requests.get("https://api.themoviedb.org/3/discover/movie", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "with_genres": "53,80",  # thriller, crime
    "with_original_language": "ko",
    "vote_count.gte": 500,
    "vote_average.gte": 7.5,
    "page": 1
}, proxies=PROXIES, timeout=20)
for item in r.json().get("results", [])[:8]:
    res = check("movie", item["id"], item.get("title",""))
    if res: results.append(res)

# 2. Japanese anime - movie (high rated)
print("\n=== Japanese Animation Movies ===")
r2 = requests.get("https://api.themoviedb.org/3/discover/movie", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "with_genres": "16,878",  # animation, sci-fi
    "with_original_language": "ja",
    "vote_count.gte": 1000,
    "vote_average.gte": 7.5,
    "page": 1
}, proxies=PROXIES, timeout=20)
for item in r2.json().get("results", [])[:8]:
    res = check("movie", item["id"], item.get("title",""))
    if res: results.append(res)

# 3. Korean thriller TV not yet covered
print("\n=== Korean Horror/Thriller TV ===")
r3 = requests.get("https://api.themoviedb.org/3/discover/tv", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "with_genres": "18,10765,80",  # drama, sci-fi, crime
    "with_original_language": "ko",
    "vote_count.gte": 300,
    "vote_average.gte": 8.0,
    "page": 1
}, proxies=PROXIES, timeout=20)
for item in r3.json().get("results", [])[:8]:
    res = check("tv", item["id"], item.get("name",""))
    if res: results.append(res)

print(f"\n\n=== TOTAL NEW CANDIDATES: {len(results)} ===")
for r in results:
    print(f"  TMDB {r['id']} ({r['type']}): {r['title']} ({r['year']}) - {r['vote']}/10 | {r['genres']}")
