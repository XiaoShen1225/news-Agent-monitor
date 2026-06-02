"""get_snapshot tool — get latest site snapshot summary."""

from langchain_core.tools import tool

VALID_SITES = ["baidu_news", "sina_news", "deepmind_blog", "openai_blog"]


def make_get_snapshot_tool(news_store, paper_store):
    @tool
    async def get_snapshot(site_name: str) -> str:
        """获取指定站点的最新快照概要（条目数、标签分布、更新摘要、更新时间）。

        使用场景：用户问"某站点有多少数据""最近更新了什么"时使用。
        不含运行历史，如需运行状态用 get_run_log。
        """
        if site_name not in VALID_SITES:
            return (
                f"[参数错误] 未知站点 '{site_name}'。有效站点: {', '.join(VALID_SITES)}"
            )

        store = (
            paper_store if site_name in ("deepmind_blog", "openai_blog") else news_store
        )
        if store is None:
            return f"[快照] 站点 {site_name} 暂无数据。"

        meta = store.get_metadata(site_name)
        if not meta:
            return f"[快照] 站点 {site_name} 暂无数据。"

        lines = [f"[站点快照] {site_name}"]
        lines.append(f"更新时间: {meta.get('updated_at', '未知')}")
        lines.append(f"条目数: {meta.get('items_count', 0)}")

        dist = meta.get("latest_tag_distribution", {})
        if dist:
            lines.append("标签分布:")
            for tag, count in sorted(dist.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {tag}: {count} 条")

        changes = meta.get("changes", {})
        if changes:
            lines.append(
                f"最近变更: 新增 {changes.get('new', 0)}, "
                f"删除 {changes.get('removed', 0)}, "
                f"修改 {changes.get('modified', 0)}"
            )

        summary = meta.get("update_summary", "")
        if summary:
            lines.append(f"更新摘要: {summary[:300]}")

        return "\n".join(lines)

    return get_snapshot
