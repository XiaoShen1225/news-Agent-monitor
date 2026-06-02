"""get_entities tool — named entity recognition results."""

from langchain_core.tools import tool


def make_get_entities_tool(news_store, paper_store):
    @tool
    async def get_entities(
        entity_name: str = "",
        limit: int = 10,
        type: str = "",
    ) -> str:
        """获取命名实体列表或某个实体的关联新闻。

        查列表：不传 entity_name。用户问"提到了哪些公司""有哪些人物"时使用。
        查详情：传 entity_name。用户问"关于XX的报道"时使用。
        type 可选 PER(人名)/ORG(组织)/LOC(地点)/PROD(产品)/EVENT(事件)，不传返回全部。
        """
        entity_type = type if type in ("PER", "ORG", "LOC", "PROD", "EVENT") else None
        entities = []
        for store in (news_store, paper_store):
            if store is None:
                continue
            try:
                ents = store.get_entities(limit=max(limit, 50), entity_type=entity_type)
                entities.extend(ents or [])
            except Exception:
                pass

        if not entities:
            return "[命名实体] 暂无实体识别数据。系统需要新数据来执行实体提取。"

        limit = min(max(limit, 1), 30)

        if entity_name:
            for ent in entities:
                if ent.get("name") == entity_name:
                    items = ent.get("items", [])
                    lines = [
                        f"[实体详情] {ent['name']}",
                        f"类型: {ent.get('type', '未知')}",
                        f"关联文章 ({len(items)} 篇):",
                    ]
                    for it in items[:10]:
                        lines.append(
                            f"  - [{it.get('site_name', '?')}] {it.get('title', '无标题')[:60]}"
                        )
                    return "\n".join(lines)
            return f"[命名实体] 未找到实体: {entity_name}"

        type_label = {
            "PER": "人物",
            "ORG": "组织",
            "LOC": "地点",
            "PROD": "产品",
            "EVENT": "事件",
        }
        lines = [
            f"[命名实体] 实体列表{' (' + type_label.get(type, type) + ')' if type else ''}:"
        ]
        for ent in entities[:limit]:
            lines.append(
                f"  [{ent.get('type', '?')}] {ent.get('name', '未知')[:40]}"
                f" — {ent.get('count', 0)} 篇"
            )
        return "\n".join(lines)

    return get_entities
