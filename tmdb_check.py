import sys, os, requests
os.environ['HTTP_PROXY'] = 'http://192.168.50.209:7890'
os.environ['HTTPS_PROXY'] = 'http://192.168.50.209:7890'
sys.path.insert(0,'/app')
import app as m
KEY = m.read_tmdb_key()
P = {'http':'http://192.168.50.209:7890','https':'http://192.168.50.209:7890'}

for tmdb_id, label in [('94605', '双城之战'), ('95557', '无敌少侠'), ('40075', '怪诞小镇'), ('89456', '史前战纪')]:
    r = requests.get(f'https://api.themoviedb.org/3/tv/{tmdb_id}', 
        params={'api_key':KEY,'language':'zh-CN','append_to_response':'credits,genres'},
        proxies=P, timeout=15)
    d = r.json()
    print(f'=== {label} ({tmdb_id}) ===')
    print(f'Name: {d.get("name")} / {d.get("original_name")}')
    print(f'Rating: {d.get("vote_average")}, Votes: {d.get("vote_count")}')
    print(f'Overview: {d.get("overview","")[:200]}')
    genres = [g['name'] for g in d.get('genres', [])]
    print(f'Genres: {genres}')
    print()
