"""search tool — BM25 + vector hybrid search."""

from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool


def make_search_tool(hybrid_searcher, vector_store, news_store, paper_store):
    @tool
    async def search(
        query: str,
        site_name: str = "",
        tag: str = "",
        days: int = 0,
        limit: int = 15,
    ) -> str:
        """语义搜索新闻/论文数据库（BM25关键词 + 向量语义混合检索 + RRF融合排序）。

        使用场景：用户查新闻/找文章时使用，是所有搜索类意图的唯一入口。
        query为必填；site_name限定站点（baidu_news/sina_news/deepmind_blog/openai_blog）；
        tag标签筛选；days回溯天数（0=今天）；limit返回数量，默认15。
        """
        if not query.strip():
            return "[参数错误] 请提供搜索关键词（query 参数）。"

        site = site_name or None
        tag_val = tag or None
        limit = min(max(limit, 1), 30)

        date_from = None
        if days is not None and days > 0:
            date_from = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # Hybrid search
        if hybrid_searcher:
            items = hybrid_searcher.search(
                query=query.strip(),
                site_name=site,
                tag=tag_val,
                date_from=date_from,
                limit=max(limit, 50),
            )
        elif vector_store:
            results = vector_store.search(
                query.strip(), site_name=site, limit=max(limit, 50)
            )
            items = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "site_name": r.get("site_name", ""),
                    "tag": r.get("tag", ""),
                    "snapshot_time": r.get("snapshot_time", ""),
                    "published": r.get("snapshot_time", ""),
                }
                for r in results
            ]
        else:
            store = (
                paper_store if site in ("deepmind_blog", "openai_blog") else news_store
            )
            if store is None:
                store = news_store
            items = store.query_items(
                site_name=site,
                tag=tag_val,
                keyword=query.strip(),
                date_from=date_from,
                limit=limit,
            )

        if not items:
            return (
                f"[混合搜索] 未找到与「{query}」相关的内容。\n"
                "建议尝试：1) 使用更简短的关键词 2) 不限定站点或标签 3) 扩大时间范围"
            )

        method = "BM25+语义融合" if hybrid_searcher else "关键词"
        lines = [f"[搜索] 查询：「{query}」（{method}），共找到 {len(items)} 条："]
        for it in items[:limit]:
            t = (it.get("published") or it.get("snapshot_time", ""))[:10]
            score = it.get("fusion_score")
            extras = ""
            if score is not None:
                sources = "+".join(it.get("sources", ["?"]))
                extras = f" [相关度: {score:.2f}, {sources}]"
            lines.append(
                f"- [{it.get('tag', '无标签')}] {it.get('title', '无标题')[:60]}"
                f" ({t}){extras}"
            )
        return "\n".join(lines)

    return search
