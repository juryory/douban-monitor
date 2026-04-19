# 实现说明

当前 skill 已包含一个完整可运行的主脚本，位置在 `scripts/monitor.py`。

## 当前模块职责

### 豆瓣抓取（Frodo → Rexxar 双通道）

- `frodo_get(...)`
  调用豆瓣 Frodo API，自动完成 HMAC-SHA1 签名。
- `fetch_douban_collection_via_frodo(...)` / `fetch_douban_subject_detail_via_frodo(...)`
  通过 Frodo API 获取榜单候选或条目详情。
- `rexxar_get(...)`
  调用 `m.douban.com` 移动网页版 Rexxar API，无需签名。
- `fetch_douban_collection_via_rexxar(...)` / `fetch_douban_subject_detail_via_rexxar(...)`
  Rexxar 版的榜单和详情抓取，字段与 Frodo 一致，可直接互换。
- `fetch_douban_weekly_candidates_lite(...)`
  榜单候选抓取入口：先试 Frodo，任一榜单失败自动改用 Rexxar。
- `fetch_douban_subject_detail_lite(...)`
  详情补全入口：同样 Frodo 失败时自动降级到 Rexxar。

### 通用模块

- `fetch_tmdb_hot_candidates_with_config(...)`
  调用 TMDB 热门接口获取补充候选。
- `update_library(...)`
  应用入库规则、分配观察层级、刷新监控库条目。
- `update_state(...)`
  判定首次提醒和二次提醒。
- `render_report(...)`
  输出每日 Markdown 报告。
- `build_result_json(...)`
  生成前端结果数据，每条达标条目附带 `qualified_at` / `first_discovered_at`。

### 网页数据生成

- `fetch_favorites.py`
  读取 `data/douban-monitor-favorites.json` 的手动收藏豆瓣 ID，通过 Rexxar API 获取详情，同时附带 TMDB 封面和元数据。
- `fetch_posters.py`
  从 TMDB 获取封面图 URL。查找策略：Frodo/Rexxar 取 IMDB ID → TMDB `/find/{imdb_id}`（最准确）→ TMDB 标题模糊搜索（逐步简化标题，去除季数后缀，拆分中外文混合词）。
  输出：`data/douban-monitor-posters.json`
- `fetch_metadata.py`
  从 TMDB 获取 original_title、overview、genres、runtime、release_date、cast 等。使用与 fetch_posters.py 相同的 IMDB→TMDB 查找策略。
  输出：`data/douban-monitor-metadata.json`
- `fetch_reviews.py`
  抓取豆瓣短评。
  输出：`data/douban-monitor-reviews.json`

## Python 依赖

仅使用 Python 标准库，无需 `pip install` 额外依赖。

## 环境变量

- `TMDB_API_KEY`
- `TMDB_BEARER_TOKEN`

通常只需要 `TMDB_API_KEY`。`TMDB_BEARER_TOKEN` 是另一种认证方式，不是必需项。

## 当前数据策略

- 候选发现
  豆瓣多榜单页 + TMDB 热门接口
- 评分与评分人数真值
  豆瓣详情页（Frodo 优先，Rexxar 兜底）
- TMDB 作用
  补充展示元数据，不覆盖豆瓣评分和评分人数
- 网页数据生成
  `fetch_posters.py` / `fetch_metadata.py` / `fetch_reviews.py` 从 TMDB 和豆瓣获取展示用数据
- 数据版本管理
  `data/` 和 `reports/` 目录纳入 Git 跟踪，每次运行后自动提交推送
- 抓取失败兜底
  候选为 0 时跳过 Markdown 报告和 `result.json` 的写入，保留上一份好数据；git pull 失败或检测到冲突标记时中止提交

当前已验证的榜单：

- 电影榜
- 华语剧集榜
- 全球剧集榜
- 国内综艺榜
- 国外综艺榜
