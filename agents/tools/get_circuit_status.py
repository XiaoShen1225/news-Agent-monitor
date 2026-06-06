"""get_circuit_status tool — check circuit breaker health."""

from langchain_core.tools import tool


def make_get_circuit_status_tool(news_store, paper_store):
    @tool
    async def get_circuit_status(site_name: str = "") -> str:
        """查询站点的断路器状态和连续失败次数。用于诊断系统健康状态。

        不传 site_name 则返回全部站点的状态。
        使用场景：用户问"系统出问题了吗？""为什么XX站点没更新？""哪些站点故障了？"时使用。
        """
        store = news_store
        if store is None:
            return "[断路器状态] 暂无数据。"

        if site_name:
            result = store.get_circuit_status(site_name)
            r = result  # single dict
            cb = "【熔断中】" if r.get("circuit_open") else "正常"
            msg = (
                f"[断路器状态] {r['site_name']}: {cb}，"
                f"连续失败 {r.get('consecutive_failures', 0)} 次"
            )
            if r.get("circuit_open") and r.get("circuit_breaker_until"):
                msg += f"，预计恢复: {r['circuit_breaker_until'][:19]}"
            return msg

        # All sites
        results = store.get_circuit_status()
        if not results:
            return "[断路器状态] 暂无站点元数据。"
        lines = ["[断路器状态] 全部站点："]
        for r in results:
            cb = "【熔断中】" if r.get("circuit_open") else "正常"
            lines.append(
                f"  - {r['site_name']}: {cb}（"
                f"连续失败 {r.get('consecutive_failures', 0)} 次）"
            )
        return "\n".join(lines)

    return get_circuit_status
