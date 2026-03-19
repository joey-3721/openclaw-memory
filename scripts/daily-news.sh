#!/bin/bash
# 每日重要新闻获取脚本
# 用法: bash /home/node/.openclaw/workspace-user1/scripts/daily-news.sh

cd /home/node/.openclaw/workspace-user1

# 获取今日日期
TODAY=$(date +%Y年%m月%d日)

# 搜索今日新闻
RESULT=$(curl -s "https://api.minimaxi.com/anthropic" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(cat /home/node/.openclaw/openclaw.json | jq -r '.auth.profiles.minimax:cn.provider')" \
  -d '{
    "model": "MiniMax-M2.7",
    "max_tokens": 2000,
    "messages": [
      {
        "role": "user",
        "content": "请搜索今日（'"$TODAY"'）重要财经新闻，包括：美股收盘情况、美联储FOMC动态、中概股/港股行情、地缘政治影响、大宗商品价格、A股权重板块。整理成简洁的中文新闻简报格式，分点列出，控制在500字以内。重点关注美股、美国经济、中国经济相关动态。"
      }
    ]
  }' 2>/dev/null)

echo "$RESULT"
