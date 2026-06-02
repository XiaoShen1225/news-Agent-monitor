"""get_events tool — cross-site event clusters."""

from langchain_core.tools import tool


def make_get_events_tool(news_store, paper_store):
    @tool
    async def get_events(event_id: str = "", limit: int = 10) -> str:
        """获取跨站点事件聚合。系统自动将相似新闻聚类为事件。

        查列表：不传 event_id。用户问"最近有什么大事件""热点话题"时使用。
        查详情：传 event_id。用户追问某个事件的具体报道时使用。
        """
        events = []
        for store in (news_store, paper_store):
            if store is None:
                continue
            try:
                evts = store.get_events(limit=max(limit, 50))
                events.extend(evts or [])
            except Exception:
                pass

        if not events:
            return "[事件聚合] 暂无跨站点事件聚合数据。系统需要新数据来生成事件分析。"

        limit = min(max(limit, 1), 20)

        if event_id:
            for evt in events:
                if evt.get("id") == event_id or str(evt.get("id")) == str(event_id):
                    items = evt.get("items", [])
                    lines = [
                        f"[事件详情] {evt.get('title', '未命名')}",
                        f"描述: {evt.get('description', '无描述')[:200]}",
                        f"站点: {evt.get('source_sites', '未知')}",
                        f"时间: {evt.get('first_seen', '?')} ~ {evt.get('last_seen', '?')}",
                        f"相关报道 ({len(items)} 篇):",
                    ]
                    for it in items[:10]:
                        lines.append(
                            f"  - [{it.get('site_name', '?')}] {it.get('title', '无标题')[:60]}"
                        )
                    return "\n".join(lines)
            return f"[事件聚合] 未找到事件 ID: {event_id}"

        lines = [f"[事件聚合] 最近 {len(events[:limit])} 个跨站点事件:"]
        for evt in events[:limit]:
            lines.append(
                f"\n  ID: {evt.get('id', '?')} | {evt.get('title', '未命名')[:50]}"
                f"\n  站点: {evt.get('source_sites', '未知')} | "
                f"报道数: {evt.get('article_count', 0)} | "
                f"时间: {str(evt.get('first_seen', '?'))[:10]}"
            )
        return "\n".join(lines)

    return get_events
