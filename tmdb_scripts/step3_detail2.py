import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Check 66433 - 步步惊心：丽
url = f"https://api.themoviedb.org/3/tv/66433"
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
seasons = d.get("number_of_seasons", 0)
print(f"Title: {name} / {original_name}")
print(f"Year: {year} | Seasons: {seasons}")
print(f"Rating: {rating} ({votes} votes)")
print(f"Genres: {genres}")
print(f"Countries: {countries}")
print(f"Poster: {poster}")
print(f"Overview: {overview}")

# Also check 221851 - 和我老公结婚吧
url2 = f"https://api.themoviedb.org/3/tv/221851"
r2 = requests.get(url2, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
d2 = r2.json()
name2 = d2.get("name")
original_name2 = d2.get("original_name")
rating2 = d2.get("vote_average")
votes2 = d2.get("vote_count")
overview2 = d2.get("overview", "")
genres2 = [g["name"] for g in d2.get("genres", [])]
countries2 = d2.get("origin_country", [])
poster2 = d2.get("poster_path")
year2 = d2.get("first_air_date", "")[:4]
seasons2 = d2.get("number_of_seasons", 0)
print(f"\nTitle: {name2} / {original_name2}")
print(f"Year: {year2} | Seasons: {seasons2}")
print(f"Rating: {rating2} ({votes2} votes)")
print(f"Genres: {genres2}")
print(f"Countries: {countries2}")
print(f"Poster: {poster2}")
print(f"Overview: {overview2}")
