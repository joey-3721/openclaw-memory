import sys, os, requests
sys.path.insert(0, "/app")
os.environ["HTTP_PROXY"] = "http://192.168.50.209:7890"
os.environ["HTTPS_PROXY"] = "http://192.168.50.209:7890"
import app as m
KEY = m.read_tmdb_key()
P = {"http": "http://192.168.50.209:7890", "https": "http://192.168.50.209:7890"}

# Fetch more info for writing recommendation
url = "https://api.themoviedb.org/3/tv/100088"
r = requests.get(url, params={"api_key": KEY, "language": "zh-CN", "append_to_response": "credits"}, proxies=P, timeout=15)
d = r.json()

# Get season 1 details
s1_url = "https://api.themoviedb.org/3/tv/100088/season/1"
r1 = requests.get(s1_url, params={"api_key": KEY, "language": "zh-CN"}, proxies=P, timeout=15)
s1 = r1.json()

# Get key episodes for plot hooks
print("=== KEY EPISODES ===")
for ep in s1.get("episodes", []):
    if ep.get("vote_average", 0) >= 8.5:
        print(f"Ep {ep['episode_number']}: {ep['name']} (Vote: {ep['vote_average']}) - {ep.get('overview','')[:100]}")

print("\n=== OVERVIEW ===")
print(d.get("overview"))
print("\n=== CREDITS (Main) ===")
for c in d.get("credits", {}).get("cast", [])[:5]:
    print(f"  {c['name']} as {c.get('character','')}")
