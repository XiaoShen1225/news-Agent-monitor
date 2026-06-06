"""dashboard_summary tool — one-shot overview of all monitored sites."""

from langchain_core.tools import tool


def make_dashboard_summary_tool(news_store, paper_store):
    @tool
    async def dashboard_summary() -> str:
        """获取所有监控站点的运行概况（健康状态、条目数、趋势、最近更新时间）。

        使用场景：用户问"系统运行怎么样""整体概况""各站点状态"时使用。
        比逐个调用 get_snapshot 高效——一次返回全部站点摘要。
        """
        sites = [
            ("baidu_news", news_store),
            ("sina_news", news_store),
            ("deepmind_blog", paper_store),
            ("openai_blog", paper_store),
        ]

        lines = ["[系统概况] 所有站点运行状态："]
        total_items = 0
        healthy = 0
        warning = 0

        for name, store in sites:
            if store is None:
                lines.append(f"\n{name}: 无数据")
                continue

            meta = store.get_metadata(name)
            if not meta:
                lines.append(f"\n{name}: 暂无快照数据")
                continue

            history = meta.get("count_history", []) or []
            count = history[-1][1] if history else 0
            total_items += count
            updated = (meta.get("updated_at", "未知") or "未知")[:19]
            changes = meta.get("latest_changes", {}) or {}
            new_c = changes.get("new", 0)
            removed_c = changes.get("removed", 0)

            circuit_open = store.is_circuit_open(name)

            trend = "—"
            if len(history) >= 2:
                recent = [h[1] for h in history[-3:]]
                older = (
                    [h[1] for h in history[:-3]]
                    if len(history) > 3
                    else [history[0][1]]
                )
                recent_avg = sum(recent) / len(recent)
                older_avg = sum(older) / len(older)
                if recent_avg > older_avg * 1.1:
                    trend = "↑"
                elif recent_avg < older_avg * 0.9:
                    trend = "↓"
                else:
                    trend = "→"

            if circuit_open:
                status = "🔴 熔断"
                warning += 1
            elif new_c == 0 and removed_c == 0 and count > 0:
                status = "🟡 无变化"
                warning += 1
            else:
                status = "🟢 正常"
                healthy += 1

            lines.append(
                f"\n{name}: {status} | {count} 条 | 趋势 {trend}"
                f" | 新增 {new_c} / 删除 {removed_c}"
                f" | 更新于 {updated}"
            )
            if circuit_open:
                lines.append("  ⚠ 连续失败过多，已暂时跳过该站点")

        lines.insert(1, f"共 {total_items} 条 | {healthy} 正常 / {warning} 异常")
        return "\n".join(lines)

    return dashboard_summary
