import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Already recommended IDs (from previous step)
ALREADY_REC = [127529,11423,27205,283566,500664,518068,766507,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,83907,95396,95479,96571,99494,1376434,13855,155,264660,280,290098,329865,396535,397567,435601,488623,496243,4977,530254,568160,581528,670,679,687163,752,756999,78,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Candidates to check: Signal (76479), Moving (76669), Sweet Home (12610)
candidates = [
    (76479, "tv"),    # Signal
    (76669, "tv"),    # Moving
    (12610, "tv"),    # Sweet Home
]

for tmdb_id, media_type in candidates:
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
    d = r.json()
    name = d.get("name", d.get("title"))
    rating = d.get("vote_average")
    votes = d.get("vote_count")
    overview = d.get("overview", "")[:200]
    genres = [g["name"] for g in d.get("genres", [])]
    countries = [c for c in d.get("origin_country", [])]
    poster = d.get("poster_path")
    year = None
    if d.get("first_air_date"):
        year = d["first_air_date"][:4]
    elif d.get("release_date"):
        year = d["release_date"][:4]
    in_rec = "YES" if tmdb_id in ALREADY_REC else "NO"
    print(f"[{'ALREADY' if in_rec=='YES' else 'NEW'}] {name} ({year}) | rating={rating} | votes={votes} | genres={genres} | countries={countries} | poster={poster}")
    print(f"  overview: {overview}")
    print()
