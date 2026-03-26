import requests, sys

PROXIES = {"http":"http://192.168.50.209:7890","https":"http://192.168.50.209:7890"}
sys.path.insert(0, "/app")
import app as m
KEY = m.read_tmdb_key()

def get_details(tmdb_id, media_type):
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    params = {"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}
    r = requests.get(url, params=params, proxies=PROXIES, timeout=15)
    return r.json()

d = get_details("124364", "tv")
print("Name:", d.get('name'))
print("Original Name:", d.get('original_name'))
print("Rating:", d.get('vote_average'))
print("Votes:", d.get('vote_count'))
print("Poster:", d.get('poster_path'))
print("Overview:", d.get('overview'))
print("Genres:", [g['name'] for g in d.get('genres', [])])
print("Countries:", [c['name'] for c in d.get('production_countries', [])])
print("First Air:", d.get('first_air_date'))
print("Last Air:", d.get('last_air_date'))
print("Seasons:", d.get('number_of_seasons'))
print("Episodes:", d.get('number_of_episodes'))
print("Status:", d.get('status'))

# Also get English overview
url = f"https://api.themoviedb.org/3/tv/124364"
params = {"api_key": KEY, "language": "en-US"}
r = requests.get(url, params=params, proxies=PROXIES, timeout=15)
en_d = r.json()
print("\nEnglish Overview:", en_d.get('overview'))
