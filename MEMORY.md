# MEMORY.md

## User preferences

- 佳奕 is my human and I am their private assistant.
- 佳奕's default timezone is **Asia/Shanghai (北京时间, UTC+8)**.
- All scheduling, reminders, weather reports, and time references should use **Beijing time** unless 佳奕 explicitly says otherwise.
- 佳奕 cares a lot about **US stocks, the US economy, and China economic news**.
- Daily weather briefing preference: send around **08:30 Beijing time**, compare with yesterday, call out large temperature swings or obvious weather changes, remind about umbrellas when rain is expected, and use a light emoji-rich style.
- Weather reports should use one deterministic fixed template every day so outputs stay consistent across different models; if a field is missing, keep the same layout and fill with `暂无数据`.
- For weather comparison, persist a compact daily snapshot in `memory/heartbeat-state.json`, compare against yesterday's stored snapshot, and retain only the latest two days of weather snapshots (today + yesterday).
- Weather heartbeat execution state should be stored in `memory/heartbeat-state.json` to avoid duplicate same-day reports.

## Workspace / git

- Workspace repo: `git@github.com:joey-3721/openclaw-memory.git`
- Git identity: `joey-3721 <lijiayi3721@gmail.com>`
- Local `post-commit` hook auto-pushes commits to origin.
- Important memory/config updates should be committed so they sync to GitHub.
- 佳奕 prefers a more automated workflow: once changes are stable and verified, commit them automatically without asking every single time.
- Agent Reach 已安装（2026-03-19），路径：`~/.openclaw/skills/agent-reach`
  - 当前 9/15 渠道激活（YouTube、V2EX、RSS、全网搜索、Twitter/X、Reddit、B站、微信公众号、任意网页）
  - 未激活需进一步配置：微博、小红书、抖音、小宇宙（需要 Docker 或 ffmpeg）、LinkedIn（需要 pip install）、GitHub gh CLI
  - npm 全局包目录：~/.npm-global（已配置）
  - pip 安装路径：~/.local/bin（pip3 可用）
- 豆瓣影视库维护方案已建立（2026-03-19）
  - 数据库文件：`/home/node/.openclaw/workspace-user1/douban/douban_media.db`
  - Skill 路径：`/home/node/.openclaw/skills/douban-library-sync/SKILL.md`
  - 一键同步脚本：`/home/node/.openclaw/skills/douban-library-sync/scripts/sync_douban.py`
  - 当前已抓取并补全 283 条豆瓣“看过”记录，并已同步 `wish` 17 条
  - 后续只要佳奕提到“豆瓣相关/豆瓣推荐/同步豆瓣/豆瓣库”，应优先使用这套本地库与 skill
  - 如果 Douban Cookie 失效或缺失，要主动向佳奕索要新的 Cookie，再执行同步或补全
- NAS Media Hub 已建立（2026-03-19）
  - 代码目录：`/home/node/.openclaw/workspace-user1/apps/media-hub`
  - 当前部署方式：Docker
  - 镜像名：`media-hub:latest`
  - 容器名：`media-hub-test`
  - 访问端口：`8765`
  - 部署/更新 Skill：`/home/node/.openclaw/skills/media-hub-nas-deploy/SKILL.md`
  - 后续只要佳奕让我改 Media Hub 页面，我应默认执行：改代码 → 重建镜像 → 重启容器 → 验证 → git commit → git push

## 媒体推荐规则（Media Hub）

### 强制排除内容
- **中国3D动漫**：一律不推荐（包括但不限于《秦时明月》《斗罗大陆》《斗破苍穹》等国产3D动画风格作品）
- 规则更新时间：2026-03-22

### 佳奕偏好
- 喜欢：美剧、电影、以及非中国产的影视内容
- 具体偏好可随时更新

---

## Model routing

- Model policy preference: default to `minimax/MiniMax-M2.5` for simple lookups, lightweight queries, and easy tasks. Switch to `duomi/gpt-5.4` for tasks that are even moderately complex, logic-heavy, multi-step, coding-related, configuration-heavy, or require stronger reasoning. Git/commit/push alone are not automatically considered complex; use judgment based on the overall task.
- Desired routing behavior is message-level in spirit: MiniMax should be treated as the first-pass classifier/default path, while `duomi/gpt-5.4` should take over for moderately complex tasks or whenever MiniMax is unreliable/unavailable.
- Fallback rule: if MiniMax/provider auth/timeout/unavailable/parse issues occur or are strongly suspected, fall back directly to `duomi/gpt-5.4` instead of blocking.
- Once a task is judged complex, keep that task on `duomi/gpt-5.4` until completion for stability.
- User-facing replies in main session should use `[[reply_to_current]]` at the top and end with a model attribution line like: `—— 来自模型：xxx`.
- Default model for main session: `anthropic/claude-sonnet-4-6` (set 2026-03-23 per 佳奕 request).
- For small, routine, low-risk self-optimizations or maintenance changes, avoid explicitly reporting every tiny action to 佳奕; just do them unless they materially affect behavior, need approval, are risky, or are worth surfacing.
- For minor fixes, low-risk debugging, and small configuration repairs, I should proactively try to fix them end-to-end by myself, verify whether they are resolved, and iterate a few times before asking 佳奕 to confirm or intervene. Only escalate early if the action is risky, externally impactful, destructive, blocked by permissions/access, or genuinely unclear.
