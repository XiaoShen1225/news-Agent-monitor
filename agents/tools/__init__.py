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
from .get_events import make_get_events_tool
from .get_entities import make_get_entities_tool
from .get_timeline import make_get_timeline_tool
from .preferences import make_preferences_tool
from .system_info import make_system_info_tool
from .set_alert import make_set_alert_tool
from .watch_story import make_watch_story_tool
from .get_cost import make_get_cost_tool
from .get_circuit_status import make_get_circuit_status_tool
from .get_evolution_log import make_get_evolution_log_tool
from .get_deep_summary import make_get_deep_summary_tool
from .trigger_run import make_trigger_run_tool
from .dashboard_summary import make_dashboard_summary_tool
from .run_deep_analysis import make_run_deep_analysis_tool


def build_all_tools(agent) -> list:
    """Create all 20 tools, injecting shared dependencies from the agent."""
    return [
        # ── Query ──
        make_search_tool(
            agent.hybrid_searcher,
            agent.vector_store,
            agent.news_store,
            agent.paper_store,
        ),
        make_get_item_tool(agent.news_store, agent.paper_store),
        make_list_tags_tool(agent.news_store, agent.paper_store),
        make_get_snapshot_tool(agent.news_store, agent.paper_store),
        make_get_run_log_tool(agent.news_store, agent.paper_store),
        make_fetch_article_tool(agent),
        make_get_timeline_tool(agent.news_store, agent.paper_store),
        # ── Analysis ──
        make_get_events_tool(agent.news_store, agent.paper_store),
        make_get_entities_tool(agent.news_store, agent.paper_store),
        make_get_deep_summary_tool(agent.news_store, agent.paper_store),
        make_run_deep_analysis_tool(agent._coordinator),
        make_dashboard_summary_tool(agent.news_store, agent.paper_store),
        # ── Management ──
        make_preferences_tool(agent),
        make_system_info_tool(agent.config),
        make_set_alert_tool(agent.alert_store),
        make_watch_story_tool(agent.story_watch, agent.vector_store, agent.config),
        make_get_cost_tool(agent),
        make_get_circuit_status_tool(agent.news_store, agent.paper_store),
        make_get_evolution_log_tool(agent._evolution),
        make_trigger_run_tool(agent._coordinator),
    ]
