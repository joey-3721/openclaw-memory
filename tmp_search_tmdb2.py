import sys, os, requests, json

sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"

import app as m
KEY = m.read_tmdb_key()
PROXIES = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

already_ids = ['11423','27205','283566','500664','518068','766507','110356','117376','125988','135157','135340','1411','1429','209867','220542','226529','230923','31911','60625','64840','66330','70626','76479','85937','95396','95479','96571','99494','637649','110534','127529','155226','200709','253905','280945','64010','73944','87108','94954','96648']

# Try Signal (信号) Korean TV series TMDB ID: 69350
# Try checking a few candidates
candidates = [
    ("tv", 69350, "信号 / Signal"),
    ("tv", 1416, "都市疑案 / Criminal Minds"),
    ("tv", 456, " law & order"),
    ("tv", 66611, "Voice"),
    ("tv", 74123, "西班牙惊悚 series"),
    ("movie", 397860, "泰国天才枪手续集"),
    ("tv", 115977, "韩综"),
]

for media_type, tmdb_id, name in candidates:
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        r = requests.get(url, params={
            "api_key": KEY, "language": "zh-CN",
            "append_to_response": "credits"
        }, proxies=PROXIES, timeout=15)
        d = r.json()
        title = d.get("name", d.get("title", ""))
        vote = d.get("vote_average", 0)
        votes = d.get("vote_count", 0)
        overview = d.get("overview", "")[:100]
        genres = [g["name"] for g in d.get("genres", [])]
        countries = [c["name"] for c in d.get("production_countries", [])]
        poster = d.get("poster_path", "")
        print(f"\n--- {name} (TMDB {tmdb_id}) ---")
        print(f"Title: {title}")
        print(f"Rating: {vote}/10 ({votes} votes)")
        print(f"Genres: {genres}")
        print(f"Countries: {countries}")
        print(f"Poster: {poster}")
        print(f"Overview: {overview}")
    except Exception as e:
        print(f"Error for {name}: {e}")
