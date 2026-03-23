# Media Hub 本地开发指南

## 项目概述
Media Hub 是一个基于 FastAPI 的 Web 应用，用于管理和推荐影视内容。它从 TMDB 获取数据和封面，并提供个性化推荐。

---

## 一、克隆仓库

```bash
git clone https://github.com/joey-3721/openclaw-memory.git
cd openclaw-memory/apps/media-hub
```

---

## 二、Python 环境与依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 三、本地 MySQL 数据库

### 3.1 启动本地 MySQL（推荐用 Docker）

```bash
docker run --name local-media-hub-mysql \
  -e MYSQL_ROOT_PASSWORD=MediaHub2026! \
  -e MYSQL_DATABASE=media_hub \
  -d -p 3307:3306 mysql:8.0
```

> 端口用 `3307` 是为了避免和 NAS 上的 `3306` 冲突（你本地也可以用 `3306`，只要不冲突就行）。

### 3.2 初始化表结构

连接本地 MySQL：
```bash
mysql -h 127.0.0.1 -P 3307 -u root -pMediaHub2026! media_hub
```

执行建表 SQL：
```sql
CREATE USER IF NOT EXISTS 'joey'@'%' IDENTIFIED WITH mysql_native_password BY 'Joey@2026!';
GRANT ALL PRIVILEGES ON media_hub.* TO 'joey'@'%';
FLUSH PRIVILEGES;

USE media_hub;
CREATE TABLE IF NOT EXISTS douban_watch_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject_id VARCHAR(255) UNIQUE,
    title TEXT,
    original_title TEXT,
    kind VARCHAR(50),
    year INT,
    pubdate TEXT,
    url TEXT,
    cover_url TEXT,
    douban_rating REAL,
    douban_rating_count INT,
    tmdb_id VARCHAR(255),
    genres TEXT,
    countries TEXT,
    languages TEXT,
    tags TEXT,
    actors TEXT,
    directors TEXT,
    writers TEXT,
    intro TEXT,
    summary TEXT,
    my_rating REAL,
    comment TEXT,
    status VARCHAR(50),
    added_at DATETIME,
    updated_at DATETIME,
    watch_count INT DEFAULT 1,
    last_watch_date DATETIME,
    recommendation_note TEXT,
    recommended_at DATETIME,
    recommend_rank INT,
    recommend_source VARCHAR(255),
    recommend_feedback TEXT,
    feedback_updated_at DATETIME,
    dislike_reason TEXT,
    rating_source TEXT,
    comment_source TEXT
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recommendation_cache (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cache_key TEXT,
    timestamp DATETIME,
    data JSON,
    expires_at DATETIME
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3.3 从 NAS 导入数据（可选）

如果你想把 NAS 上的线上数据库同步到本地：

**第一步：在 NAS 上导出（SSH 到 NAS 后执行）：**
```bash
docker exec media-hub-mysql mysqldump -u root -pMediaHub2026! media_hub > ~/media_hub_dump.sql
```

**第二步：复制到 Mac：**
```bash
scp your_nas_user@YOUR_NAS_IP:~/media_hub_dump.sql .
```

**第三步：导入本地：**
```bash
mysql -h 127.0.0.1 -P 3307 -u root -pMediaHub2026! media_hub < media_hub_dump.sql
```

---

## 四、环境变量配置

`app.py` 通过以下环境变量连接 MySQL（括号内为默认值）：

| 变量名 | 说明 | 线上默认值 | 本地开发建议值 |
|---|---|---|---|
| `MYSQL_HOST` | 数据库地址 | `172.17.0.5`（容器内IP） | `127.0.0.1` |
| `MYSQL_PORT` | 数据库端口 | `3306` | `3307`（如果你用 3306 则不用改） |
| `MYSQL_USER` | 数据库用户名 | `joey` | `joey` |
| `MYSQL_PASSWORD` | 数据库密码 | `Joey@2026!` | `Joey@2026!` |
| `MYSQL_DB` | 数据库名 | `media_hub` | `media_hub` |
| `MEDIA_HUB_COVERS_DIR` | 封面图片目录 | `/app/covers` | `./covers`（相对路径） |

在 `apps/media-hub/` 目录下创建 `.env` 文件（已在 `.gitignore` 里，不会提交）：
```
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_USER=joey
MYSQL_PASSWORD=Joey@2026!
MYSQL_DB=media_hub
MEDIA_HUB_COVERS_DIR=./covers
```

然后在启动前 export 这些变量：
```bash
export $(cat .env | xargs)
```

或者直接在命令行前缀指定：
```bash
MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 uvicorn app:app --host 0.0.0.0 --port 8765 --reload
```

---

## 五、封面图片

本地运行时，封面目录默认是 `/app/covers`（容器路径），需要改成本地路径。

```bash
# 在 apps/media-hub/ 下创建 covers 目录
mkdir -p covers
```

如果你想把线上封面同步到本地：
```bash
# 从 NAS 复制（SSH 到 NAS 后确认路径）
scp -r your_nas_user@YOUR_NAS_IP:/volume1/@docker/volumes/media-hub-covers/_data/ ./covers/
```

---

## 六、启动应用

```bash
cd openclaw-memory/apps/media-hub
source venv/bin/activate
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3307
export MYSQL_USER=joey
export MYSQL_PASSWORD=Joey@2026!
export MYSQL_DB=media_hub
export MEDIA_HUB_COVERS_DIR=./covers

uvicorn app:app --host 0.0.0.0 --port 8765 --reload
```

访问 `http://localhost:8765` 查看应用。

`--reload` 模式下代码改动后会自动重启，开发效率很高。

---

## 七、Git 工作流

```bash
# 开始开发前先拉取最新代码
git pull

# 开发、修改...

# 提交
git add .
git commit -m "你改了什么"
git push
```

推上去后，NAS 上我（OpenClaw）会拉取最新代码并重建 Docker 镜像。

---

## 八、线上 vs 本地差异对比

| 项目 | NAS 线上 | Mac 本地 |
|---|---|---|
| 运行方式 | Docker 容器 | 直接 `uvicorn` |
| 端口 | `8765`（NAS IP:8765） | `8765`（localhost:8765） |
| MySQL Host | `172.17.0.5`（容器内IP） | `127.0.0.1` |
| MySQL Port | `3306` | `3307`（或 3306） |
| 封面目录 | `/app/covers`（Docker volume） | `./covers`（本地目录） |
| TMDB 代理 | `192.168.50.209:7890` | 你 Mac 本地的代理 |
