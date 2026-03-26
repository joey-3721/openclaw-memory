import sys, os, requests, json

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m
KEY = m.read_tmdb_key()
PROXIES = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

already_ids = ['11423','27205','283566','500664','518068','766507','110356','117376','125988','135157','135340','1411','1429','209867','220542','226529','230923','31911','60625','64840','66330','70626','76479','85937','95396','95479','96571','99494','637649','110534','127529','155226','200709','253905','280945','64010','73944','87108','94954','96648']

def check_show(media_type, tmdb_id, label):
    if str(tmdb_id) in already_ids:
        print(f"[SKIP - already] {label} ({tmdb_id})")
        return None
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        r = requests.get(url, params={
            "api_key": KEY, "language": "zh-CN",
            "append_to_response": "credits"
        }, proxies=PROXIES, timeout=15)
        d = r.json()
        title = d.get("name") or d.get("title") or "N/A"
        vote = d.get("vote_average", 0)
        votes = d.get("vote_count", 0)
        genres = [g["name"] for g in d.get("genres", [])]
        overview = d.get("overview", "")[:200]
        poster = d.get("poster_path", "")
        year = (d.get("first_air_date") or d.get("release_date") or "")[:4]
        print(f"[CHECK] {label} ({tmdb_id}) = {title} ({year}) | {vote}/10 ({votes} votes) | {genres}")
        print(f"  Poster: {poster}")
        print(f"  Overview: {overview[:150]}")
        return {"id": tmdb_id, "type": media_type, "title": title, "year": year, "vote": vote, "votes": votes, "genres": genres, "poster": poster, "overview": overview}
    except Exception as e:
        print(f"[ERR] {label}: {e}")
        return None

# Korean shows not in already list
candidates = []

# From discover results - page 2
print("=== Page 2 Korean TV ===")
r = requests.get("https://api.themoviedb.org/3/discover/tv", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "with_genres": "18,80",
    "with_original_language": "ko",
    "vote_count.gte": 200,
    "vote_average.gte": 7.5,
    "page": 2
}, proxies=PROXIES, timeout=20)
data = r.json()
for item in data.get("results", [])[:10]:
    tmdb_id = item["id"]
    if str(tmdb_id) not in already_ids:
        candidates.append(check_show("tv", tmdb_id, f"{item.get('name','')}"))

# Korean movies thriller
print("\n=== Korean Movies Thriller ===")
r2 = requests.get("https://api.themoviedb.org/3/discover/movie", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "with_genres": "53,80,878",  # thriller, crime, sci-fi
    "with_original_language": "ko",
    "vote_count.gte": 200,
    "vote_average.gte": 7.5,
    "page": 1
}, proxies=PROXIES, timeout=20)
data2 = r2.json()
print(f"Korean movies found: {data2.get('total_results', 0)}")
for item in data2.get("results", [])[:10]:
    tmdb_id = item["id"]
    if str(tmdb_id) not in already_ids:
        candidates.append(check_show("movie", tmdb_id, f"{item.get('title','')}"))

# American sci-fi / thriller TV
print("\n=== American Sci-Fi TV ===")
r3 = requests.get("https://api.themoviedb.org/3/discover/tv", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "with_genres": "10765,16",  # sci-fi & fantasy, animation
    "with_original_language": "en",
    "vote_count.gte": 500,
    "vote_average.gte": 8.0,
    "page": 1
}, proxies=PROXIES, timeout=20)
data3 = r3.json()
for item in data3.get("results", [])[:10]:
    tmdb_id = item["id"]
    if str(tmdb_id) not in already_ids:
        candidates.append(check_show("tv", tmdb_id, f"{item.get('name','')}"))
