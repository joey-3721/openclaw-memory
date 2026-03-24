from datetime import datetime, timedelta

from ..db import ensure_schema, get_conn


def demo_dashboard():
    today = datetime.now()
    return {
        "site_stats": {
            "net_worth": "¥ 428,560",
            "cash_balance": "¥ 126,480",
            "month_income": "¥ 48,200",
            "month_spending": "¥ 17,380",
            "budget_usage": 63,
            "monthly_saving_rate": 64,
        },
        "accounts": [
            {"name": "招商银行卡", "type": "现金账户", "balance": "¥ 58,420", "change": "+2.6%", "tone": "mint"},
            {"name": "支付宝余额", "type": "日常流动", "balance": "¥ 8,960", "change": "+8.3%", "tone": "sky"},
            {"name": "盈米基金", "type": "投资账户", "balance": "¥ 213,700", "change": "+4.9%", "tone": "violet"},
            {"name": "应急备用金", "type": "储蓄目标", "balance": "¥ 36,000", "change": "目标 72%", "tone": "amber"},
        ],
        "trend": [
            {"label": (today - timedelta(days=6 - i)).strftime("%m-%d"), "income": v[0], "spend": v[1]}
            for i, v in enumerate([(5, 2), (7, 3), (8, 6), (9, 4), (6, 5), (11, 7), (10, 4)])
        ],
        "category_mix": [
            {"name": "生活", "amount": "¥ 6,420", "share": 37, "color": "#15b79e"},
            {"name": "订阅", "amount": "¥ 1,860", "share": 11, "color": "#7c3aed"},
            {"name": "出行", "amount": "¥ 2,540", "share": 15, "color": "#fb7185"},
            {"name": "餐饮", "amount": "¥ 3,980", "share": 23, "color": "#f59e0b"},
            {"name": "其他", "amount": "¥ 2,580", "share": 14, "color": "#3b82f6"},
        ],
        "budgets": [
            {"name": "餐饮预算", "spent": 3980, "limit": 5200, "ratio": 77},
            {"name": "出行预算", "spent": 2540, "limit": 3000, "ratio": 85},
            {"name": "娱乐预算", "spent": 1120, "limit": 2200, "ratio": 51},
        ],
        "activities": [
            {"title": "工资到账", "meta": "工商银行 · 今天 09:20", "amount": "+¥ 32,000", "kind": "inflow"},
            {"title": "房租支出", "meta": "银行卡自动扣款 · 昨天", "amount": "-¥ 4,500", "kind": "outflow"},
            {"title": "基金定投", "meta": "盈米基金 · 周一", "amount": "-¥ 2,000", "kind": "transfer"},
            {"title": "咖啡与午餐", "meta": "支付宝 · 周一", "amount": "-¥ 86", "kind": "outflow"},
        ],
        "db_status": {"ok": False, "message": "当前显示演示数据，数据库接入后可逐步替换。"},
    }


def load_dashboard_from_db():
    data = demo_dashboard()
    try:
        conn = get_conn()
        ensure_schema(conn)

        account_count = conn.execute("SELECT COUNT(*) AS cnt FROM finance_accounts").fetchone()["cnt"]
        tx_count = conn.execute("SELECT COUNT(*) AS cnt FROM finance_transactions").fetchone()["cnt"]
        active_budget_count = conn.execute("SELECT COUNT(*) AS cnt FROM finance_budgets").fetchone()["cnt"]
        balance_row = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) AS total_balance FROM finance_accounts WHERE is_active=1"
        ).fetchone()
        outflow_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total_spend
            FROM finance_transactions
            WHERE direction='expense'
              AND DATE_FORMAT(happened_at, '%%Y-%%m') = DATE_FORMAT(CURDATE(), '%%Y-%%m')
            """
        ).fetchone()

        data["site_stats"].update(
            {
                "net_worth": f"¥ {balance_row['total_balance']:,.0f}",
                "cash_balance": f"{account_count} 个账户",
                "month_income": f"{tx_count} 条流水",
                "month_spending": f"¥ {outflow_row['total_spend']:,.0f}",
                "budget_usage": min(100, 25 + active_budget_count * 12),
            }
        )
        data["db_status"] = {"ok": True, "message": "数据库已连接，当前页面使用真实概览 + 演示布局。"}

        rows = conn.execute(
            """
            SELECT account_name, account_type, balance
            FROM finance_accounts
            WHERE is_active=1
            ORDER BY balance DESC, id DESC
            LIMIT 4
            """
        ).fetchall()
        if rows:
            tone_map = ["mint", "sky", "violet", "amber"]
            data["accounts"] = [
                {
                    "name": row["account_name"],
                    "type": row["account_type"],
                    "balance": f"¥ {row['balance']:,.2f}",
                    "change": "已连接",
                    "tone": tone_map[idx % len(tone_map)],
                }
                for idx, row in enumerate(rows)
            ]

        conn.close()
        return data
    except Exception as exc:
        data["db_status"] = {"ok": False, "message": f"数据库暂未连接，当前显示演示数据。错误：{exc}"}
        return data
