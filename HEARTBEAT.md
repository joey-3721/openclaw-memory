# HEARTBEAT.md

## 规则

- 心跳不做飞书推送，不发任何消息
- 推荐维护由 cron job（`8646f048`，每 30 分钟）独立完成，heartbeat 不重复执行
- 心跳触发时只做日志记录（heartbeat-log.md）

## 心跳日志格式

每次心跳触发后追加一行到 `memory/heartbeat-log.md`：

| UTC时间 | 北京时间 | 触发来源 | 动作 | 状态 |

状态说明：
- 🔄 收到心跳（仅记录，无动作）
- ⏭️ cron 已在执行推荐（心跳不重复执行）
- ⚠️ 异常

## 心跳触发时的动作

收到心跳时，执行以下日志记录：

```
| {UTC时间} | {北京时间} | heartbeat | 心跳触发 | 🔄 收到 |
```

然后回复 `HEARTBEAT_OK`。

## 推荐数量检查

每次心跳检查一次推荐数量是否低于阈值（低于则在 cron job 下次运行时补充）：

```bash
docker exec media-hub-test python3 /app/scripts/add_one_recommendation.py --check-count
```

结果记录到日志，不做其他动作。
