# HEARTBEAT.md

## Daily weather task

If current local time in Asia/Shanghai is between 08:25 and 08:40, and today's weather report has not been sent yet, send jy a weather briefing.

Rules:
- All time handling must use Asia/Shanghai (北京时间, UTC+8)
- Location: Beijing unless jy specifies another city later
- Compare today's weather with yesterday's when possible
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

If outside the time window, do nothing.
