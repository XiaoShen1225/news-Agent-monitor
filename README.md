# 数据可视化课程作业 —— 多 Agent 新闻监控系统

基于多 Agent 协同的网站内容监控与数据可视化系统。定时抓取百度新闻，检测内容变更，提取关键数据，与历史数据整合，自动生成可视化 PNG 图表。支持自进化。

## 功能特性

- **网站监控**：Playwright 无头浏览器渲染 JS 页面 + 滚动触发懒加载，SHA256 哈希快速检测变更
- **结构化提取**：DOM 树遍历 + 章节关键词匹配，无需消耗 LLM Token 即可完成新闻分类
- **变更分析**：以标题为主键对比历史快照，识别新增/移除/修改内容，计算趋势方向
- **自动可视化**：matplotlib 生成 7 种 PNG 图表（饼图、折线、柱状、摘要表、仪表盘、新增条目表、新增分布）
- **图表留存策略**：today / yesterday / two_days_ago / one_week_ago / one_month_ago / total 六组图表自动轮替
- **三层存储**：JSON 快照 + SQLite 条目表（可索引查询）+ CSV 文件（通用分析）
- **多 Agent 协同**：6 个 Agent 分工协作（Fetcher / Parser / Analyzer / Visualizer / Coordinator / Evolution）
- **自进化**：运行指标追踪 + 调度频率自适应 + 提示词调优

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                    Coordinator Agent                          │
│  (编排流水线, 管理调度, 触发自进化)                              │
└──────┬───────┬──────────┬──────────────┬─────────────────────┘
       │       │          │              │
       ▼       ▼          ▼              ▼
┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────────┐
│ Fetcher │ │ Parser  │ │ Analyzer │ │ Visualization    │
│ Agent   │ │ Agent   │ │ Agent    │ │ Agent            │
├─────────┤ ├─────────┤ ├──────────┤ ├──────────────────┤
│Playwright│ │DOM遍历  │ │ 标题Diff  │ │ 分类饼图         │
│ 渲染抓取 │ │章节匹配  │ │ 趋势分析  │ │ 趋势折线         │
│SHA256   │ │关键词分类│ │ 变更报告  │ │ 变更柱状         │
│ 变更检测 │ │零LLM消耗 │ │          │ │ 摘要表+仪表盘     │
└─────────┘ └─────────┘ └──────────┘ │ 新增条目表+分布   │
       │       │          │          └──────────────────┘
       └───────┴──────────┴──────────────┘
                      │
                      ▼
            ┌──────────────────────────┐
            │       Data Store         │
            │ JSON + SQLite + CSV      │
            └──────────────────────────┘
                      │
                      ▼
            ┌──────────────────────────┐
            │   Evolution Optimizer    │
            │ 指标记录 → 策略调优       │
            └──────────────────────────┘
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 2. 安装

```bash
# 克隆或解压项目后
cd Visualization

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（Chromium）
playwright install chromium
```

### 3. 配置

编辑 `config.yaml`，将 API Key 替换为自己的智谱 AI Key（https://open.bigmodel.cn/ 免费注册获取）：

```yaml
llm:
  api_key: "your-zhipu-api-key-here"   # 替换为你的 API Key
  model: "glm-4-flash"

targets:
  - url: "https://news.baidu.com/"
    name: "baidu_news"
    interval_minutes: 60
    use_browser: true                    # 使用 Playwright 渲染 JS 页面
```

### 4. 运行

```bash
# 单次抓取并生成可视化
python main.py --once --name baidu_news

# 定时调度模式（后台持续监控）
python main.py --schedule

# 查看运行统计
python main.py --stats --name baidu_news

# 查询数据库中的条目
python main.py --query --name baidu_news --tag 科技 --limit 10
python main.py --query --name baidu_news --from 2026-05-01 --to 2026-05-16

# 重置历史数据
python main.py --reset --name baidu_news
```

## 项目结构

```
Visualization/
├── main.py                    # CLI 入口: --once / --schedule / --stats / --query / --reset
├── config.yaml                # 配置文件 (LLM Key, 目标URL, 调度间隔)
├── requirements.txt           # Python 依赖
├── prompts/
│   └── extraction.yaml        # LLM 提取提示词模板（可被进化优化器修改）
├── agents/
│   ├── base_agent.py          # Agent 基类（LLM 客户端、重试、JSON 解析容错）
│   ├── fetcher.py             # 网站抓取（httpx + Playwright）+ SHA256 变更检测
│   ├── parser.py              # DOM 遍历 + 章节关键词匹配 + 新闻链接提取
│   ├── analyzer.py            # 标题级 Diff + 趋势方向计算
│   ├── visualizer.py          # matplotlib 图表生成 + 六组图表留存策略
│   └── coordinator.py         # 流水线编排（Fetcher→Parser→Analyzer→Visualizer）
├── data/
│   ├── store.py               # 数据持久化（JSON + SQLite + CSV 三层存储）
│   └── monitor.db             # SQLite 数据库（自动生成）
├── evolution/
│   ├── memory.py              # 运行指标记录
│   └── optimizer.py           # 自进化：Prompt 调优 + 调度频率自适应
├── data/history/              # 历史快照 JSON 文件
├── outputs/
│   ├── charts/                # 生成的 PNG 图表（6 组目录）
│   │   ├── today/             # 今日最新（每次运行更新）
│   │   ├── yesterday/         # 昨日快照
│   │   ├── two_days_ago/      # 前天快照
│   │   ├── one_week_ago/      # 一周前快照（仅周日更新）
│   │   ├── one_month_ago/     # 一月前快照（仅月末更新）
│   │   └── total/             # 累计历史趋势（每次运行更新）
│   └── data/
│       └── news_items.csv     # 所有条目统一 CSV（每次运行追加）
└── report.md                  # 课程报告
```

## Agent 协作流程

1. **Coordinator** 接收任务（手动 `--once` 或 APScheduler 定时触发）
2. **Fetcher** 用 Playwright 渲染页面 + 滚动触发懒加载 → 计算 SHA256
3. **哈希未变** → 跳过后续步骤，日志记录 `skipped_no_change`，**零 Token 消耗**
4. **哈希已变** → **Parser** 遍历 DOM 树，匹配章节关键词（国内/国际/科技等），提取 `<a>` 标签中的标题+URL+分类
5. 数据同时存入 **JSON 快照** + **SQLite 条目表** + **CSV 文件**
6. **Analyzer** 加载上一次快照，以标题为主键做 Diff → new_items / removed_items / modified_items
7. **Visualizer** 根据报告生成图表，today/total 每次更新，其他按策略更新
8. **Evolution** 记录运行指标 → 无变化时降低轮询频率（省资源），频繁变化时提高频率

## 生成的图表

| 图表 | 文件名 | 说明 |
|------|--------|------|
| 分类饼图 | `chart_tag_pie.png` | 全部新闻的分类分布 |
| 新增分布饼图 | `new_items_distribution_tag_pie.png` | 仅新增条目的分类分布 |
| 趋势折线图 | `chart_trend_line.png` | 新闻数量随时间变化 |
| 变更柱状图 | `chart_change_bar.png` | 新增/移除/修改数量对比 |
| 新闻摘要表 | `chart_summary_table.png` | 最新 15 条（新增条目绿色高亮 + "NEW \|" 前缀） |
| 新增条目表 | `chart_new_items.png` | 仅新增条目（标题+Tag+原文URL，最多30条） |
| 综合仪表盘 | `chart_overview.png` | 统计信息 + 分类饼图 + 新增/移除列表 |
| 历史趋势 | `total_historical_trend.png` | 全部历史快照的新闻数量变化 |
| 标签演变 | `total_tag_evolution.png` | 分类占比随时间的堆叠面积图 |
| 累计概览 | `total_cumulative_overview.png` | 历史统计 + 累计标签分布 |

## 自进化机制

- **运行记忆**：每次运行记录置信度、变化量、处理时间到 JSON
- **调度调优**：连续 3 次无变化 → 间隔翻倍（省浏览器资源）；频繁变化 → 间隔缩短（及时捕获）
- **提示词进化**：当 LLM 提取置信度 < 0.5，自动向 prompt 追加格式强化指令

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| LLM | 智谱 AI glm-4-flash（免费额度，OpenAI 兼容接口） |
| 浏览器渲染 | Playwright (Chromium headless) |
| HTML 解析 | BeautifulSoup4 + lxml |
| 数据存储 | JSON + SQLite + CSV |
| 可视化 | matplotlib（SimHei 中文字体） |
| 调度 | APScheduler |
| HTTP | httpx |
