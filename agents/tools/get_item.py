"""get_item tool — fetch single item from local cache."""

from langchain_core.tools import tool


def make_get_item_tool(news_store, paper_store):
    @tool
    async def get_item(url: str) -> str:
        """获取指定URL的单篇新闻完整信息（缓存摘要、标签、情感等），不发起网络请求。

        使用场景：用户搜索后想了解某篇文章的详细信息时使用。
        与 fetch_article 区别：get_item 查本地缓存（秒级），fetch_article 抓取网页+AI摘要（10-15秒）。
        """
        if not url:
            return "[参数错误] 未提供 url 参数。"

        for store in (news_store, paper_store):
            if store is None:
                continue
            summary = store.get_item_summary(url)
            if summary:
                return f"[文章缓存]\n{summary[:500]}"

        # Fallback: search by URL
        for store in (news_store, paper_store):
            if store is None:
                continue
            items = store.query_items(limit=200)
            matches = [it for it in items if it.get("url") == url]
            if matches:
                it = matches[0]
                lines = [
                    f"[文章缓存] URL: {url}",
                    f"标题: {it.get('title', '无标题')}",
                    f"标签: {it.get('tag', '无标签')}",
                    f"站点: {it.get('site_name', '未知')}",
                    f"时间: {it.get('snapshot_time', '未知')}",
                    f"情感: {it.get('sentiment', '未知')}",
                ]
                if it.get("summary"):
                    lines.append(f"\n摘要: {it['summary'][:500]}")
                return "\n".join(lines)

        return f"[文章缓存] 未找到 URL 对应的文章: {url}"

    return get_item
