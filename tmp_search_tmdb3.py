import sys, os, requests, json

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m
KEY = m.read_tmdb_key()
PROXIES = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

already_ids = ['11423','27205','283566','500664','518068','766507','110356','117376','125988','135157','135340','1411','1429','209867','220542','226529','230923','31911','60625','64840','66330','70626','76479','85937','95396','95479','96571','99494','637649','110534','127529','155226','200709','253905','280945','64010','73944','87108','94954','96648']

# Discover Korean TV thriller/crime with high rating
print("=== Discover Korean TV Thriller ===")
r = requests.get("https://api.themoviedb.org/3/discover/tv", params={
    "api_key": KEY, "language": "zh-CN",
    "sort_by": "vote_average.desc",
    "with_genres": "18,80",  # drama, crime
    "with_original_language": "ko",
    "vote_count.gte": 200,
    "vote_average.gte": 7.5,
    "page": 1
}, proxies=PROXIES, timeout=20)
data = r.json()
print(f"Total results: {data.get('total_results', 0)}")
for item in data.get("results", [])[:10]:
    print(f"\nID: {item['id']} | {item.get('name','')} ({item.get('first_air_date','')[:4]}) | Score: {item['vote_average']} ({item['vote_count']} votes)")
    print(f"Overview: {item.get('overview','')[:150]}")

# Also search by specific Korean show names
print("\n\n=== Checking specific shows ===")
shows_to_check = [
    ("tv", 69411, "Signal (韩剧)"),
    ("tv", 1396, "Stranger (秘密森林)"),
    ("tv", 75006, "Voice (声音)"),
    ("tv", 135738, "Kingdom (王国)"),
    ("tv", 80752, "My Name (第三人称)"),
    ("tv", 71912, "Through the Darkness"),
    ("tv", 128839, "Beyond Evil (恶之人)"),
    ("tv", 115977, "Mouse (窥探)"),
]

for media_type, tmdb_id, name in shows_to_check:
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
        overview = d.get("overview", "")[:120]
        poster = d.get("poster_path", "")
        year = (d.get("first_air_date") or d.get("release_date") or "")[:4]
        in_already = str(tmdb_id) in already_ids
        print(f"\n{'[ALREADY]' if in_already else '[NEW]'} {name} (TMDB {tmdb_id})")
        print(f"  Title: {title} ({year})")
        print(f"  Rating: {vote}/10 ({votes} votes)")
        print(f"  Genres: {genres}")
        print(f"  Poster: {poster}")
        print(f"  Overview: {overview}")
    except Exception as e:
        print(f"Error for {name}: {e}")
