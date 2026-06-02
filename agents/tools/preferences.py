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
        prefs = agent._preferences
        overrides = prefs.get("explicit_overrides", {})

        if action == "view":
            if not overrides and not prefs.get("inferences", {}).get("top_interests"):
                return (
                    "[偏好] 当前还没有偏好设置。系统会根据你的查询行为自动学习你的兴趣。\n"
                    "你可以说「我喜欢AI相关的内容」来主动设置偏好。"
                )

            lines = ["[用户偏好]"]
            if overrides:
                likes = [k for k, v in overrides.items() if v.get("action") == "like"]
                dislikes = [
                    k for k, v in overrides.items() if v.get("action") == "dislike"
                ]
                if likes:
                    lines.append(f"喜欢: {', '.join(likes)}")
                if dislikes:
                    lines.append(f"不喜欢: {', '.join(dislikes)}")

            inferences = prefs.get("inferences", {})
            if inferences.get("top_interests"):
                lines.append(
                    f"系统推断的兴趣: {', '.join(inferences['top_interests'][:5])}"
                )
            if inferences.get("summary"):
                lines.append(f"偏好概要: {inferences['summary'][:200]}")
            if inferences.get("interest_confidence"):
                lines.append(f"偏好确信度: {inferences['interest_confidence']:.0%}")
            return "\n".join(lines)

        if action == "update":
            if not interest.strip():
                return "[参数错误] update 操作需要提供 interest 参数。"
            pref = preference if preference in ("like", "dislike") else "like"
            conf = min(max(confidence, 0), 1)

            overrides[interest.strip()] = {
                "action": pref,
                "confidence": conf,
                "updated_at": agent._now_iso(),
            }
            prefs["explicit_overrides"] = overrides
            agent._save_preferences()
            action_text = "喜欢" if pref == "like" else "不喜欢"
            return f"[偏好] 已更新：{action_text}「{interest.strip()}」（确信度: {conf:.0%}）"

        return f"[参数错误] 未知操作: {action}。支持 view（查看）和 update（更新）。"

    return preferences
