# 数据可视化课程报告 —— 多 Agent 新闻监控与可视化系统

## 一、项目概述

本项目实现了一个基于多 Agent 协同的新闻网站内容监控与数据可视化系统。系统以百度新闻（news.baidu.com）为目标网站，定时抓取页面内容，检测内容变更，提取新闻标题、原文链接和分类标签，与历史数据整合，自动生成可视化 PNG 图表。

### 核心指标

| 指标 | 数值 |
|------|------|
| Agent 数量 | 6 个（Fetcher / Parser / Analyzer / Visualizer / Coordinator / Evolution） |
| 单次抓取新闻数 | ~241 条 |
| 分类准确率 | 11 个章节正确分类（科技、财经、军事、国内、国际、娱乐、体育、要闻、探索、图片、本地） |
| LLM Token 消耗 | 0（纯 DOM 遍历 + 关键词分类，无需 LLM 参与解析） |
| 存储方式 | JSON + SQLite + CSV 三层 |
| 图表类型 | 10 种 PNG 图表 |

---

## 二、系统架构

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

---

## 三、Agent 详细设计

### 3.1 FetcherAgent（抓取 Agent）

**职责**：获取目标网页 HTML，计算内容哈希，实现快速变更检测。

**技术方案**：
- **静态抓取**：httpx 发送 HTTP 请求，模拟 Chrome 浏览器 User-Agent
- **动态渲染**：Playwright 无头 Chromium，执行 JavaScript 渲染，滚动触发懒加载
- **反检测**：`--disable-blink-features=AutomationControlled`，隐藏 `navigator.webdriver`
- **滚动策略**：6 步渐进滚动 + 底部全量滚动 + 回滚 + 再次滚动到底部，触发所有懒加载区块
- **效果**：HTML 从 79KB → 133KB，提取条目从 54 → 170 → 243

**变更检测**：
```python
# 剥离 script/style/noscript 标签 + 空白 → SHA256
text = SCRIPT_STYLE_PATTERN.sub(" ", html)
clean = WHITESPACE_PATTERN.sub(" ", text).strip()
content_hash = sha256(clean.encode()).hexdigest()
```

哈希相同时 Coordinator 直接跳过下游 Agent，零 Token 消耗。

### 3.2 ParserAgent（解析 Agent）

**职责**：从 HTML 中提取新闻标题、原文链接和分类标签。

**核心设计决策 —— 为什么不用 LLM？**
百度新闻本身就是按板块（国内/国际/科技/娱乐等）组织的，页面 DOM 结构中已包含分类信息。用 LLM 提取分类反而引入了延迟、成本和不确定性。我们选择了纯结构化的 DOM 遍历方案。

**实现方案**：
1. **DOM 树遍历**：按文档顺序遍历 `soup.descendants`
2. **章节追踪**：维护 `current_tag` 变量，遇到章节标记（导航标签、h3 标题）时更新
3. **链接提取**：遍历中遇到 `<a>` 标签即提取 title + href + current_tag
4. **更长匹配优先**：章节关键词匹配时，长关键词（如"探索" 3字）优先于短关键词（如"图片" 2字）
5. **中文提取**：对于 "国内China" 这类中英混合标题，自动提取中文部分匹配
6. **新闻链接保护**：`<a>` 标签中的文本若本身是合法新闻标题，不会被视为章节标记

**过滤机制**：
- 标题长度：6-200 字符
- 噪声模式：加载中/百度/ICP备案/版权声明等 20+ 条正则
- UI 标签黑名单：首页/登录/注册/更多等 15+ 个精确匹配
- 章节模式：纯英文、1-3 字超短文本

**章节关键词映射**（部分）：
```
热点→要闻, 北京→本地, 国内→国内, 国际→国际, 军事→军事,
财经→财经, 娱乐→娱乐, 体育→体育, 科技→科技, 互联网→科技,
游戏→游戏, 女人→女性, 汽车→汽车, 房产→房产, 探索→探索,
明星→娱乐, NBA→体育, 中国军情→军事
```

### 3.3 AnalyzerAgent（分析 Agent）

**职责**：对比当前快照与上一次快照，检测变更，计算趋势。

**差异算法**：以标题为主键做集合对比
```python
prev_titles = {item["title"] for item in previous}
curr_titles = {item["title"] for item in current}

new_items     = curr_titles - prev_titles      # 新增
removed_items = prev_titles - curr_titles      # 移除
modified_items = {t for t in curr_titles & prev_titles
                  if tag_changed(t) or summary_changed(t)}  # 修改
```

**趋势计算**：最近 3 次快照平均数量 vs 更早快照平均数量
- `recent_avg > older_avg * 1.1` → 上升趋势
- `recent_avg < older_avg * 0.9` → 下降趋势
- 其他 → 稳定

### 3.4 VisualizationAgent（可视化 Agent）

**职责**：根据分析报告和历史快照生成 PNG 图表。

**图表类型**（共 10 种）：
1. `chart_tag_pie.png` — 全部分类饼图
2. `new_items_distribution_tag_pie.png` — 新增条目分类饼图
3. `chart_trend_line.png` — 新闻数量趋势折线
4. `chart_change_bar.png` — 新增/移除/修改柱状图
5. `chart_summary_table.png` — 最新 15 条摘要表（新增条目绿色高亮）
6. `chart_new_items.png` — 新增条目详情表（标题+Tag+原文URL，最多30条）
7. `chart_overview.png` — 综合仪表盘（统计+分类+新增/移除列表）
8. `total_historical_trend.png` — 历史趋势图（含移动平均线）
9. `total_tag_evolution.png` — 分类占比随时间变化的堆叠面积图
10. `total_cumulative_overview.png` — 累计统计概览

**图表留存策略**（6 组目录）：

| 目录 | 更新时机 | 内容 |
|------|---------|------|
| `today/` | 每次运行 | 最新快照的完整图表集 |
| `yesterday/` | 每次运行（有昨日数据时） | 截至昨天的历史图表 |
| `two_days_ago/` | 每次运行（有前天数据时） | 截至前天的历史图表 |
| `one_week_ago/` | 仅周日 | 截至 7 天前的历史图表 |
| `one_month_ago/` | 仅月末 | 截至 30 天前的历史图表 |
| `total/` | 每次运行 | 全部历史的累计趋势图表 |

**中文支持**：自动检测系统可用中文字体（SimHei → Microsoft YaHei → WenQuanYi → Noto Sans CJK → Arial Unicode MS）。

### 3.5 CoordinatorAgent（协调 Agent）

**职责**：编排流水线，连接 DataStore 和 Evolution。

**两种运行模式**：
- `--once`：手动单次运行，输出结果摘要
- `--schedule`：APScheduler 定时调度，先执行初始抓取再进入周期

**流水线逻辑**：
```
Fetcher → Hash Check → (changed?) → Parser → DataStore.save → Analyzer → Visualizer → Evolution.record
                           ↓ (unchanged)
                      log "skipped" + return
```

### 3.6 Evolution（自进化）

**记忆系统**（`evolution/memory.py`）：
- 每次运行记录：时间戳、站点、状态、提取条目数、变更数、置信度、处理耗时
- 持久化到 `evolution/memory.json`

**优化器**（`evolution/optimizer.py`）：
- **调度调优**：连续 3 次无变化 → 轮询间隔翻倍（节能）；频繁变化 → 间隔缩短（及时捕获）
- **提示词进化**：当 LLM 提取置信度 < 0.5，自动在 prompt 中追加格式强化指令

---

## 四、数据存储

三层存储方案，各司其职：

| 层级 | 格式 | 用途 |
|------|------|------|
| JSON 快照 | `data/history/*.json` | 完整历史记录，可回溯任意时间点 |
| SQLite 数据库 | `data/monitor.db` | 结构化查询，按标签/时间/站点过滤 |
| CSV 文件 | `outputs/data/news_items.csv` | 通用数据分析（Excel / Pandas 直接读取） |

**SQLite `news_items` 表结构**：
```sql
CREATE TABLE news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    site_name TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    tag TEXT DEFAULT '',
    snapshot_time TIMESTAMP NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);
CREATE INDEX idx_news_items_site_time ON news_items(site_name, snapshot_time);
CREATE INDEX idx_news_items_tag ON news_items(site_name, tag);
```

---

## 五、CLI 命令速查

```bash
# 单次抓取
python main.py --once --name baidu_news

# 定时调度
python main.py --schedule

# 查看统计
python main.py --stats --name baidu_news

# 查询条目（按标签）
python main.py --query --name baidu_news --tag 科技 --limit 20

# 查询条目（按日期范围）
python main.py --query --name baidu_news --from 2026-05-01 --to 2026-05-16

# 重置数据
python main.py --reset --name baidu_news
```

---

## 六、实验数据

### 单次抓取效果

抓取百度新闻首页，Playwright 渲染 + 滚动触发懒加载后：
- HTML 大小：~133KB
- 提取新闻数：241 条
- 分类数量：11 个
- 处理耗时：~20 秒（含 Playwright 渲染和滚动）

### 分类分布

| 标签 | 数量 | 占比 |
|------|------|------|
| 科技 | 48 | 19.9% |
| 财经 | 27 | 11.2% |
| 军事 | 25 | 10.4% |
| 国内 | 24 | 10.0% |
| 娱乐 | 22 | 9.1% |
| 体育 | 22 | 9.1% |
| 国际 | 22 | 9.1% |
| 要闻 | 17 | 7.1% |
| 探索 | 15 | 6.2% |
| 图片 | 11 | 4.6% |
| 本地 | 8 | 3.3% |

### 变更检测

两次连续运行（间隔 14 分钟），SHA256 哈希不同但提取的标题完全相同 → Analyzer 正确报告 0 new, 0 removed, 0 modified。说明变更检测逻辑正确：哈希对 HTML 敏感（捕获任何变化），Diff 对标题精确（避免误报）。

---

## 七、安装说明

### Windows

```bash
cd Visualization
pip install -r requirements.txt
playwright install chromium
# 编辑 config.yaml，填入智谱 AI API Key
python main.py --once --name baidu_news
```

### macOS / Linux

```bash
cd Visualization
pip install -r requirements.txt
playwright install chromium
# 编辑 config.yaml，填入智谱 AI API Key
python main.py --once --name baidu_news
```

### 注意事项

1. Playwright 首次安装需下载 Chromium（~150MB），确保网络畅通
2. 中文字体：Windows 通常自带 SimHei，Linux 需安装中文字体包
3. 智谱 AI API Key 从 https://open.bigmodel.cn/ 免费注册获取

---

## 八、总结

本系统完整实现了课程作业的全部 4 项要求：

1. **网站查询、变更检测、数据提取、历史整合、自动可视化** — 全流程闭环
2. **Agent 框架 + 免费 Token** — 6 Agent 协同，智谱 AI glm-4-flash 免费额度，Parser 甚至零 Token 消耗
3. **多 Agent 协同 + 自进化** — Coordinator 编排流水线，Evolution 自动调优轮询频率和提示词
4. **PPT 演示** — 
