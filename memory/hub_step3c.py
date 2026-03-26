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

ALREADY = ['127529', '11423', '27205', '283566', '500664', '518068', '766507', '110356', '117376', '125988', '135340', '1411', '1429', '209867', '220542', '226529', '230923', '31911', '60625', '64840', '66330', '70626', '76479', '85937', '95396', '95479', '96571', '99494', '329865', '435601', '488623', '4977', '581528', '670', '687163', '838209', '100088', '108261', '108284', '110534', '119051', '129552', '135238', '13916', '155226', '200709', '218230', '253905', '280945', '64010', '67915', '73944', '87108', '90447', '90814', '94954', '96648', '99966']

# Check candidates not in ALREADY
candidates = [
    ("124364", "tv"),   # From - not in ALREADY
    ("86831", "tv"),    # Love Death Robots - not in ALREADY
    ("157065", "tv"),   # The Fall of the House of Usher - not in ALREADY
]

for cid, ct in candidates:
    if cid not in ALREADY:
        d = get_details(cid, ct)
        print(f"=== {cid} {d.get('name')} / {d.get('original_name')} ===")
        print(f"Rating: {d.get('vote_average')} | Votes: {d.get('vote_count')} | Lang: {d.get('original_language')}")
        print(f"Genres: {[g['name'] for g in d.get('genres', [])]}")
        print(f"Countries: {[c['name'] for c in d.get('production_countries', [])]}")
        print(f"First Air: {d.get('first_air_date')} | Status: {d.get('status')}")
        print(f"Overview: {d.get('overview','')[:300]}")
        # Check if it's a sequel/low-rated franchise
        print(f"Number of seasons: {d.get('number_of_seasons')}")
        print()
