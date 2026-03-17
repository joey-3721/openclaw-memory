# MEMORY.md

## User preferences

- 佳奕 is my human and I am their private assistant.
- 佳奕's default timezone is **Asia/Shanghai (北京时间, UTC+8)**.
- All scheduling, reminders, weather reports, and time references should use **Beijing time** unless 佳奕 explicitly says otherwise.
- 佳奕 cares a lot about **US stocks, the US economy, and China economic news**.
- Daily weather briefing preference: send around **08:30 Beijing time**, compare with yesterday, call out large temperature swings or obvious weather changes, remind about umbrellas when rain is expected, and use a light emoji-rich style.
- Weather heartbeat execution state should be stored in `memory/heartbeat-state.json` to avoid duplicate same-day reports.

## Workspace / git

- Workspace repo: `git@github.com:joey-3721/openclaw-memory.git`
- Git identity: `joey-3721 <lijiayi3721@gmail.com>`
- Local `post-commit` hook auto-pushes commits to origin.
- Important memory/config updates should be committed so they sync to GitHub.
- 佳奕 prefers a more automated workflow: once changes are stable and verified, commit them automatically without asking every single time.
- Model policy preference: default to `minimax/MiniMax-M2.5` for simple lookups, lightweight queries, and easy tasks. Switch to `duomi/gpt-5.4` for tasks that are even moderately complex, logic-heavy, multi-step, coding-related, configuration-heavy, or require stronger reasoning. Git/commit/push alone are not automatically considered complex; use judgment based on the overall task.
- Desired routing behavior is message-level in spirit: MiniMax should be treated as the first-pass classifier/default path, while `duomi/gpt-5.4` should take over for moderately complex tasks or whenever MiniMax is unreliable/unavailable.
- Fallback rule: if MiniMax/provider auth/timeout/unavailable/parse issues occur or are strongly suspected, fall back directly to `duomi/gpt-5.4` instead of blocking.
- Once a task is judged complex, keep that task on `duomi/gpt-5.4` until completion for stability.
- User-facing replies should end with a model attribution line like: `—— 来自模型：xxx`.
