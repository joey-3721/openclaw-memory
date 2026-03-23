# HEARTBEAT.md

## 原则
- 能自己做的先做，不要等佳奕确认
- 真需要佳奕提供信息（如失效Cookie）再搁置并说明
- 主动找活，把能推进的优化都推进
- 改代码 → 验证/更新 Docker → git commit → git push

## 每次心跳自动执行

### 第一步：查询当前推荐数量（必须记录）
```bash
docker exec media-hub-test python3 -c "
import sys; sys.path.insert(0, '/app'); import app as m
conn = m.get_conn()
row = conn.execute(\"SELECT COUNT(*) as cnt FROM douban_watch_history WHERE status='recommended'\").fetchone()
print('recommended_count:', row['cnt'])
conn.close()
"
```

### 第二步：判断是否需要补充
- 若 `recommended_count` **< 100**：执行补充流程
- 若 `recommended_count` **≥ 100**：跳过补充，记录原因
- **无论是否执行，都必须记录日志**

### 第三步：补充流程（少于100条时）
每一步都要记录：
1. 开始执行：`"开始补充推荐，当前 N 条，目标 100 条"`
2. 读取口味画像（collect 数量、低评原因）
3. TMDB 搜索候选（记录搜了什么关键词/类型）
4. 每个候选的去重检查结果（已在库跳过 / 可以写入）
5. 每个候选的封面检查结果（封面存在 / 下载成功 / 下载失败）
6. 每条写入结果（成功写入 / 失败原因）
7. 写入后总数验证

### 第四步：统一记录到心跳日志（必须）
每次心跳**无论成功/失败/跳过**，都必须追加一行到 `memory/heartbeat-log.md`：

```
| {UTC时间} | {北京时间} | heartbeat | {简要动作} | {状态} |
```

**必须记录的日志级别：**
- `✅ 写入成功：X条，当前共N条`
- `⏭️ 跳过：已达 N 条（≥100），不补充`
- `⚠️ 失败：{原因}`（如 proxy 不通 / TMDB 超时 / 封面下载失败 / MySQL 连接失败）
- `🔍 排查：{发现的问题}`（如发现数量异常 / 数据不一致）

**禁止：心跳执行了但不记录**

## 数据库规则（MySQL）
- 生产库：MySQL `media_hub`（容器 `media-hub-mysql`，端口 3306）
- 访问方式：`docker exec media-hub-test python3 -c "import app; conn=app.get_conn(); ..."`
- 禁止写 SQLite 本地文件，禁止写 workspace 开发副本

## 推荐补充流程（SOP）
见 `~/.openclaw/skills/tmdb-recommendation-flow/SKILL.md`，核心步骤：
1. 读用户口味（collect 高分 + dislike 理由 + 偏好题材/国家）
2. 从 TMDB 搜索候选（requests + proxy `192.168.50.209:7890`）
3. 去重检查（tmdb_id 或 title 已在库则跳过，跳过时记录）
4. 下载封面到本地（`app.download_cover_to_local()`，封面不可用则跳过）
5. LLM 生成个性化推荐语（禁止模板化）
6. `REPLACE INTO` 写入 MySQL（`app.get_conn()`）
7. 验证封面文件存在且 >1KB

## 剩余可做项
- 看完推荐后自动从推荐列表移除或降低权重
- 继续抓取 collect 列表剩余封面（鱿鱼游戏2/3暂无可用封面）
- 金融模块入口（待后续）
