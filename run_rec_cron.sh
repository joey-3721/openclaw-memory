#!/bin/bash
while true; do
  docker exec -e PYTHONPATH=/app media-hub-test python /app/scripts/cron_add_recommendation.py >> /home/node/.openclaw/workspace-user1/logs/cron_rec.log 2>&1
  echo "--- ran at $(date) ---" >> /home/node/.openclaw/workspace-user1/logs/cron_rec.log
  sleep 1800
done
