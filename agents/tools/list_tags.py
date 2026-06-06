"""list_tags tool — get tag distribution across sites."""

from langchain_core.tools import tool


def make_list_tags_tool(news_store, paper_store, all_targets=None):
    @tool
    async def list_tags(site_name: str = "") -> str:
        """列出当前可用的标签及其条目数量分布。

        使用场景：用户问"有哪些分类""标签分布"时，或搜索前想了解有哪些标签可选时使用。
        可传 site_name 限定站点，不传则返回全站标签汇总。
        """
        from agents.site_profiles import is_article_site

        stores = []
        if site_name:
            store = paper_store if is_article_site(site_name) else news_store
            if store:
                stores = [(site_name, store)]
        else:
            targets = all_targets or []
            for t in targets:
                name = t.get("name") or t.get("site_name", "")
                if not name:
                    continue
                store = paper_store if is_article_site(name) else news_store
                if store:
                    stores.append((name, store))

        if not stores:
            return "[标签] 暂无数据。"

        lines = [f"[标签分布] {'站点: ' + site_name if site_name else '全站汇总'}："]
        for name, store in stores:
            meta = store.get_metadata(name)
            if not meta:
                continue
            dist = meta.get("latest_tag_distribution", {})
            if not dist:
                continue
            if not site_name:
                lines.append(f"\n{name}:")
            items = sorted(dist.items(), key=lambda x: x[1], reverse=True)
            for tag, count in items:
                lines.append(f"  {tag}: {count} 条")
        return "\n".join(lines) if len(lines) > 1 else "[标签] 暂无数据。"

    return list_tags
