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
- The message format must be deterministic and consistent across models: same section order, same headings, same bullet style, same emoji anchors, and no freeform restructuring
- If some data is missing, keep the same template and fill the slot with `暂无数据` instead of changing layout
- Keep wording concise and stable; do not switch between radically different tones or formats across days/models
- Use exactly the fixed template below when sending the daily weather briefing
- Avoid duplicate reports on the same day
- If data is incomplete, still send a useful concise summary instead of failing silently
- Use `memory/heartbeat-state.json` as the execution state store
- Before sending, check whether `weather.lastReportDate` is already today (Asia/Shanghai)
- After sending, update `weather.lastReportDate` and `weather.lastReportTs`
- Store snapshots under `weather.snapshots` keyed by date (Asia/Shanghai), but keep only the latest 2 dates

Fixed template (use this exact section order every time):

📍 {city}天气简报｜{date}

【现在天气】
- 天气：{condition}
- 温度：{currentTemp}°C（体感 {feelsLike}°C）
- 湿度：{humidity}%
- 风况：{wind}

【今天情况】
- 最高 / 最低：{high}°C / {low}°C
- 降雨：{rainText}
- 变化：{todayChangeSummary}

【相比昨天】
- 温度对比：{tempCompare}
- 天气对比：{conditionCompare}
- 提醒：{compareReminder}

【出门建议】
- {advice1}
- {advice2}

【一句话总结】
- {oneLineSummary}

Template emoji rules:
- Add emoji to section headings based on context (not fixed): e.g., 🌧️ for rain, ☀️ for sunny, 🌡️ for temperature, 🌬️ for windy
- Use emoji freely in content to enhance readability
- But keep the five sections and their order fixed
- Do not add extra sections or change the structure

Template rules:
- Keep the five sections exactly as written
- Keep bracketed headings exactly as written
- Use bullet list marker `- ` only
- Do not add extra headers, intro text, outro text, markdown tables, or code blocks
- `rainText` should be one short phrase such as `无雨` / `有小雨，建议带伞`
- `todayChangeSummary` should summarize today's notable trait in one short phrase
- `tempCompare` should include a concrete delta when yesterday data exists; otherwise say `昨日数据暂缺，今日已记录，明天可对比`
- `conditionCompare` should compare condition change when yesterday data exists; otherwise say `昨日数据暂缺`
- `compareReminder` should be one short actionable reminder
- `oneLineSummary` should be one short sentence, not multiple sentences

If outside the time window, do nothing.
