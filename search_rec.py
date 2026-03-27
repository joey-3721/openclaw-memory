import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m
KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Candidates: Korean/American thriller/fantasy/crime
candidates = [
    ("tv", 131159, "Sweet Home"),
    ("tv", 1416, "怪奇物语"),
    ("tv", 80762, "Death's Game"),
    ("tv", 215322, "A Killer Paradox"),
    ("tv", 116277, "Hotel Del Luna"),
    ("tv", 202369, "Moving"),
    ("tv", 226519, "The Glory"),
    ("tv", 215273, "Mask Girl"),
    ("tv", 224537, "The Uncanny Counter"),
    ("tv", 100712, "Voice"),
]

already = [670, 110356, 117376, 125988, 135157, 135340, 1411, 1429, 200709, 209867, 220542, 226529, 230923, 253905, 280945, 31911, 488623, 500664, 518068, 60625, 64840, 66330, 70626, 76479, 84369, 85937, 95396, 95479, 96571, 96648, 99494, 70523, 73944, 87108, 90814, 94954, 110534, 11423, 27205, 283566, 766507]

results = []
for media_type, tmdb_id, hint in candidates:
    if tmdb_id in already:
        print(f"SKIP already rec: {tmdb_id}")
        continue
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
        r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
        d = r.json()
        title = d.get("name", d.get("title", hint))
        vote = d.get("vote_average", 0)
        votes = d.get("vote_count", 0)
        poster = d.get("poster_path", "")
        overview = (d.get("overview") or "")[:200]
        genres = [g["name"] for g in d.get("genres", [])]
        year = (d.get("first_air_date") or d.get("release_date", ""))[:4]
        countries = [c["name"] for c in d.get("production_countries", [])]
        print(f"CAND|{tmdb_id}|{title}|{vote}|{votes}|{year}|{genres}|{countries}|{poster}|{overview}")
        if vote >= 7.5 and votes >= 200:
            results.append((vote, votes, tmdb_id, media_type, title, genres, countries, poster, overview, year))
    except Exception as e:
        print(f"ERR {tmdb_id}: {e}")

print("\n=== QUALIFIED (vote>=7.5, votes>=200) ===")
results.sort(reverse=True)
for r in results:
    print(f"{r[0]}|{r[1]}|{r[2]}|{r[3]}|{r[4]}|{r[5]}|{r[6]}")
