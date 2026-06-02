"""set_alert tool — manage keyword alerts."""

from langchain_core.tools import tool


def make_set_alert_tool(alert_store):
    @tool
    async def set_alert(action: str, keyword: str = "") -> str:
        """管理关键词告警。

        action='list'（查看全部告警）/ 'add'（添加关键词）/ 'remove'（删除关键词）。
        使用场景：用户说"有AI新闻告诉我""帮我关注科技"时用add；"有哪些告警"时用list；"取消XX告警"时用remove。
        """
        if alert_store is None:
            return "[告警错误] 告警系统未初始化，请联系管理员。"

        if action == "list":
            alerts = alert_store.get_keywords()
            if not alerts:
                return "[告警] 当前没有设置任何关键词告警。使用 '如果有XX的新闻请告诉我' 来添加。"
            return "[告警] 当前告警关键词: " + ", ".join(
                f"「{a['keyword']}」" for a in alerts
            )

        kw = (keyword or "").strip()
        if not kw:
            return "[告警错误] keyword参数不能为空（add/remove操作需要关键词）。"

        if action == "add":
            r = alert_store.add_keyword(kw)
            return f"[告警] {r['msg']}。"

        if action == "remove":
            r = alert_store.remove_keyword(kw)
            if r.get("ok"):
                return f"[告警] {r['msg']}。"
            return f"[告警] {r['msg']}，无需移除。"

        return f"[参数错误] 未知操作: {action}。支持 list、add、remove。"

    return set_alert
