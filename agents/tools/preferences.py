"""preferences tool — view/update user preferences."""

from langchain_core.tools import tool


def make_preferences_tool(agent):
    @tool
    async def preferences(
        action: str = "view",
        interest: str = "",
        preference: str = "like",
        confidence: float = 0.9,
    ) -> str:
        """查看或更新用户偏好。

        查看：不传参数或 action='view'。用户问"我喜欢什么""我的偏好吗"时使用。
        更新：传 action='update' + interest + preference。用户表达"喜欢/不喜欢某类"时使用。
        提示：搜索前先查偏好，有明确兴趣标签时可传给 search 的 tag 参数。
        """
        engine = getattr(agent, "_preference_engine", None)

        if action == "view":
            if engine is not None:
                return engine.format_for_display()
            return "[偏好] 偏好系统未初始化，暂无偏好数据。"

        if action == "update":
            if not interest.strip():
                return "[参数错误] update 操作需要提供 interest 参数。"
            if engine is None:
                return "[偏好] 偏好系统未初始化，无法更新。"
            pref = preference if preference in ("like", "dislike") else "like"
            conf = min(max(confidence, 0), 1)
            engine.set_override(interest.strip(), pref, conf)
            action_text = "喜欢" if pref == "like" else "不喜欢"
            return f"[偏好] 已更新：{action_text}「{interest.strip()}」（确信度: {conf:.0%}）"

        return f"[参数错误] 未知操作: {action}。支持 view（查看）和 update（更新）。"

    return preferences
