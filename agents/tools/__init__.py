"""Build all ChatAgent tools with dependency injection.

Each tool is a factory function that receives shared dependencies (stores,
searcher, coordinator, etc.) via closure and returns a @tool-decorated function.
"""

from .search import make_search_tool
from .get_item import make_get_item_tool
from .list_tags import make_list_tags_tool
from .get_snapshot import make_get_snapshot_tool
from .get_run_log import make_get_run_log_tool
from .fetch_article import make_fetch_article_tool
from .get_timeline import make_get_timeline_tool
from .preferences import make_preferences_tool
from .system_info import make_system_info_tool
from .watch import make_watch_tool
from .get_cost import make_get_cost_tool
from .get_circuit_status import make_get_circuit_status_tool
from .trigger_run import make_trigger_run_tool
from .dashboard_summary import make_dashboard_summary_tool
from .memory_audit import make_memory_audit_tool


def build_all_tools(agent) -> list:
    """Create all 15 tools, injecting shared dependencies from the agent."""
    all_targets = agent.config.get("targets", []) if agent.config else []
    return [
        # ── Query ──
        make_search_tool(
            agent.hybrid_searcher,
            agent.vector_store,
            agent.news_store,
            agent.paper_store,
        ),
        make_get_item_tool(agent.news_store, agent.paper_store),
        make_list_tags_tool(agent.news_store, agent.paper_store, all_targets),
        make_get_snapshot_tool(agent.news_store, agent.paper_store),
        make_get_run_log_tool(agent.news_store, agent.paper_store),
        make_fetch_article_tool(agent),
        make_get_timeline_tool(agent.news_store, agent.paper_store),
        # ── Analysis ──
        make_dashboard_summary_tool(agent.news_store, agent.paper_store, all_targets),
        # ── Management ──
        make_preferences_tool(agent),
        make_system_info_tool(agent.config),
        make_watch_tool(
            agent.watch_store,
            agent.vector_store,
            agent.config,
            agent.news_store,
            agent.paper_store,
        ),
        make_get_cost_tool(agent),
        make_get_circuit_status_tool(agent.news_store, agent.paper_store),
        make_trigger_run_tool(agent._coordinator),
        make_memory_audit_tool(agent),
    ]
