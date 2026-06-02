"""get_evolution_log tool — view evolution optimization history."""

from langchain_core.tools import tool

VALID_SITES = ["baidu_news", "sina_news", "deepmind_blog", "openai_blog"]


def make_get_evolution_log_tool(evolution):
    @tool
    async def get_evolution_log(site_name: str, limit: int = 10) -> str:
        """查看指定站点的进化优化历史，包括 prompt 调优记录、调度频率调整记录、优化统计。

        帮助理解系统如何自适应调整抓取策略。
        使用场景：用户问"优化效果怎么样？""调度频率调整过吗？""XX站点进化记录"时使用。
        """
        if site_name not in VALID_SITES:
            return (
                f"[参数错误] 未知站点 '{site_name}'。有效站点: {', '.join(VALID_SITES)}"
            )

        if not evolution:
            return "[进化日志] 进化优化器未启用，无进化记录。"

        memory = evolution.memory
        limit = min(max(limit, 1), 30)
        records = memory.get_recent(site_name, limit)
        stats = memory.get_stats(site_name)
        last_adj = memory.get_last_adjustment(site_name)
        opt_interval = memory.get_optimized_interval(site_name)

        lines = [f"[进化日志] 「{site_name}」优化历史："]
        lines.append(
            f"  统计: 累计运行 {stats.get('runs', 0)} 次，"
            f"平均置信度 {stats.get('avg_confidence', 0):.2f}，"
            f"平均变更 {stats.get('avg_changes_per_run', 0):.1f} 条/次，"
            f"平均耗时 {stats.get('avg_time_ms', 0):.0f}ms"
        )
        if stats.get("avg_tokens"):
            lines.append(f"  平均Token: {stats['avg_tokens']:.0f}/次")

        if opt_interval:
            lines.append(f"  优化调度间隔: {opt_interval} 分钟")

        if last_adj:
            lines.append(
                f"  最近调度调整: {last_adj.get('action', '?')} "
                f"({last_adj.get('old_interval', '?')}→{last_adj.get('new_interval', '?')}分钟，"
                f"{last_adj.get('timestamp', '')[:10]})"
            )

        if records:
            lines.append(f"\n  最近 {len(records)} 条运行记录：")
            for rec in records[:limit]:
                ts = rec.get("timestamp", "")[:19]
                items = rec.get("items_count", 0)
                changes = rec.get("changes_detected", 0)
                conf = rec.get("extraction_confidence", 0)
                tokens = rec.get("total_tokens", 0)
                lines.append(
                    f"    [{ts}] 抓取 {items} 条，变更 {changes}，"
                    f"置信度 {conf:.2f}，Token {tokens}"
                )
        else:
            lines.append("  暂无运行记录。")

        return "\n".join(lines)

    return get_evolution_log
