import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

ALREADY_REC = [127529,11423,27205,283566,500664,518068,110356,117376,125988,135340,1411,1429,209867,220542,226529,230923,31911,60625,64840,66330,70626,76479,95396,95479,96571,99494,1376434,13855,155,264660,280,290098,329865,396535,397567,435601,488623,496243,4977,530254,568160,581528,670,679,687163,752,756999,78,838209,9323,950396,100088,108261,108284,110316,110534,113268,119051,124364,127532,129552,13916,1415,155226,200709,208336,235577,246,253905,280945,40075,42509,46896,64010,65931,67915,72548,73944,75006,83097,87108,90447,90814,92685,92983,9343,94954,95269,95557,96160,96648,96777,99966]

# Check candidate: 还魂 (135157)
for tmdb_id in [135157, 66433, 221851, 136369]:
    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
    d = r.json()
    name = d.get("name", d.get("title"))
    rating = d.get("vote_average")
    votes = d.get("vote_count")
    overview = d.get("overview", "")
    genres = [g["name"] for g in d.get("genres", [])]
    countries = d.get("origin_country", [])
    poster = d.get("poster_path")
    year = d.get("first_air_date", "")[:4] if d.get("first_air_date") else ""
    in_rec = "ALREADY" if tmdb_id in ALREADY_REC else "NEW"
    print(f"[{in_rec}] {name} ({year}) | rating={rating} | votes={votes}")
    print(f"  genres={genres} | countries={countries}")
    print(f"  poster_path={poster}")
    print(f"  overview: {overview[:300]}")
    print()
