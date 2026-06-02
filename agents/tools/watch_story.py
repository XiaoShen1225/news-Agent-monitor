"""watch_story tool — manage story tracking lifecycle."""

from langchain_core.tools import tool


def make_watch_story_tool(story_watch, vector_store, config):
    @tool
    async def watch_story(
        action: str,
        title: str = "",
        url: str = "",
        story_id: str = "",
        status: str = "",
    ) -> str:
        """追踪新闻故事的生命周期。

        action='list'（查看）/ 'add'（添加追踪）/ 'remove'（删除）/ 'complete'（标记完结）/ 'reactivate'（重新激活）。
        使用场景：用户说"帮我追踪XX事件"时用add；"XX事件进展如何"时用list。
        list时可传status筛选：active(活跃), dormant(休眠), completed(已完成)。
        """
        store = story_watch
        if store is None:
            return "[故事追踪错误] 故事追踪系统未初始化，请联系管理员。"

        if action == "list":
            status_filter = status or None
            stories = store.list_stories(status=status_filter)
            if not stories:
                status_hint = f"（状态: {status_filter}）" if status_filter else ""
                return f"[故事追踪] 当前没有追踪任何新闻故事{status_hint}。"

            active = [s for s in stories if s["status"] == "active"]
            completed = [s for s in stories if s["status"] == "completed"]
            dormant = [s for s in stories if s["status"] == "dormant"]

            filter_label = f"（筛选: {status_filter}）" if status_filter else ""
            lines = [f"[故事追踪] 当前追踪状态{filter_label}："]
            if active:
                lines.append(f"\n活跃 ({len(active)} 个)：")
                for s in active:
                    lines.append(
                        f"  ID: {s['id']} | 「{s['title'][:50]}」"
                        f" | 已匹配 {s['match_count']} 次"
                    )
            if completed:
                lines.append(f"\n已完成 ({len(completed)} 个)：")
                for s in completed:
                    lines.append(f"  ID: {s['id']} | 「{s['title'][:50]}」")
            if dormant:
                lines.append(f"\n休眠 ({len(dormant)} 个，超过30天无后续)：")
                for s in dormant:
                    lines.append(f"  ID: {s['id']} | 「{s['title'][:50]}」")
            return "\n".join(lines)

        if action == "add":
            title_val = (title or "").strip()
            if not title_val:
                return "[故事追踪错误] 请提供要追踪的新闻标题（title参数）。"
            url_val = (url or "").strip()

            embedding = None
            source_site = ""
            if vector_store:
                embedding = store.compute_embedding(title_val, vector_store)
            if url_val:
                for t in config.get("targets", []):
                    if t.get("name", "") in url_val:
                        source_site = t["name"]
                        break

            r = store.add_story(
                title=title_val,
                url=url_val,
                source_site=source_site,
                embedding=embedding,
            )
            return (
                f"[故事追踪] {r['msg']}。活跃的故事会在每次新闻抓取后自动检查后续报道。"
            )

        if action == "remove":
            sid = (story_id or "").strip()
            ttl = (title or "").strip()
            if not sid and not ttl:
                return "[故事追踪错误] 请提供 story_id 或 title。"
            r = store.remove_story(story_id=sid, title=ttl)
            return f"[故事追踪] {r['msg']}。"

        if action == "complete":
            sid = (story_id or "").strip()
            if not sid:
                return "[故事追踪错误] 请提供 story_id。"
            r = store.complete_story(sid)
            return f"[故事追踪] {r['msg']}。"

        if action == "reactivate":
            sid = (story_id or "").strip()
            if not sid:
                return "[故事追踪错误] 请提供 story_id。"
            r = store.reactivate_story(sid)
            return f"[故事追踪] {r['msg']}。"

        return f"[故事追踪错误] 未知操作: {action}"

    return watch_story
