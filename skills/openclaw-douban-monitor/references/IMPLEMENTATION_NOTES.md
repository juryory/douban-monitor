# 实现说明

当前 skill 已经包含一个 Python 执行骨架，位置在 `scripts/monitor.py`。

## 当前模块职责

- `fetch_douban_weekly_candidates_with_config(...)`
  负责读取豆瓣周榜页，提取候选条目链接。

- `fetch_tmdb_hot_candidates_with_config(...)`
  负责调用 TMDB 热门接口，例如 `trending`、`popular`。

- `resolve_with_ptgen_config(candidate, config)`
  优先使用 PtGen 静态 JSON，失败后回退到 OurHelp 的 infogen API，再尝试解析 `douban_id`、评分、评分人数、标题、年份和 `imdb_id`。

- `enrich_with_tmdb(candidate)`
  用 TMDB 补充更适合展示的元数据。

- `update_library(...)`
  应用入库规则、分配观察层级、刷新监控库条目。

- `archive_expired_library_items(...)`
  把过期或明显低价值的条目移出活跃监控。

- `update_state(...)`
  判定首次提醒和二次提醒。

- `render_report(...)`
  输出每日 Markdown 报告。

## 建议后续实现顺序

1. 把豆瓣周榜条目的标题和分类也解析出来，而不只是链接。
2. 用几个真实条目验证 PtGen 字段提取逻辑，必要时收紧解析规则。
3. 增加基于环境变量或配置文件的路径和开关配置。
4. 为入库、提醒、冷却、退库规则补单元测试。
5. 增加重试、退避和结构化日志。

## 环境变量

- `TMDB_API_KEY`
- `TMDB_BEARER_TOKEN`

当这两个变量之一存在时，`scripts/monitor.py` 就可以调用 TMDB 热门接口。

通常你只需要：

- `TMDB_API_KEY`

`TMDB_BEARER_TOKEN` 是 TMDB v4 的 Bearer Token。它是另一种认证方式，不是必需项。如果你现在只有普通 API Key，可以完全不填。

## 配置文件

脚本会尝试读取 skill 根目录下的 `config.toml`。

建议做法：

1. 复制 `references/config.example.toml`
2. 重命名为根目录下的 `config.toml`
3. 按需修改阈值、观察期、候选源地址和请求页数

## 当前 PtGen 行为

- 静态导出地址
  `https://ourbits.github.io/PtGen/<site>/<sid>.json`
- 回退 API 地址
  `https://api.ourhelp.club/infogen?site=<site>&sid=<sid>`
- 当前支持
  `site=douban` 和 `site=imdb`
- 解析策略
  由于 payload 结构可能不统一，所以目前采用“结构化字段优先，文本兜底匹配补充”的方式
