# OpenClaw 豆瓣高分监控 Skill

这个目录包含一套面向 OpenClaw 的豆瓣高分影视监控 skill 草案，用来发现“新出现并达到目标门槛”的电影、剧集、综艺等内容。

## 目录结构

- `SKILL.md`
  skill 主说明，定义目标、规则、数据流和监控策略
- `scripts/monitor.py`
  Python 版执行入口，负责候选采集、状态更新和报告生成
- `references/state.example.json`
  提醒状态文件示例
- `references/library.example.json`
  监控库文件示例
- `references/config.example.toml`
  非敏感运行参数示例
- `references/IMPLEMENTATION_NOTES.md`
  实现说明和后续接线建议
- `.env.example`
  TMDB 密钥示例

## 推荐候选源

- 豆瓣移动端周榜页
  例如 `https://m.douban.com/subject_collection/movie_weekly_best`
- TMDB 的电影和剧集热门接口

## 推荐每日流程

1. 拉取豆瓣周榜和 TMDB 热门内容，合并成候选池。
2. 尽可能把候选映射到 `douban_id`。
3. 将候选写入本地监控库。
4. 用豆瓣侧评分和评分人数做最终判定。
5. 产出“新增命中”“值得二次关注”“继续观察”三类结果。

## 建议后续工作

1. 接入真实的豆瓣候选抓取逻辑。
2. 接入 TMDB 热门接口作为补充候选源。
3. 确认项目实际使用的状态文件和监控库路径。
4. 继续完善执行脚本，使其能直接产出日报。

## 配置建议

- `SKILL.md`
  放监控规则、默认行为、入库和退库逻辑
- `.env`
  只放密钥或敏感环境变量，例如 `TMDB_API_KEY`
- `references/config.example.toml`
  放非敏感运行参数，例如阈值、观察期、候选源地址、请求页数

脚本约定：

- `scripts/monitor.py` 会优先读取 skill 根目录下的 `config.toml`
- 如果没有这个文件，就回退到脚本内置默认值
