# Finance Hub 本地开发指南

Finance Hub 是一个基于 FastAPI + Jinja2 + MySQL 的轻量财务仪表盘原型，风格与 `media-hub` 不同，主打浅色卡片、干净留白和移动端友好。

## 目录

- `app.py`: 后端入口
- `templates/`: 页面模板
- `static/style.css`: 样式文件
- `scripts/init_finance_hub.sql`: 建库建表 SQL
- `.env.local`: 本地调试数据库配置

## 本地启动

```bash
cd apps/finance-hub
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export $(cat .env.local | xargs)
uvicorn app:app --host 0.0.0.0 --port 8766 --reload
```

访问：`http://localhost:8766`

## 数据库

默认代码里的数据库连接参数：

```env
MYSQL_HOST=172.17.0.5
MYSQL_PORT=3306
MYSQL_USER=joey
MYSQL_PASSWORD=Joey@2026!
MYSQL_DB=finance_hub
```

本地开发建议使用 `.env.local`：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_USER=joey
MYSQL_PASSWORD=Joey@2026!
MYSQL_DB=finance_hub
```

如果数据库还没创建，先执行：

```bash
mysql -h 127.0.0.1 -P 3307 -u root -p < scripts/init_finance_hub.sql
```

## 当前状态

- 已有首页仪表盘框架
- 已有响应式布局
- 已有数据库表结构
- 业务逻辑目前是演示数据优先，数据库接入后可逐步替换

## 后续推荐扩展

- 账户资产趋势
- 月度现金流分析
- 分类支出明细
- 预算预警
- 固定账单与订阅管理
