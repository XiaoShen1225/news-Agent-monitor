"""get_cost tool — LLM token consumption statistics."""

from langchain_core.tools import tool


def make_get_cost_tool(agent):
    @tool
    async def get_cost(days: int = 7) -> str:
        """查看 LLM API 调用的 Token 消耗和费用统计（按站点聚合）。

        使用场景：用户问"用了多少token""花了多少钱""哪个站点最费token"时使用。
        """
        store = agent.news_store
        if store is None:
            return "[费用统计] 暂无数据。"

        rows = store.get_cost_summary(days=min(max(days, 1), 90))
        if not rows:
            return f"[费用统计] 最近{days}天没有运行记录。"

        total = sum(r["total_tokens"] for r in rows)
        lines = [
            f"[费用统计] 最近{days}天共消耗约 {total:,} tokens",
            "",
        ]
        for r in rows:
            pct = (r["total_tokens"] / total * 100) if total > 0 else 0
            lines.append(
                f"  {r['site_name']}: {r['total_tokens']:,} tokens "
                f"({r['runs']}次运行, {pct:.0f}%)"
            )
        return "\n".join(lines)

    return get_cost
