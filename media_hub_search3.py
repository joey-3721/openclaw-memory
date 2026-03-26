import sys, os, requests
sys.path.insert(0,"/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m

KEY = m.read_tmdb_key()
P = {"http":"http://192.168.50.209:7890","https":"http://192.168.50.209:7890"}

def get_show(id_):
    url = f"https://api.themoviedb.org/3/tv/{id_}"
    r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "keywords"}, proxies=P, timeout=15)
    d = r.json()
    try:
        countries = [c.get("english_name", c.get("name", "?")) for c in d.get("production_countries", [])]
    except:
        countries = [c.get("name", "?") for c in d.get("production_countries", [])]
    try:
        keywords = [k["name"] for k in d.get("keywords", {}).get("results", [])[:10]]
    except:
        keywords = []
    print(f"Title: {d.get('name')} / {d.get('original_name')}")
    print(f"Year: {d.get('first_air_date','')[:4]}")
    print(f"Rating: {d.get('vote_average')} Votes: {d.get('vote_count')}")
    print(f"Genres: {[g['name'] for g in d.get('genres', [])]}")
    print(f"Countries: {countries}")
    print(f"Overview: {d.get('overview','')[:400]}")
    print(f"Poster: {d.get('poster_path')}")
    print(f"Keywords: {keywords}")
    print()

get_show(135157)  # 还魂
get_show(113268)  # 惊奇的传闻
get_show(92983)   # 浪客行
