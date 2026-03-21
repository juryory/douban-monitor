# OpenClaw 豆瓣高分监控 Skill

这个项目是一个运行在 OpenClaw 环境中的豆瓣高分影视监控 skill，用来发现豆瓣里“近期新出现并达到门槛”的电影、剧集、综艺等内容。

默认规则：

- 豆瓣评分大于 `8.0`
- 豆瓣评分人数大于 `3000`

## 工作方式

这个 skill 采用双层抓取策略：

- 豆瓣榜单页
  使用 Playwright 浏览器抓取候选
- 豆瓣详情页
  优先使用 HTML 解析提取标题、评分、评分人数和年份
- TMDB
  作为候选补充和展示元数据来源

默认会抓取这些豆瓣榜单：

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
  密钥示例
- `requirements.txt`
  Python 依赖
- `scripts/monitor.py`
  主执行脚本
- `references/`
  示例配置、状态文件和实现说明

## 运行依赖

### Python 依赖

- `playwright`

安装方式：

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 浏览器依赖

完整模式要求宿主环境至少满足以下之一：

1. 已安装 Playwright 自带 Chromium
2. 已安装系统浏览器，并在 `config.toml` 中通过 `browser_executable_path` 指定

### Linux 容器依赖

如果这个 skill 运行在 Linux 容器中的 OpenClaw 环境里，并且要启用浏览器抓取，那么容器中通常还需要安装 Playwright 所依赖的系统库，例如：

```bash
apt-get update && apt-get install -y libnspr4 libnss3 libatk1.0-0 libdbus-1-3 libcups2 libxkbcommon0 libatspi2.0-0 libgbm1 libasound2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2
```

## 配置建议

- `SKILL.md`
  放监控规则、默认行为、入库和退库逻辑
- `.env`
  只放密钥或敏感环境变量，例如 `TMDB_API_KEY`
- `config.toml`
  放非敏感运行参数，例如阈值、观察期、多榜单候选源地址、请求页数和浏览器参数

## 运行方式

建议使用绝对路径运行：

```bash
python3 /home/node/.openclaw/skills/douban-monitor/scripts/monitor.py
```

运行后会输出阶段日志，并写入：

- `data/douban-monitor-state.json`
- `data/douban-monitor-library.json`
- `reports/douban-monitor-YYYYMMDD.md`
