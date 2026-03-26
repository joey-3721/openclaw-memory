import sys, os, requests, json
sys.path.insert(0,"/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

already_ids = {int(x) for x in ['127529','11423','27205','283566','500664','518068','766507','110356','117376','125988','135340','1411','1429','209867','220542','226529','230923','31911','60625','64840','66330','70626','76479','85937','95396','95479','96571','99494','13855','155','264660','329865','396535','397567','435601','488623','496243','4977','568160','581528','670','687163','838209','9323','950396','100088','108261','108284','110316','110534','113268','119051','124364','127532','129552','13916','1415','155226','200709','235577','246','253905','280945','40075','42509','64010','65931','67915','72548','73944','75006','83097','87108','90447','90814','92685','92983','9343','94954','95557','96160','96648','96777','99966']}

# Check 还魂 (The Uncanny Counter) - 135157 - Korean fantasy/suspense
url = f"https://api.themoviedb.org/3/tv/135157"
params = {"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}
r = requests.get(url, params=params, proxies=P, timeout=15)
d = r.json()
print(f"还魂 (ID:135157):")
print(f"  Title: {d.get('name')} / {d.get('original_name')}")
print(f"  Rating: {d.get('vote_average')} / {d.get('vote_count')}")
print(f"  Genres: {[g['name'] for g in d.get('genres', [])]}")
print(f"  Countries: {[c['english_name'] for c in d.get('production_countries', [])]}")
print(f"  Year: {d.get('first_air_date', '')[:4]}")
print(f"  Overview: {d.get('overview', '')[:300]}")
print(f"  Seasons: {d.get('number_of_seasons')}, Episodes: {d.get('number_of_episodes')}")
# Check seasons
for s in d.get('seasons', []):
    print(f"  Season {s['season_number']}: {s['episode_count']} eps, air: {s['air_date']}")

print()

# Check 新世纪福音战士 (990) - Japanese anime
url2 = f"https://api.themoviedb.org/3/tv/890"
r2 = requests.get(url2, params=params, proxies=P, timeout=15)
d2 = r2.json()
print(f"新世纪福音战士 (ID:890):")
print(f"  Title: {d2.get('name')} / {d2.get('original_name')}")
print(f"  Rating: {d2.get('vote_average')} / {d2.get('vote_count')}")
print(f"  Genres: {[g['name'] for g in d2.get('genres', [])]}")
print(f"  Year: {d2.get('first_air_date', '')[:4]}")
print(f"  Overview: {d2.get('overview', '')[:300]}")
print(f"  Seasons: {d2.get('number_of_seasons')}, Episodes: {d2.get('number_of_episodes')}")
