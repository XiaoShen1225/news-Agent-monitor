"""run_deep_analysis tool — manually trigger cross-site event clustering + entity extraction."""

from langchain_core.tools import tool


def make_run_deep_analysis_tool(coordinator):
    @tool
    async def run_deep_analysis() -> str:
        """手动触发深度分析：跨站点事件聚类 + 命名实体识别。

        使用场景：用户要求"分析最近趋势""跑一下深度分析""聚合跨站事件"时使用。
        分析耗时 10-30 秒，完成后可通过 get_events/get_entities 查看结果。
        """
        if coordinator is None:
            return "[深度分析] Coordinator 未初始化，无法触发。"

        result = await coordinator.run_deep_analysis_manual()
        if not result.get("ok"):
            return f"[深度分析] 触发失败: {result.get('msg', '未知错误')}"

        return (
            f"[深度分析] 已完成！\n"
            f"事件簇: {result.get('event_count', 0)} 个\n"
            f"命名实体: {result.get('entity_count', 0)} 个\n"
            f"分析条目数: {result.get('items_analyzed', 0)} 条\n\n"
            "使用 get_events 查看事件、get_entities 查看实体榜单。"
        )

    return run_deep_analysis
