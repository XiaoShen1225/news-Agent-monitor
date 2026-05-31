# News Agent Monitor —— 多 Agent 新闻监控与可视化系统

基于多 Agent 协同的网站内容监控系统。定时抓取多个新闻网站，检测内容变更，结构化提取新闻条目，LLM 情感分析 + 自动摘要，混合搜索引擎（BM25 + 向量 + RRF 融合），生成可视化图表，支持 Web 仪表盘实时查看。

## 功能特性

- **多源监控**：新闻站点（百度、新浪）+ AI 论文 RSS 源（DeepMind / OpenAI / Google AI）
- **浏览器渲染**：Playwright 无头 Chromium 渲染 JS 页面 + 渐进式滚动触发懒加载
- **四种提取策略**：section_walk / css_selector / LLM 智能过滤 / RSS/Atom XML 解析
- **导航切换**：新闻监控 + 论文追踪双页面，论文页不含复杂数据分析
- **异步管道**：httpx.AsyncClient + Playwright async API + AsyncOpenAI，多站点 asyncio.gather 并发
- **变更分析**：SHA256 内容哈希快速跳过无变化页面；标题级 Diff 识别新增/移除/修改
- **AI 更新摘要**：LLM 自动生成每次更新的中文摘要，突出新增内容和变化趋势
- **智能告警**：关键词自动匹配推送通知、Z-score 异常检测（量级突增/骤降）、中文情感偏移检测，冷却去重
- **多 Provider LLM 抽象**：可插拔 LLM 提供商（智谱/OpenAI/Claude/本地模型），改配置一键切换，Claude 工具格式自动转换
- **深度内容分析**：跨站点事件聚合（向量聚类 + LLM 命名）、命名实体识别（PER/ORG/LOC/PROD/EVENT）、事件时间线构建
- **故事追踪**：用户添加追踪 → 自动匹配后续报道 → 通知推送；完整生命周期管理（活跃/休眠/完结自动清理）
- **文章摘要**：点击任意条目可即时获取文章内容摘要
- **向量语义搜索**：ChromaDB + text2vec-base-chinese 本地嵌入，`/api/search` 端点
- **混合搜索引擎**：jieba 分词 + BM25 倒排索引 + 向量语义 + RRF 融合排序，统一 `search_news` 工具 + `/api/search/hybrid` 端点
- **Web 仪表盘**：FastAPI + ECharts 5.5 实时交互图表 + 暗色主题 + 毛玻璃效果，WebSocket 实时推送
- **分页加载**：News Items 支持分页浏览（30 条/页），避免一次性加载全部数据
- **仪表盘操作**：Refresh All（一键刷新全部）、Run Now（手动触发抓取）、Reset（重置站点历史）集成到前端
- **AI 对话助手**：基于 Tool Calling 的智能助手，多 Session 隔离（独立上下文/偏好），配置外置（config.yaml 可控），结构化 System Prompt（身份/工具策略/拒绝规则/输出格式），思考过程实时可见（ReAct 风格）
- **上下文管理**：Token 预算滑动窗口 + Exchange 边界裁剪，参考 ChatGPT/Claude 的混合策略；主动压缩旧对话摘要，工具结果自动清理
- **Webhook 通知**：钉钉 / 企业微信 / 邮件（SMTP），管道完成后自动推送
- **自动可视化**：matplotlib 生成 10 种 PNG 图表，6 组时间轮替留存
- **新闻/论文分离存储**：新闻与论文使用独立 SQLite 数据库 + JSON 快照目录 + CSV 文件，自动清理旧快照
- **元数据预聚合**：site_metadata 表存储预计算的标签分布、历史计数、变更摘要，仪表盘查询 O(1) 无需扫描全量快照
- **Docker 部署**：一键 `docker compose up -d`，含中文字体 + Chromium
- **自进化**：运行指标追踪 + 调度频率自适应（持久化，重启不丢失）+ 提示词调优
- **每日简报**：定时自动生成 LLM 新闻摘要并推送通知（钉钉/企微/邮件），支持手动触发
- **变更检测优化**：SHA256 内容哈希跳过无变化页面；difflib 模糊标题匹配识别截断/标点差异，减少虚假增删
- **相似度去重**：近重复标题（>70% 相似度）自动过滤，避免同一新闻不同来源的冗余数据
- **断路器**：连续 5 次失败自动熔断 1 小时，避免对不可达站点的无效重试，节省 LLM Token
- **结构化日志**：Pipeline 级别 trace_id + JSON 事件日志（pipeline_start/skip/done/error），支持根因分析
- **健康检查**：`/api/health` 端点，返回服务状态、scheduler 运行状态、最后一次 pipeline 执行时间
- **Windows 兼容**：信号处理兼容 Windows 平台，schedule 模式可正常 Ctrl+C 退出
- **232 个测试**：pytest + pre-commit + ruff lint + GitHub Actions CI
- **成本追踪**：Token 用量按站点聚合入库，`/api/cost` 端点查询，支持按天数筛选
- **LLM 输出评估**：离线评估工具 `eval/judge.py`，faithfulness/relevance 双维度评分
- **流式输出**：Chat 助手 SSE 流式输出，逐字显示回复，工具调用过程实时可见
- **仪表盘鉴权**：可选的 Token 鉴权（环境变量 `DASHBOARD_TOKEN`），未配置则跳过
- **正文缓存**：文章 LLM 摘要自动缓存到 `news_items.summary`，重复请求即时返回
- **跨站点去重**：两轮去重（同站 0.7 + 跨站 0.85），过滤多源重复新闻
- **日志轮转**：`logs/app.log` 文件日志 + 轮转（5MB × 3），排查问题更方便
- **Agent 思考可见**：Chat 助手 ReAct 式思考过程展示——工具调用前显示思考卡片，步骤标签 + 完成标记 + Token 用量进度条
- **安全护栏**：输入校验（越权拦截 + Prompt 注入防护）+ 工具参数校验（URL 格式/站点名合法性），结构化错误分类
- **结构化工具输出**：查询结果带前缀标记（[查询结果]/[站点统计]等），空结果附操作建议
- **用户偏好学习**：时间衰减信号 + 双反馈（隐式行为采集 + 显式喜欢/不喜欢纠正）+ 置信度评分 + 偏好排序增强
- **分析型工具**：站点对比（`compare_sites`）、热点趋势总结（`summarize_trends`）、关键词告警（`set_alert`），Chat 助手支持 8 种工具
- **现代化 UI**：渐变色标题、毛玻璃顶栏、卡片悬浮阴影、自定义滚动条、页面切换动画、气泡式聊天界面

## 快速开始

### 1. 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 2. 安装

```bash
git clone https://github.com/XiaoShen1225/news-Agent-monitor.git
cd news-Agent-monitor

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright Chromium
playwright install chromium
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，填入智谱 AI API Key（https://open.bigmodel.cn/ 免费注册）
```

`config.yaml` 支持多 LLM 提供商切换（`llm.provider: zhipu/openai/claude/local`）。默认使用智谱 AI，API Key 通过 `${ZHIPU_API_KEY}` 环境变量注入。可按需调整目标站点、调度间隔和告警阈值。

### 4. 运行

```bash
# 单次抓取
python main.py --once --url https://news.baidu.com --name baidu_news

# 定时调度（后台持续监控所有 targets）
python main.py --schedule

# Web 仪表盘 + 后台调度
python main.py --serve --port 8080
# 浏览器打开 http://localhost:8080

# 查看统计
python main.py --stats --name baidu_news

# 查询数据库
python main.py --query --name baidu_news --tag 科技 --limit 10

# 重置站点历史
python main.py --reset --name baidu_news
```

### 5. Docker 部署

```bash
docker compose up -d
# 仪表盘: http://localhost:8080
```

## 项目结构

```
Visualization/
├── main.py                        # CLI 入口: --once / --schedule / --serve / --stats / --query / --reset
├── config.yaml                    # 配置文件（LLM、目标站点、调度、通知、情感分析）
├── requirements.txt               # Python 依赖
├── Dockerfile                     # Docker 镜像（含中文字体 + Chromium）
├── docker-compose.yml             # 一键部署
├── .env.example                   # 环境变量模板
├── .pre-commit-config.yaml        # pre-commit 配置
├── .github/workflows/ci.yml       # GitHub Actions CI（3.10/3.11/3.12 矩阵 + lint）
├── agents/
│   ├── base_agent.py              # Agent 基类（Provider 抽象、重试、JSON 容错解析）
│   ├── llm_provider.py            # LLM Provider 抽象接口 + ChatResult/StreamEvent
│   ├── provider_factory.py        # Provider 工厂（zhipu/openai/claude/local）
│   ├── providers/
│   │   ├── zhipu_provider.py      # 智谱 AI (glm-4-flash)
│   │   ├── openai_provider.py     # OpenAI (GPT-4o 等)
│   │   ├── claude_provider.py     # Anthropic Claude (工具格式自动转换)
│   │   └── local_provider.py      # ollama/vLLM 等本地模型
│   ├── fetcher.py                 # 网站抓取（httpx + Playwright）+ SHA256 变更检测
│   ├── parser.py                  # section_walk / css_selector / LLM / RSS 四种提取策略
│   ├── analyzer.py                # 标题 Diff + 趋势计算 + 异常检测 + 情感偏移 + LLM 摘要
│   ├── sentiment_analyzer.py      # 规则中文情感分析（~200 词词典，无 LLM 依赖）
│   ├── visualizer.py              # matplotlib 10 种图表 + 六组留存策略
│   ├── coordinator.py             # 流水线编排，集成告警匹配 + 通知 + 向量存储
│   ├── chat_agent.py              # AI 对话助手（多 Session 隔离 + 结构化 Prompt + Tool Calling + ReAct 思考 + 偏好学习 + Guardrails）
│   ├── deep_analyzer.py           # 深度分析：跨站事件聚合 + 实体识别 + 时间线构建
│   ├── clustering.py              # 余弦相似度聚类（Union-Find + VectorStore Embedding）
│   └── site_profiles.py           # SiteProfile 数据类 + 内置站点配置
├── data/
│   ├── store.py                   # JSON + SQLite + CSV 存储（新闻/论文分离路径）
│   ├── alert_store.py             # 统一告警存储（关键词 CRUD + 冷却/去重 + 匹配）
│   ├── vector_store.py            # ChromaDB 向量存储 + 语义搜索
│   ├── hybrid_search.py           # BM25 + 向量 + RRF 混合搜索引擎
│   ├── history/                   # 新闻历史快照 JSON
│   ├── papers_history/            # 论文历史快照 JSON
│   ├── monitor.db                 # 新闻 SQLite 数据库
│   ├── papers.db                  # 论文 SQLite 数据库
│   └── vector_db/                 # ChromaDB 持久化数据
├── web/
│   ├── app.py                     # FastAPI 应用（REST API + WebSocket）
│   └── templates/
│       └── dashboard.html         # 暗色主题仪表盘 HTML
├── notifications/
│   ├── base.py                    # 通知基类 + PipelineEvent
│   ├── dispatcher.py              # 通知分发器
│   ├── dingtalk.py                # 钉钉群机器人
│   ├── wecom.py                   # 企业微信群机器人
│   └── email.py                   # SMTP 邮件通知
├── evolution/
│   ├── memory.py                  # 运行指标记录
│   └── optimizer.py               # 自进化：Prompt 调优 + 调度频率自适应
├── tests/                         # 232 个测试
│   ├── test_base_agent.py         # LLM JSON 解析容错测试
│   ├── test_llm_provider.py       # Provider 工厂 + 工具转换测试
│   ├── test_fetcher.py            # HTML 清洗 + 哈希测试
│   ├── test_parser.py             # 过滤 + 章节匹配 + DOM 提取 + Profile 测试
│   ├── test_analyzer.py           # Diff + 标签分布 + 趋势测试
│   ├── test_sentiment.py          # 中文情感分类测试
│   ├── test_data_store.py         # 快照 CRUD + 查询 + 运行日志
│   ├── test_alert_store.py        # 告警 CRUD + 冷却 + 匹配测试
│   ├── test_deep_analyzer.py      # 深度分析 + 事件聚类 + 实体提取 + 时间线
│   ├── test_clustering.py         # 余弦相似度 + Union-Find 聚类
│   ├── test_evolution.py          # 调度 + 提示词调优测试
│   ├── test_chat_agent.py         # ChatAgent 上下文管理 + Token 估算测试
│   ├── test_notifications.py      # 通知创建 + 事件构建测试
│   └── test_eval.py               # LLM 输出评估评分解析测试
├── outputs/
│   ├── charts/                    # 生成的 PNG 图表（6 组目录）
│   │   ├── today/                 # 今日最新
│   │   ├── yesterday/             # 昨日快照
│   │   ├── two_days_ago/          # 前天快照
│   │   ├── one_week_ago/          # 一周前快照
│   │   ├── one_month_ago/         # 一月前快照
│   │   └── total/                 # 累计历史趋势
│   └── data/
│       ├── news_items.csv         # 新闻条目 CSV
│       └── papers.csv             # 论文条目 CSV
└── report.md                      # 课程报告
```

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       Coordinator Agent                          │
│       (编排流水线, 管理调度, 触发通知 + 向量存储 + 深度分析)        │
└──┬──────┬──────────┬──────────────┬──────────────┬───────────────┘
   │      │          │              │              │
   ▼      ▼          ▼              ▼              ▼
┌────────┐ ┌──────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐
│Fetcher │ │Parser│ │ Analyzer │ │Visualizer  │ │ Notifications│
│Agent   │ │Agent │ │ Agent    │ │Agent       │ │              │
├────────┤ ├──────┤ ├──────────┤ ├────────────┤ │ DingTalk     │
│Playwr. │ │DOM树 │ │ 标题Diff  │ │ 分类饼图    │ │ WeCom        │
│httpx   │ │章节  │ │ 趋势分析  │ │ 趋势折线    │ │ Email        │
│SHA256  │ │关键词│ │ 情感分析  │ │ 变更柱状    │ │              │
│变更检测 │ │CSS选 │ │ LLM摘要  │ │ 摘要表+仪表 │ │              │
└────────┘ └──────┘ └──────────┘ └────────────┘ └──────────────┘
   │          │          │              │
   └──────────┴──────────┴──────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│    Data Store    │   │   Vector Store   │   │   Alert Store    │
│ JSON+SQLite+CSV  │   │   ChromaDB       │   │ 关键词 + 冷却     │
│ events+entities  │   │ text2vec-chinese │   │ 异常 + 情感偏移   │
└──────────────────┘   └──────────────────┘   └──────────────────┘
          │                       │
          └───────────┬───────────┘
                      ▼
          ┌──────────────────────┐
          │  Deep Analyzer       │
          │ 跨站事件聚合 + 聚类   │
          │ 实体识别 + 时间线     │
          └──────────────────────┘
                      │
                      ▼
          ┌──────────────────────┐
          │    Web Dashboard     │
          │ FastAPI + WebSocket  │
          │ /api/events 事件列表 │
          │ /api/entities 实体榜 │
          │ /api/search 语义搜索 │
          │ /api/chat 对话助手   │
          └──────────────────────┘
```

## Agent 协作流程

1. **Coordinator** 接收任务（手动 `--once` 或 APScheduler 定时触发）
2. **Fetcher** Playwright 渲染 + 滚动 → SHA256 哈希
3. **哈希未变** → 跳过，`skipped_no_change`，**零 Token 消耗**
4. **哈希已变** → **Parser** DOM 遍历 + SiteProfile 策略提取 → 标题+URL+分类+发布时间
5. **SentimentAnalyzer** 规则词典快速标注情感（正面/负面/中性）
6. 数据存入 **JSON 快照** + **SQLite** + **CSV**，**Vector Store** 索引
7. **Analyzer** 标题 Diff → 新增/移除/修改 + 趋势方向 + 异常检测（Z-score）+ 情感偏移 + **LLM 摘要**
8. **AlertStore** 关键词匹配 → 冷却检查 → 注入 PipelineEvent
9. **Visualizer** 生成图表，today/total 每次更新
10. **通知** → 钉钉/企微/邮件推送（含告警段落）
11. **DeepAnalyzer** 所有站点完成后 → 跨站事件聚类（Vector Embedding + 余弦相似度）→ LLM 命名 → 实体识别 → 时间线构建
12. **Evolution** 指标记录 → 调度频率自适应
13. **ChatAgent** 通过 Tool Calling 查询数据，上下文窗口自动管理（Token 预算 + Exchange 裁剪）

## API 文档

启动 `--serve` 后访问 `http://localhost:8080/docs` 查看 Swagger 文档。

| 端点 | 说明 |
|------|------|
| `GET /` | 仪表盘 HTML 页面 |
| `GET /api/stats?site=` | 运行统计 + 快照概览 |
| `GET /api/query?site=&tag=&date_from=&date_to=&limit=&offset=` | 新闻条目查询（分页） |
| `GET /api/search?q=&site=&limit=` | 向量语义搜索 |
| `GET /api/search/hybrid?q=&site=&tag=&days=&limit=` | 混合搜索（BM25+向量+RRF） |
| `GET /api/charts` | PNG 图表文件列表 |
| `GET /api/chart-data?site=` | ECharts 实时图表数据 |
| `GET /api/summarize?url=&title=` | 文章内容即时摘要 |
| `GET /api/papers?site=&limit=&offset=` | 论文/文章条目查询 |
| `GET /api/targets` | 已配置的监控目标列表 |
| `GET /api/schedule` | 调度器状态和配置 |
| `POST /api/trigger-run?site=&url=` | 手动触发单次抓取 |
| `POST /api/refresh-all` | 一键刷新全部监控目标 |
| `POST /api/reset?site=` | 重置站点历史数据 |
| `POST /api/chat` | AI 对话助手（支持 Tool Calling） |
| `POST /api/chat/stream` | AI 对话助手 SSE 流式输出（含 thinking/tool_call/tool_result/token/context/done 事件） |
| `POST /api/auth` | 仪表盘 Token 鉴权 |
| `GET /api/chat/history` | 查看对话历史 |
| `GET /api/chat/context` | 上下文使用统计（Token 数、Exchange 数） |
| `GET /api/chat/sessions` | 活跃 Session 列表 |
| `GET /api/health` | 健康检查（状态、运行时长、scheduler 状态、最后执行时间） |
| `GET /api/cost?days=7` | Token 用量统计（按站点聚合，支持天数筛选） |
| `DELETE /api/chat` | 清空对话历史（支持 session_id 参数） |
| `POST /api/report/now` | 手动触发每日简报并推送通知 |
| `GET /api/report/schedule` | 查看简报调度配置 |
| `GET /api/events` | 跨站事件列表（深度分析） |
| `GET /api/events/{event_id}` | 事件详情 + 时间线 |
| `GET /api/entities?type=` | 实体热度榜（可按类型筛选） |
| `GET /api/entities/{entity_name}` | 实体相关新闻条目 |
| `WS /ws` | WebSocket 实时推送 |

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| LLM | 智谱 AI / OpenAI / Claude / 本地（Provider 可插拔，改配置切换） |
| 嵌入模型 | shibing624/text2vec-base-chinese（本地，免费） |
| 浏览器渲染 | Playwright (Chromium headless) |
| HTML 解析 | BeautifulSoup4 + lxml |
| Web 框架 | FastAPI + Jinja2 + WebSocket |
| 向量数据库 | ChromaDB |
| 数据存储 | JSON + SQLite + CSV |
| 可视化 | matplotlib（SimHei 中文字体） |
| 调度 | APScheduler (AsyncIOScheduler) |
| 通知 | 钉钉 / 企业微信 / SMTP 邮件 |
| 测试 | pytest（232 tests）+ ruff + pre-commit |
| CI/CD | GitHub Actions |
| 部署 | Docker + Docker Compose |
