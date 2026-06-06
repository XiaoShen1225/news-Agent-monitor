"""get_run_log tool — get pipeline run history for a site."""

from langchain_core.tools import tool


def make_get_run_log_tool(news_store, paper_store):
    @tool
    async def get_run_log(site_name: str, limit: int = 5) -> str:
        """获取指定站点的抓取运行历史（每次运行的状态、条目数、变更数、耗时、token消耗）。

        使用场景：用户问"最近运行正常吗""抓取有没有报错""token消耗情况"时使用。
        """
        store = (
            paper_store if site_name in ("deepmind_blog", "openai_blog") else news_store
        )
        if store is None:
            return f"[运行历史] 站点 {site_name} 暂无数据。"

        runs = store.get_run_history(site_name, limit=min(max(limit, 1), 20))
        if not runs:
            return f"[运行历史] 站点 {site_name} 暂无运行记录。"

        lines = [f"[运行历史] {site_name} (最近 {len(runs)} 次):"]
        for r in runs:
            status = r.get("status", "unknown")
            icon = {"success": "✓", "error": "✗", "skipped_no_change": "○"}.get(
                status, "?"
            )
            lines.append(
                f"  {icon} {r.get('timestamp', '?')[:19]} | "
                f"条目: {r.get('items_found', 0)} | "
                f"变更: {r.get('changes_detected', 0)} | "
                f"耗时: {r.get('processing_time_ms', 0):.0f}ms | "
                f"Token: {r.get('total_tokens', 0)}"
            )
            if r.get("error_message"):
                lines.append(f"    错误: {r['error_message'][:100]}")
        return "\n".join(lines)

    return get_run_log
