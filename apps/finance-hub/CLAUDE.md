# Finance Hub — Developer Guidelines

## Project Overview
Personal asset tracking system. FastAPI + Jinja2 SSR + Chart.js. MySQL backend.
Primary use: track US stocks/bonds/cash positions, display all values in CNY.

## Architecture Principles
- **Single responsibility**: Each class/file handles one concern. Split functions into
  separate classes/files by domain (auth, assets, market data, dashboard, exchange rates).
- **Minimal methods**: Keep methods short (<30 lines). Extract helpers early.
- **Descriptive names**: Functions describe what they return or do. No abbreviations.
  e.g., `fetch_daily_close_prices()` not `get_prices()`.

## Mobile-First (CRITICAL)
- iPhone is the primary device. Design for 375px width first.
- CSS: write mobile styles as defaults, use `min-width` media queries for larger screens.
- Touch targets: minimum 44×44px.
- Bottom navigation bar is primary nav on mobile.

## Database
- MySQL via PyMySQL + DBUtils connection pool.
- **Pool max size: 20 connections.** Never exceed this.
- **NEVER** open connections inside loops. Batch queries instead.
- Use parameterized queries exclusively. No string interpolation for SQL.
- All tables: utf8mb4, COLLATE utf8mb4_unicode_ci.

## Common Pitfalls
- 数据库连接池上限是 20，别在循环里开新连接

## Python Style
- Formatter: `ruff format` with line-width = 88.
- Linter: `ruff check`.
- Type hints on all function signatures.
- No wildcard imports.

## File Organization
- `finance_app/services/` — business logic, one file per domain.
- `finance_app/routes/` — HTTP layer only, delegates to services.
- `static/js/` — one JS file per page/feature.
- `templates/` — Jinja2 templates, one per page.

## Commands
- Run: `uvicorn app:app --host 0.0.0.0 --port 8766 --reload`
- Format: `ruff format .`
- Lint: `ruff check . --fix`
