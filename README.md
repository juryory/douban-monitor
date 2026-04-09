# OpenClaw 豆瓣高分监控 Skill

这个项目是一个运行在 OpenClaw 环境中的豆瓣高分影视监控 skill，用来发现豆瓣里"近期新出现并达到门槛"的电影、剧集、综艺等内容。

默认规则：

- 豆瓣评分大于 `8.0`
- 豆瓣评分人数大于 `3000`

## 工作方式

支持两种运行模式，通过 `config.toml` 中的 `mode` 字段切换：

- **轻量模式**（`mode = "lite"`，默认）
  通过豆瓣 Frodo API 获取榜单候选和详情数据，不需要浏览器环境
- **完整模式**（`mode = "full"`）
  使用 Playwright 浏览器抓取豆瓣榜单，详情页优先 HTML 解析
- **TMDB**
  作为候选补充和展示元数据来源（封面、简介、类型等）

默认抓取的豆瓣榜单（全部已验证可用）：

- 电影
- 华语剧集
- 全球剧集
- 国内综艺
- 国外综艺

## 目录结构

- `SKILL.md`
  skill 规则与策略说明
- `config.toml`
  非敏感运行参数
- `.env.example`
  环境变量模板（TMDB API key）
- `requirements.txt`
  Python 依赖
- `index.html`
  可视化网页，展示监控库中的达标内容
- `scripts/monitor.py`
  主执行脚本（7 步流程）
- `scripts/fetch_posters.py`
  从 TMDB 获取封面图 URL
- `scripts/fetch_metadata.py`
  从 TMDB 获取简介、类型、时长等元数据
- `data/`
  运行产生的 JSON 数据文件（result、posters、metadata）
- `reports/`
  每日 Markdown 报告
- `.github/workflows/monitor.yml`
  GitHub Actions 定时执行配置
- `references/`
  示例配置、状态文件和实现说明

## 运行依赖

### 轻量模式

仅使用 Python 标准库，无额外依赖。

### 完整模式

需要 `playwright`：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Linux 容器中还需要安装 Playwright 所依赖的系统库：

```bash
apt-get update && apt-get install -y libnspr4 libnss3 libatk1.0-0 libdbus-1-3 libcups2 libxkbcommon0 libatspi2.0-0 libgbm1 libasound2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2
```

### TMDB 数据

封面和元数据获取需要 `TMDB_API_KEY`，参考 `.env.example` 配置：

```bash
cp .env.example .env
# 编辑 .env 填入你的 TMDB API Key
```

## 配置建议

- `SKILL.md`
  放监控规则、默认行为、已知限制和后续扩展方向
- `.env`
  只放密钥或敏感环境变量，例如 `TMDB_API_KEY`
- `config.toml`
  放非敏感运行参数，例如阈值、观察期、多榜单候选源地址和浏览器参数

## 运行方式

建议使用绝对路径运行：

```bash
python3 /home/node/.openclaw/skills/douban-monitor/scripts/monitor.py
```

运行后依次执行 7 个步骤，并写入以下文件：

- `data/douban-monitor-state.json`（状态文件）
- `data/douban-monitor-library.json`（监控库）
- `data/douban-monitor-result.json`（达标结果）
- `data/douban-monitor-posters.json`（封面 URL）
- `data/douban-monitor-metadata.json`（TMDB 元数据）
- `reports/douban-monitor-YYYYMMDD.md`（Markdown 报告）

步骤 6 会自动调用 `fetch_posters.py` 和 `fetch_metadata.py` 生成网页所需数据。
步骤 7 会自动将 `data/` 和 `reports/` 的变更提交并推送到 GitHub。

## 自动运行

项目配置了 GitHub Actions（`.github/workflows/monitor.yml`），每天北京时间 09:00 和 21:00 自动执行。也支持在 Actions 页面手动触发（workflow_dispatch）。

需要在仓库 Settings → Secrets and variables → Actions 中配置 `TMDB_API_KEY`。

## 当前状态

当前版本已经具备这些能力：

- 多榜单候选抓取（5 个榜单全部打通）
- 豆瓣详情页评分和评分人数核验
- 状态文件与监控库维护
- Markdown 报告生成
- 新增命中与继续观察判定
- 网页可视化展示（瀑布流卡片、封面、简介、评分）
- TMDB 封面和元数据自动获取
- GitHub Actions 定时自动运行

## 已知限制

- 轻量模式依赖豆瓣 Frodo API，如果接口变更或限流需要关注
- 完整模式下少量详情页在特定环境下可能无法稳定提取评分或评分人数
- 未配置 `TMDB_API_KEY` 时，TMDB 候选源和网页封面/元数据不会生效
- 未配置豆瓣 Cookie 时，不依赖豆瓣搜索页补链接

## 后续方向

- 支持豆瓣 Cookie，提升抓取稳定性
- 接入 MoviePilot，实现命中内容自动推送或下载
- 生成适合公众号发布的内容稿件
