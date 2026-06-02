"""system_info tool — view system configuration."""

from langchain_core.tools import tool


def make_system_info_tool(config):
    @tool
    async def system_info(aspect: str = "targets") -> str:
        """查看系统配置（监控目标列表或调度设置）。

        查目标：不传 aspect 或传 'targets'。用户问"监控了哪些网站"时使用。
        查调度：传 aspect='schedule'。用户问"多久抓取一次"时使用。
        其他工具接收的 site_name 以此返回的 name 为准。
        """
        if aspect not in ("targets", "schedule"):
            return f"[参数错误] 不支持的 aspect: {aspect}。可选: targets（监控目标）, schedule（调度配置）"

        if aspect == "targets":
            targets = config.get("targets", [])
            if not targets:
                return "[系统配置] 暂无监控目标配置。"

            lines = ["[监控目标] 当前监控的网站:"]
            for i, t in enumerate(targets, 1):
                lines.append(
                    f"\n  {i}. {t.get('name', '?')}"
                    f"\n     URL: {t.get('url', '?')}"
                    f"\n     方式: {'浏览器' if t.get('use_browser') else '静态抓取'}"
                    f"\n     频率: {t.get('interval_minutes', '?')} 分钟"
                )
                if t.get("profile"):
                    lines.append(f"     类型: {t['profile'].get('type', '?')}")
            return "\n".join(lines)

        if aspect == "schedule":
            sched = config.get("scheduler", {})
            lines = [
                "[调度配置]",
                f"调度器: {'已启用' if sched.get('enabled') else '已禁用'}",
                f"时区: {sched.get('timezone', 'Asia/Shanghai')}",
                f"并发数: {sched.get('max_concurrent', '?')}",
                f"重试次数: {sched.get('max_retries', '?')}",
                "",
                "各站点调度:",
            ]
            triggers = sched.get("triggers", [])
            if triggers:
                for t in triggers:
                    lines.append(
                        f"  {t.get('site_name', '?')}: "
                        f"cron='{t.get('cron', '?')}' "
                        f"({'浏览器' if t.get('use_browser') else '静态'})"
                    )
            else:
                for target in config.get("targets", []):
                    lines.append(
                        f"  {target.get('name', '?')}: "
                        f"每 {target.get('interval_minutes', '?')} 分钟"
                    )
            return "\n".join(lines)

    return system_info
