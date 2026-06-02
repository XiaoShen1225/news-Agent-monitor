"""trigger_run tool — manually trigger pipeline execution."""

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def make_trigger_run_tool(coordinator):
    @tool
    async def trigger_run(site_name: str = "") -> str:
        """手动触发系统抓取指定或全部站点的最新数据。耗时较长（10-30秒），请先告知用户正在执行。

        使用场景：用户说"刷新一下""立即抓取""帮我查最新"时使用。
        不传 site_name 或传'全部'则运行所有站点。
        """
        if not coordinator:
            return (
                "[触发错误] 无法触发抓取 — 未连接到调度系统。"
                "请通过 Web 仪表盘或命令行执行。"
            )

        site = (site_name or "").strip()
        if site and site != "全部":
            targets = coordinator.config.get("targets", [])
            target = next((t for t in targets if t["name"] == site), None)
            if not target:
                valid = ", ".join(t["name"] for t in targets)
                return f"[触发错误] 未找到站点 '{site}'。有效站点: {valid}"
            logger.info("[ChatAgent] User triggered run for %s", site)
            result = await coordinator.run_async(
                target["url"],
                site,
                use_browser=target.get("use_browser", False),
            )
            status = result.get("status", "unknown")
            changes = (
                result.get("report", {}).get("total_changes", 0)
                if result.get("report")
                else 0
            )
            return (
                f"[触发结果] {site} 抓取完成（状态: {status}）\n"
                f"- 变更数: {changes}\n"
                f"- 可使用 search 查询最新数据。"
            )
        else:
            logger.info("[ChatAgent] User triggered run for all sites")
            results = await coordinator.run_all_targets_async()
            lines = ["[触发结果] 全部站点抓取完成：", ""]
            for r in results:
                if isinstance(r, Exception):
                    lines.append(f"  - 错误: {r}")
                    continue
                sn = r.get("site_name", "?")
                st = r.get("status", "?")
                ch = (
                    r.get("report", {}).get("total_changes", 0)
                    if r.get("report")
                    else 0
                )
                lines.append(f"  - {sn}: {st} (变更 {ch} 项)")
            lines.append("")
            lines.append("[提示] 可使用 search 查询最新抓取结果。")
            return "\n".join(lines)

    return trigger_run
