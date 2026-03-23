# HEARTBEAT.md

> ⚠️ **心跳模式已废弃（2026-03-23）**
> 推荐维护已迁移至 OpenClaw Cron（每 30 分钟自动执行），不再依赖飞书消息触发心跳。

---

## 推荐维护 Cron 任务

**任务 ID：** `8646f048-e671-4f92-8bc1-2f21b983148c`
**调度：** 每 30 分钟一次（`every 30m`，isolated session）
**投递方式：** `--no-deliver`（结果不发送飞书，只写日志）
**查看执行记录：** `openclaw cron runs --id 8646f048-e671-4f92-8bc1-2f21b983148c`

---

## 执行流程（每 30 分钟自动触发）

### 1. 查询推荐数量
```bash
docker exec media-hub-test python3 -c "import sys; sys.path.insert(0, '/app'); import app as m; conn=m.get_conn(); r=conn.execute(\"SELECT COUNT(*) as cnt FROM douban_watch_history WHERE status='recommended'\").fetchone(); print('count:', r['cnt']); conn.close()"
```

### 2. 判断逻辑
- `count < 100` → 执行补充流程
- `count ≥ 100` → 跳过，记录原因到心跳日志

### 3. 补充 SOP（count < 100 时）
1. 读用户口味（collect 高分 + dislike 理由 + 偏好题材/国家）
2. TMDB 搜索候选（requests + proxy `192.168.50.209:7890`）
3. 去重检查（tmdb_id 已在库则跳过，跳过时记录具体原因）
4. 下载封面（`app.download_cover_to_local`，封面不可用则跳过并记录）
5. LLM 生成个性化推荐语（禁止模板化，结合剧情简介和用户背景）
6. `REPLACE INTO` 写入 MySQL（`app.get_conn()`）
7. 验证封面文件存在且 >1KB

### 4. 记录心跳日志（必须）
追加到 `memory/heartbeat-log.md`：
```
| UTC时间 | 北京时间 | cron | 推荐维护 | 状态描述 |
```

**必须记录的节点：**
- ✅ 写入成功：`"写入X条，当前共N条"`
- ⏭️ 跳过：`"已达N条，不补充"` 或 `"tmdb:XXX已存在，跳过"`
- ⚠️ 失败：`"原因"`（proxy不通 / TMDB超时 / 封面下载失败 / MySQL连接失败）

---

## 数据库规则（MySQL）
- 生产库：MySQL `media_hub`（容器 `media-hub-mysql`，端口 3306）
- 访问：`docker exec media-hub-test python3 -c "import app; conn=app.get_conn(); ..."`
- 禁止写 SQLite 本地文件，禁止写 workspace 开发副本

## 查看 Cron 执行记录
```bash
# 列出最近执行记录
openclaw cron runs --id 8646f048-e671-4f92-8bc1-2f21b983148c

# 手动触发一次（测试用）
openclaw cron run 8646f048-e671-4f92-8bc1-2f21b983148c
```

## 剩余可做项
- 看完推荐后自动从推荐列表移除或降低权重
- 继续抓取 collect 列表剩余封面（鱿鱼游戏2/3暂无可用封面）
- 金融模块入口（待后续）
