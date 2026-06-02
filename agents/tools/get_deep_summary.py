"""get_deep_summary tool — cross-site deep analysis overview."""

from langchain_core.tools import tool


def make_get_deep_summary_tool(news_store, paper_store):
    @tool
    async def get_deep_summary(days: int = 7) -> str:
        """获取深度分析摘要：跨站事件聚合和命名实体识别结果。

        展示最近发现的跨站点关联事件和重要实体。
        使用场景：用户问"有什么跨站大事件？""最近有什么热点趋势？""识别出哪些实体？"时使用。
        """
        events = []
        entities = []
        for store in (news_store, paper_store):
            if store is None:
                continue
            try:
                evts = store.get_events(limit=10)
                events.extend(evts or [])
                ents = store.get_entities(limit=15)
                entities.extend(ents or [])
            except Exception:
                pass

        lines = ["[深度分析摘要]"]
        lines.append(f"\n最近事件（共 {len(events)} 个）：")
        if events:
            for ev in events[:10]:
                ev_sites = ev.get("sites", [])
                if isinstance(ev_sites, str):
                    import json

                    try:
                        ev_sites = json.loads(ev_sites)
                    except Exception:
                        ev_sites = []
                ev_tags = ev.get("tags", [])
                if isinstance(ev_tags, str):
                    import json

                    try:
                        ev_tags = json.loads(ev_tags)
                    except Exception:
                        ev_tags = []
                sites = ", ".join(ev_sites[:4])
                tags = ", ".join(ev_tags[:3])
                lines.append(
                    f"  - [{ev.get('event_id', ev.get('id', '?'))}] "
                    f"{ev.get('event_name', ev.get('title', '?'))}"
                    f"（{ev.get('item_count', ev.get('article_count', 0))} 条，"
                    f"跨 {len(ev_sites)} 站）"
                    f" | 站点: {sites}" + (f" | 标签: {tags}" if tags else "")
                )
        else:
            lines.append("  暂无事件。系统会在每次全量抓取后自动运行深度分析。")

        lines.append(f"\n高频实体（共 {len(entities)} 个）：")
        if entities:
            for ent in entities[:15]:
                lines.append(
                    f"  - [{ent.get('type', '?')}] {ent.get('name', '?')}"
                    f"（提及 {ent.get('mentions', ent.get('count', 0))} 次，"
                    f"最近: {(ent.get('last_seen') or '')[:10]}）"
                )
        else:
            lines.append("  暂无识别实体。")

        return "\n".join(lines)

    return get_deep_summary
