"""watch tool — unified topic monitoring + event tracking."""

from langchain_core.tools import tool


def make_watch_tool(
    watch_store, vector_store, config, news_store=None, paper_store=None
):
    @tool
    async def watch(
        action: str,
        type: str = "topic",
        title: str = "",
        keywords: str = "",
        watch_id: str = "",
        status: str = "",
    ) -> str:
        """管理统一关注系统（主题监控 + 事件追踪）。

        支持的操作：
        - add: 添加关注。用户说"关注AI"→type="topic"；"追踪这个事件"→type="event"
        - list: 查看所有关注。可选status参数：active/completed/paused
        - remove: 删除关注，需要watch_id
        - complete: 标记事件为已完结，需要watch_id
        - pause: 暂停关注，需要watch_id
        - resume: 恢复关注，需要watch_id

        参数：
        - action: "add"|"list"|"remove"|"complete"|"pause"|"resume"
        - type: "topic"(长期主题监控)|"event"(特定事件追踪)，仅add时需要
        - title: 关注标题/名称，仅add时需要
        - keywords: 逗号分隔的关键词，仅topic类型需要
        - watch_id: 内部ID，remove/complete/pause/resume时需要
        - status: 按状态过滤list结果：active/completed/paused，不传返回全部
        """
        if action == "list":
            status_filter = (
                status if status in ("active", "completed", "paused") else None
            )
            watches = watch_store.list_watches(status=status_filter)
            if not watches:
                return "[关注列表] 暂无关注项。用「add」添加主题或事件追踪。"

            active = [w for w in watches if w["status"] == "active"]
            completed = [w for w in watches if w["status"] == "completed"]
            paused = [w for w in watches if w["status"] == "paused"]

            lines = [f"[关注列表] 共 {len(watches)} 项"]
            if active:
                lines.append(f"\n▸ 活跃 ({len(active)}):")
                for w in active:
                    t = "主题" if w["type"] == "topic" else "事件"
                    kws = ", ".join(w.get("keywords", [])[:5])
                    lines.append(
                        f"  [{t}] {w['title'][:40]} "
                        f"(ID: {w['id']}, 匹配: {w['match_count']})"
                    )
                    if kws:
                        lines.append(f"    关键词: {kws}")
            if paused:
                lines.append(f"\n▸ 暂停 ({len(paused)}):")
                for w in paused:
                    lines.append(f"  [{w['type']}] {w['title'][:40]} (ID: {w['id']})")
            if completed:
                lines.append(f"\n▸ 已完成 ({len(completed)}):")
                for w in completed[:5]:
                    lines.append(f"  [{w['type']}] {w['title'][:40]} (ID: {w['id']})")
            return "\n".join(lines)

        if action == "add":
            if not title.strip():
                return "[关注] 请提供关注标题，例如「关注AI领域动态」"
            watch_type = type if type in ("topic", "event") else "topic"
            kw_list = (
                [k.strip() for k in keywords.split(",") if k.strip()]
                if keywords
                else []
            )

            # Compute embedding for semantic matching
            embedding = None
            if vector_store:
                try:
                    embedding = watch_store.compute_embedding(title, vector_store)
                except Exception:
                    pass

            result = watch_store.add_watch(
                watch_type=watch_type,
                title=title.strip(),
                keywords=kw_list,
                embedding=embedding,
            )

            # Retroactive initialization: search existing items
            watch_id_new = result.get("watch_id", "")
            if result.get("ok") and watch_id_new:
                try:
                    recent = []
                    for store in (news_store, paper_store):
                        if store is None:
                            continue
                        try:
                            items = store.query_items(limit=500)
                            if items:
                                recent.extend(items)
                        except Exception:
                            pass
                    if recent:
                        n = watch_store.initialize_matches(
                            watch_id_new, recent, vector_store
                        )
                        if n > 0:
                            return f"[关注] {result['msg']}，已从历史数据中回溯匹配 {n} 条相关新闻。"
                except Exception:
                    pass

            return f"[关注] {result['msg']}"

        if action == "remove":
            if not watch_id:
                return "[关注] 请提供要删除的关注ID（可通过 list 查看）"
            result = watch_store.remove_watch(watch_id)
            return f"[关注] {result['msg']}"

        if action == "complete":
            if not watch_id:
                return "[关注] 请提供要完成的关注ID（可通过 list 查看）"
            result = watch_store.complete_watch(watch_id)
            return f"[关注] {result['msg']}"

        if action == "pause":
            if not watch_id:
                return "[关注] 请提供要暂停的关注ID（可通过 list 查看）"
            result = watch_store.pause_watch(watch_id)
            return f"[关注] {result['msg']}"

        if action == "resume":
            if not watch_id:
                return "[关注] 请提供要恢复的关注ID（可通过 list 查看）"
            result = watch_store.resume_watch(watch_id)
            return f"[关注] {result['msg']}"

        return f"[关注] 不支持的操作: {action}。支持: add/list/remove/complete/pause/resume"

    return watch
