import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Get full details for 还魂 (135157)
url = "https://api.themoviedb.org/3/tv/135157"
r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
d = r.json()
name = d.get("name")
original_name = d.get("original_name")
rating = d.get("vote_average")
votes = d.get("vote_count")
overview = d.get("overview", "")
genres = [g["name"] for g in d.get("genres", [])]
countries = d.get("origin_country", [])
poster = d.get("poster_path")
year = d.get("first_air_date", "")[:4]

# Get season count
seasons = d.get("number_of_seasons", 0)

print(f"Title: {name} / {original_name}")
print(f"Year: {year}")
print(f"Rating: {rating} ({votes} votes)")
print(f"Seasons: {seasons}")
print(f"Genres: {genres}")
print(f"Countries: {countries}")
print(f"Poster: {poster}")
print(f"Overview: {overview}")
