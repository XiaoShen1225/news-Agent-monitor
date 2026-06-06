"""get_timeline tool — time-ordered news items."""

from langchain_core.tools import tool


def make_get_timeline_tool(news_store, paper_store):
    @tool
    async def get_timeline(
        days: int = 7,
        site_name: str = "",
        sentiment: str = "",
        limit: int = 15,
    ) -> str:
        """获取按时间排序的新闻条目列表，用于了解最近动态时间线。

        使用场景：用户问"最近发生了什么""时间线""这几天有什么新消息"时使用。
        可用 list_tags 了解标签分布、get_events 了解聚集事件作为补充。
        sentiment可筛选情感（positive/negative/neutral），不传则返回全部。
        """
        days = min(max(days, 1), 30)
        limit = min(max(limit, 1), 30)
        sentiment_val = sentiment or None

        items = []
        if site_name:
            from agents.site_profiles import is_article_site

            store = paper_store if is_article_site(site_name) else news_store
            if store:
                items = store.query_items(
                    site_name=site_name, sentiment=sentiment_val, limit=limit
                )
        else:
            for store in (news_store, paper_store):
                if store:
                    try:
                        store_items = store.query_items(
                            sentiment=sentiment_val, limit=limit
                        )
                        items.extend(store_items or [])
                    except Exception:
                        pass

        if not items:
            label = f"站点 {site_name}" if site_name else "全部站点"
            return f"[时间线] {label}暂无数据。"

        # Sort by time descending
        items.sort(
            key=lambda x: x.get("snapshot_time") or x.get("published") or "",
            reverse=True,
        )

        label = f"站点: {site_name}" if site_name else "全部站点"
        lines = [f"[时间线] 最近 {days} 天 ({label})，共 {len(items)} 条:"]
        for it in items[:limit]:
            t = (it.get("published") or it.get("snapshot_time", ""))[:10]
            lines.append(
                f"- [{it.get('site_name', '?')}][{it.get('tag', '无标签')}] "
                f"{it.get('title', '无标题')[:60]} ({t})"
            )
        return "\n".join(lines)

    return get_timeline
