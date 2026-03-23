# HEARTBEAT.md

## 原则
- 能自己做的先做，不要等佳奕确认
- 真需要佳奕提供信息（如失效Cookie）再搁置并说明
- 主动找活，把能推进的优化都推进
- 改代码 → 验证/更新 Docker → git commit → git push

## 每次心跳自动执行
1. 查询 MySQL `media_hub.douban_watch_history` 推荐数量
2. 若 `status='recommended'` 少于 100 条，按 SOP（SKILL.md）补充推荐
3. 追加日志到 `memory/heartbeat-log.md`

## 推荐补充流程（SOP）
见 `~/.openclaw/skills/tmdb-recommendation-flow/SKILL.md`，核心：
1. 读用户口味（collect 高分 + dislike 理由 + 偏好题材/国家）
2. 从 TMDB 搜索候选（requests + proxy `192.168.50.209:7890`）
3. 去重检查（tmdb_id 或 title 已在库则跳过）
4. 下载封面到本地（`app.download_cover_to_local()`）
5. LLM 生成个性化推荐语
6. `REPLACE INTO` 写入 MySQL（`app.get_conn()`）
7. 验证封面文件存在且 >1KB

## 数据库规则（MySQL）
- 生产库：MySQL `media_hub`（容器 `media-hub-mysql`，端口 3306）
- 访问方式：`docker exec media-hub-test python3 -c "import app; conn=app.get_conn(); ..."`
- 禁止写 SQLite 本地文件，禁止写 workspace 开发副本
- 推荐计数查询：
  ```
  docker exec media-hub-test python3 -c "import app; conn=app.get_conn(); r=conn.execute(\"SELECT COUNT(*) as cnt FROM douban_watch_history WHERE status='recommended'\").fetchone(); print(r['cnt'])"
  ```

## 心跳日志格式
每次心跳结束后追加到 `memory/heartbeat-log.md`：
```
时间(UTC) | 时间(北京时间) | 触发来源 | 动作 | 状态
```

## 剩余可做项
- 看完推荐后自动从推荐列表移除或降低权重
- 继续抓取 collect 列表剩余封面（鱿鱼游戏2/3暂无可用封面）
- 金融模块入口（待后续）
- 推荐数量补充（当前2条，建议逐步补至30+条）
