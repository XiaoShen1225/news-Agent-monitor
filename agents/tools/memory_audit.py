"""memory_audit tool — view memory system health report."""

from langchain_core.tools import tool


def make_memory_audit_tool(agent):
    @tool
    async def memory_audit() -> str:
        """查看记忆系统健康状态。

        返回三层记忆（L0/L1/L2）的数据统计和健康诊断。
        用户问"记忆系统怎么样""偏好数据有多少"时使用。
        """
        ts = getattr(agent, "_track_store", None)
        if ts is None:
            return "[记忆审计] 记忆系统未初始化。"

        l0_active = ts.get_l0_events(status="active", limit=1000)
        l0_stale = ts.get_l0_events(status="soft_deleted", limit=1000)

        # Also get L1/L2 from PreferenceEngine
        engine = getattr(agent, "_preference_engine", None)
        l1 = {}
        l2 = {}
        if engine is not None:
            current = engine.get_current()
            l1 = current.get("l1", {}) or {}
            l2 = current.get("l2", {}) or {}

        parts = ["[记忆系统健康]"]

        # Stats
        parts.append(f"L0 活跃事件: {len(l0_active)} 条")
        if l0_stale:
            parts.append(f"L0 待清理: {len(l0_stale)} 条")

        l1_interests = l1.get("active_interests", [])
        if l1_interests:
            parts.append(f"L1 活跃主题: {len(l1_interests)} 个")
            items = [
                f"{i['name']}({i.get('trend', 'stable')})" for i in l1_interests[:5]
            ]
            parts.append(f"  详情: {', '.join(items)}")
        else:
            parts.append("L1 模式: 暂无数据")

        l2_interests = l2.get("stable_interests", [])
        if l2_interests:
            parts.append(f"L2 稳定兴趣: {len(l2_interests)} 个")
            items = [f"{i['name']}({i['strength']:.0%})" for i in l2_interests[:5]]
            parts.append(f"  详情: {', '.join(items)}")
            identity = l2.get("identity", "")
            if identity:
                parts.append(f"  身份推测: {identity}")
        else:
            parts.append("L2 画像: 暂无数据")

        # Health status
        stale_ratio = len(l0_stale) / max(len(l0_active) + len(l0_stale), 1)
        if stale_ratio > 0.3:
            parts.append(f"⚠ 过期率偏高 ({stale_ratio:.0%})，建议检查 TTL 策略")
        elif len(l0_active) == 0 and not l2_interests:
            parts.append("状态: 空闲（尚无足够数据）")
        else:
            parts.append("状态: 正常")

        return "\n".join(parts)

    return memory_audit
