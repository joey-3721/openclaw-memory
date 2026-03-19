Run locally:
1) python3 -m pip install --user --break-system-packages -r requirements.txt
2) uvicorn app:app --host 0.0.0.0 --port 8765 --app-dir /home/node/.openclaw/workspace-user1/apps/media-hub
Then open http://NAS_IP:8765
