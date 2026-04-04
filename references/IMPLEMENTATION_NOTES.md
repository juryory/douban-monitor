# 实现说明

当前 skill 已包含一个完整可运行的主脚本，位置在 `scripts/monitor.py`。

## 当前模块职责

### 轻量模式（Frodo API）

- `frodo_get(...)`
  调用豆瓣 Frodo API，自动完成 HMAC-SHA1 签名。

- `fetch_douban_collection_via_frodo(...)`
  通过 Frodo API 获取豆瓣榜单候选列表。

- `fetch_douban_subject_detail_via_frodo(...)`
  通过 Frodo API 获取条目详情（评分、评分人数、标题、年份）。

- `fetch_douban_weekly_candidates_lite(...)`
  轻量模式下的榜单候选抓取入口。

- `fetch_douban_subject_detail_lite(...)`
  轻量模式下的详情补全入口。

### 完整模式（浏览器）

- `extract_weekly_candidates_with_browser(...)`
  使用 Playwright 打开豆瓣榜单页，从浏览器 DOM 中提取候选标题。

- `resolve_candidate_urls_from_collection_page(...)`
  对没有直链的榜单候选，直接在榜单页内点击对应卡片，回填详情页链接。

- `fetch_douban_subject_detail(...)`
  访问豆瓣详情页，提取标题、评分、评分人数和年份。
  如果普通 HTML 请求拿不到关键字段，会自动回退到浏览器抓取。

### 通用模块

- `fetch_tmdb_hot_candidates_with_config(...)`
  调用 TMDB 热门接口获取补充候选。

- `update_library(...)`
  应用入库规则、分配观察层级、刷新监控库条目。

- `update_state(...)`
  判定首次提醒和二次提醒。

- `render_report(...)`
  输出每日 Markdown 报告。

## Python 依赖

轻量模式不需要额外依赖，仅使用 Python 标准库。

完整模式需要 `playwright`：

```bash
pip install playwright
python -m playwright install chromium
```

## Linux 容器依赖

轻量模式不需要任何系统级依赖。

完整模式要求容器内具备浏览器自动化运行环境。
如果使用 Playwright 自带 Chromium，通常需要额外安装 Linux 系统库，例如：

```bash
apt-get update && apt-get install -y libnspr4 libnss3 libatk1.0-0 libdbus-1-3 libcups2 libxkbcommon0 libatspi2.0-0 libgbm1 libasound2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2
```

如果容器中已经有可用浏览器与依赖，也可以直接通过 `config.toml` 中的 `browser_executable_path` 复用。

## 环境变量

- `TMDB_API_KEY`
- `TMDB_BEARER_TOKEN`

通常只需要 `TMDB_API_KEY`。`TMDB_BEARER_TOKEN` 是另一种认证方式，不是必需项。

## 当前数据策略

- 候选发现
  豆瓣多榜单页 + TMDB 热门接口
- 评分与评分人数真值
  豆瓣详情页
- 抓取分层
  榜单页走浏览器，详情页走 HTML，必要时浏览器兜底
- 补链接策略
  优先使用榜单页卡片点击补详情页链接
- TMDB 作用
  补充展示元数据，不覆盖豆瓣评分和评分人数

当前已验证：

- 电影榜
- 华语剧集榜
- 全球剧集榜
- 国外综艺榜

待单独适配：

- 国内综艺榜
