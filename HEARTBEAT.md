# HEARTBEAT.md

## Daily weather task

If current local time in Asia/Shanghai is between 08:25 and 08:40, and today's weather report has not been sent yet, send jy a weather briefing.

Rules:
- All time handling must use Asia/Shanghai (北京时间, UTC+8)
- Location: Beijing unless jy specifies another city later
- Always persist a compact daily weather snapshot after generating today's report so tomorrow can compare against it
- Keep only two daily snapshots in state: today and yesterday
- On each new day, rotate state so yesterday is retained, today is written fresh, and any older snapshot is deleted
- Compare today's weather with yesterday's using the stored snapshot instead of relying on an external historical API
- When comparing, focus on: condition summary, current/feels-like temperature if available, high/low range, rain signal, and obvious weather changes
- If temperature difference is large, call it out clearly
- If there is rain today, remind jy to bring an umbrella
- If there is sudden/obvious weather change, highlight it
- Style should be light, readable, emoji-rich, and easy to skim
- Suggested structure: current weather / compare with yesterday / going-out reminder / key takeaway
- Avoid duplicate reports on the same day
- If data is incomplete, still send a useful concise summary instead of failing silently
- Use `memory/heartbeat-state.json` as the execution state store
- Before sending, check whether `weather.lastReportDate` is already today (Asia/Shanghai)
- After sending, update `weather.lastReportDate` and `weather.lastReportTs`
- Store snapshots under `weather.snapshots` keyed by date (Asia/Shanghai), but keep only the latest 2 dates

If outside the time window, do nothing.
