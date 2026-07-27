# OpenClaw 豆瓣高分监控 Skill

这个项目是一个运行在 OpenClaw 环境中的豆瓣高分影视监控 skill，用来发现豆瓣里"近期新出现并达到门槛"的电影、剧集、综艺等内容。

默认规则：

- 豆瓣评分大于 `8.0`
- 豆瓣评分人数大于 `3000`

## 快速开始（新手）

第一次拉取仓库后，按下面几步就能跑通：

1. **准备环境**
   需要 Python **3.11+**（脚本用到标准库 `tomllib`，3.11 起才内置）。无第三方依赖，不用 `pip install`。

2. **配置 TMDB Key（可选但推荐）**
   ```bash
   cp .env.example .env
   # 编辑 .env，填入 TMDB_API_KEY（或 TMDB_BEARER_TOKEN，二选一）
   ```
   不填也能运行，但不会有封面、简介和 TMDB 候选源。`config.toml` 里的阈值和榜单开箱即用，一般不用改。

3. **在仓库根目录运行**
   ```bash
   python scripts/monitor.py
   ```
   ⚠️ **必须在国内网络环境运行**：豆瓣 Rexxar API 拒绝境外 IP，境外运行时第 1 步豆瓣抓取会全部失败（当日候选为 0），脚本只会保留上一份旧数据。

4. **查看结果**
   浏览器直接打开根目录 `index.html`，或查看 `reports/douban-monitor-YYYYMMDD.md`。

> 想用 GitHub Actions 自动跑，见文末「自动运行」一节。

## 工作方式

纯 HTTP 抓取，不需要浏览器环境：

- **豆瓣**
  统一通过 Rexxar API（`m.douban.com` 移动网页版接口，无需签名和 apiKey）抓取，是当前豆瓣抓取的唯一通道
- **TMDB**
  提供额外候选和展示元数据来源（封面、简介、类型等）

默认抓取的豆瓣榜单（见 `config.toml` 的 `douban_collection_urls`）：

- 电影：热门、实时热门、一周口碑
- 剧集：热门、实时热门、华语一周口碑、全球一周口碑

综艺（国内 / 国外）已停用：TMDB 几乎没有对应封面，命中率太低。

## 目录结构

- `SKILL.md`
  skill 规则与策略说明
- `config.toml`
  非敏感运行参数
- `.env.example`
  环境变量模板（TMDB API key）
- `index.html`
  可视化网页，展示监控库中的达标内容
- `scripts/monitor.py`
  主执行脚本（8 步流程）
- `scripts/fetch_favorites.py`
  读取 `data/douban-monitor-favorites.json` 中的豆瓣 ID，获取手动收藏详情
- `scripts/fetch_posters.py`
  从 TMDB 获取封面图 URL
- `scripts/fetch_metadata.py`
  从 TMDB 获取简介、类型、时长等元数据
- `scripts/fetch_reviews.py`
  从豆瓣获取短评
- `scripts/generate_detail_pages.py`
  为每个达标条目生成 `detail/<douban_id>.html` 详情页
- `data/`
  运行产生的 JSON 数据文件（state、library、result、favorites、posters、metadata、reviews）
- `detail/`
  各条目静态详情页 HTML
- `reports/`
  每日 Markdown 报告
- `.github/workflows/monitor.yml`
  GitHub Actions 执行配置（当前仅手动触发 workflow_dispatch）
- `references/`
  示例配置、状态文件和实现说明
- `tools/`
  辅助调试页面

## 运行依赖

仅使用 Python 标准库，无额外依赖。

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
  放非敏感运行参数，例如阈值、观察期、冷却窗口、多榜单候选源地址和 TMDB 设置

## 运行方式

本地在仓库根目录运行即可：

```bash
python scripts/monitor.py
```

在 OpenClaw 环境中，可使用绝对路径运行：

```bash
python3 /home/node/.openclaw/skills/douban-monitor/scripts/monitor.py
```

运行后依次执行 8 个步骤，并写入以下文件：

- `data/douban-monitor-state.json`（状态文件）
- `data/douban-monitor-library.json`（监控库，带 `qualified_at` / `first_discovered_at`）
- `data/douban-monitor-result.json`（达标结果，条目携带入库时间，供前端"最近入库"排序）
- `data/douban-monitor-favorites-result.json`（手动收藏详情）
- `data/douban-monitor-posters.json`（封面 URL）
- `data/douban-monitor-metadata.json`（TMDB 元数据）
- `data/douban-monitor-reviews.json`（豆瓣短评）
- `reports/douban-monitor-YYYYMMDD.md`（Markdown 报告）

步骤 6 生成前端结果数据 `douban-monitor-result.json`。
步骤 7 会自动调用 `fetch_favorites.py`、`fetch_posters.py`、`fetch_metadata.py`、`fetch_reviews.py`、`generate_detail_pages.py` 生成网页所需数据和详情页。
步骤 8 会自动将 `data/`、`detail/`、`reports/`、`posters/` 的变更提交并推送到 GitHub。

**容错**：若第 1、2 步抓取全部失败，当日候选为 0 时，脚本跳过第 5、6 步对报告和 `result.json` 的写入，保留上一份好数据；若第 8 步 `git pull --rebase` 失败，或待提交文件里出现合并冲突标记，脚本立即中止，不提交或推送。

## 自动运行

项目配置了 GitHub Actions（`.github/workflows/monitor.yml`），当前**仅支持在 Actions 页面手动触发**（workflow_dispatch）。定时抓取的 cron 已停用：豆瓣 API 拒绝境外 IP，GitHub 托管的 runner 无法直接抓取，定时运行改由国内 Docker 负责。

启用前需要在仓库里做两步配置：

1. **配置 Secret**
   Settings → Secrets and variables → Actions，添加 `TMDB_API_KEY`（若改用 Bearer，则添加 `TMDB_BEARER_TOKEN`，二者对应 workflow 中读取的两个环境变量）。
2. **开启写权限**
   Settings → Actions → General → Workflow permissions 选择 **Read and write permissions**，否则 workflow 里的 `git push` 会因为没有写权限而报 403。

> 注意：GitHub 托管 runner 在境外，即使手动触发，豆瓣抓取这一步也会失败，仅 TMDB 部分有效。真正的定时抓取仍需在国内网络环境（如国内 Docker）执行。

## 当前状态

当前版本已经具备这些能力：

- 多榜单候选抓取（电影 / 剧集 榜单，综艺已停用）
- 豆瓣详情页评分和评分人数核验
- 状态文件与监控库维护（含入库时间戳）
- Markdown 报告生成
- 新增命中与继续观察判定
- 网页可视化展示（瀑布流卡片、封面、简介、评分、短评）
- 手动收藏：在 `data/douban-monitor-favorites.json` 填豆瓣 ID 即可
- 最近入库排序：按真实入库时间倒序
- TMDB 封面和元数据自动获取
- 静态详情页生成（`detail/<douban_id>.html`）
- GitHub Actions 手动触发运行
- 抓取失败与推送冲突兜底：自动保留历史数据，不覆盖、不提交坏文件

## 已知限制

- 豆瓣抓取全部依赖 Rexxar API（`m.douban.com` 移动网页版接口，无需签名）。若 Rexxar 整体宕机，本次运行会跳过日报和前端结果写入，保留上一份好数据
- 豆瓣 API 拒绝境外 IP，GitHub 托管的 runner 无法直接抓取，定时运行需由国内网络环境（如国内 Docker）执行
- 未配置 `TMDB_API_KEY` 时，TMDB 候选源和网页封面/元数据不会生效

## 后续方向

- 支持豆瓣 Cookie，提升抓取稳定性
- 接入 MoviePilot，实现命中内容自动推送或下载
- 生成适合公众号发布的内容稿件
