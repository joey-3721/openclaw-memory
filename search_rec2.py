import sys, os, requests, json
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m
KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

already = [670, 110356, 117376, 125988, 135157, 135340, 1411, 1429, 200709, 209867, 220542, 226529, 230923, 253905, 280945, 31911, 488623, 500664, 518068, 60625, 64840, 66330, 70626, 76479, 84369, 85937, 95396, 95479, 96571, 96648, 99494, 70523, 73944, 87108, 90814, 94954, 110534, 11423, 27205, 283566, 766507]

def search_and_check(query, media_type="tv", year=None):
    params = {"api_key": KEY, "query": query, "language": "zh-CN", "include_adult": False}
    if year:
        params["primary_release_year"] = year
    r = requests.get(f"https://api.themoviedb.org/3/search/{media_type}", params=params, proxies=P, timeout=15)
    results = r.json().get("results", [])
    if not results:
        return None
    # Get top result
    top = results[0]
    tmdb_id = top["id"]
    if tmdb_id in already:
        print(f"SKIP already rec: {query} -> {tmdb_id}")
        return None
    # Fetch full details
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    r2 = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
    d = r2.json()
    title = d.get("name", d.get("title", query))
    vote = d.get("vote_average", 0)
    votes = d.get("vote_count", 0)
    poster = d.get("poster_path", "")
    overview = (d.get("overview") or "")[:200]
    genres = [g["name"] for g in d.get("genres", [])]
    year_str = (d.get("first_air_date") or d.get("release_date", ""))[:4]
    countries = [c["name"] for c in d.get("production_countries", [])]
    print(f"\n=== {title} (TMDB:{tmdb_id}) ===")
    print(f"Vote: {vote} ({votes} votes) | Year: {year_str}")
    print(f"Genres: {genres}")
    print(f"Countries: {countries}")
    print(f"Poster: {poster}")
    print(f"Overview: {overview}")
    if vote >= 7.5 and votes >= 200:
        print(f"✅ QUALIFIED")
        return (tmdb_id, media_type, title, genres, countries, poster, overview, year_str, vote, votes)
    else:
        print(f"❌ Below threshold: vote={vote}, votes={votes}")
        return None

# Search for Korean thriller/fantasy series
print("=== Korean Thriller/Fantasy ===")
results = []
r = search_and_check("Sweet Home", "tv")
if r: results.append(r)
r = search_and_check("Moving 2023", "tv")
if r: results.append(r)
r = search_and_check("The Glory", "tv")
if r: results.append(r)
r = search_and_check("Mask Girl", "tv")
if r: results.append(r)
r = search_and_check("A Killer Paradox", "tv")
if r: results.append(r)
r = search_and_check("Death's Game", "tv")
if r: results.append(r)
r = search_and_check("Squid Game", "tv")
if r: results.append(r)

print("\n\n=== American Sci-Fi/Thriller ===")
r = search_and_check("The Last of Us", "tv")
if r: results.append(r)
r = search_and_check("Severance", "tv")
if r: results.append(r)
r = search_and_check("From", "tv")
if r: results.append(r)
r = search_and_check("Yellowjackets", "tv")
if r: results.append(r)

print("\n\n=== Japanese Animation Thriller ===")
r = search_and_check("Parasyte", "tv")
if r: results.append(r)
r = search_and_check("Monster anime", "tv")
if r: results.append(r)
r = search_and_check("The Promised Neverland", "tv")
if r: results.append(r)
r = search_and_check("attack on titan", "tv")
if r: results.append(r)

print("\n\n=== SUMMARY ===")
for item in results:
    print(f"{item[8]}|{item[9]}|{item[0]}|{item[2]}")
