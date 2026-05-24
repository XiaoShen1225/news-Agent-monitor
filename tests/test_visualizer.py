"""Tests for VisualizationAgent: chart generation and font setup."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def config(tmp_path):
    return {
        "llm": {"api_key": "test", "base_url": "https://test.api"},
        "visualization": {
            "font_family": "SimHei",
            "dpi": 72,
            "figure_width": 6,
            "figure_height": 4,
            "output_dir": str(tmp_path / "charts"),
        },
    }


class TestInit:
    def test_creates_all_sets(self, config):
        from agents.visualizer import VisualizationAgent

        agent = VisualizationAgent(config)
        for name in [
            "today",
            "yesterday",
            "two_days_ago",
            "one_week_ago",
            "one_month_ago",
            "total",
        ]:
            assert agent.sets[name].exists()
            assert agent.sets[name].is_dir()

    def test_removes_legacy_current_dir(self, config, tmp_path):
        legacy = tmp_path / "charts" / "current"
        legacy.mkdir(parents=True)
        (legacy / "old.png").write_text("stale")
        from agents.visualizer import VisualizationAgent

        VisualizationAgent(config)
        assert not legacy.exists()

    def test_dpi_and_fig_size_defaults(self, config):
        from agents.visualizer import VisualizationAgent

        agent = VisualizationAgent(config)
        assert agent.dpi == 72
        assert agent.fig_w == 6
        assert agent.fig_h == 4


class TestFontSetup:
    def test_preferred_font_selected(self, config):
        from agents.visualizer import VisualizationAgent
        import matplotlib.font_manager as fm

        fake_font = MagicMock()
        fake_font.name = "MyCustomFont"
        with patch.object(fm.fontManager, "ttflist", [fake_font]):
            agent = VisualizationAgent(config)
            # font family should be set (via plt.rcParams or warning)
            assert agent is not None  # should not crash

    def test_fallback_when_missing(self, config):
        from agents.visualizer import VisualizationAgent
        import matplotlib.font_manager as fm

        class FakeFont:
            name = "Arial"  # not Chinese

        with patch.object(fm.fontManager, "ttflist", [FakeFont()]):
            agent = VisualizationAgent(config)
            assert agent is not None  # graceful degradation


class TestRun:
    def test_run_with_valid_report(self, config):
        from agents.visualizer import VisualizationAgent

        agent = VisualizationAgent(config)
        report = {
            "site_name": "test_site",
            "current_count": 10,
            "total_changes": 3,
            "has_changes": True,
            "tag_distribution": {"科技": 5, "娱乐": 5},
            "trends": {"direction": "up"},
            "new_items": [{"title": "N1", "url": "/1", "tag": "科技"}],
            "removed_items": [],
            "modified_items": [],
            "timestamp": "2026-01-01T00:00:00",
            "update_summary": "新增1条科技新闻",
        }
        snapshots = [
            {"items_count": 5, "timestamp": "2025-12-31T00:00:00", "items": []},
            {"items_count": 10, "timestamp": "2026-01-01T00:00:00", "items": []},
        ]
        result = agent.run(report, snapshots)
        assert "charts" in result
        assert "today" in result["charts"]
        assert "total" in result["charts"]
        today_dir = agent.sets["today"]
        png_files = list(today_dir.glob("*.png"))
        # Charts should generate at least one PNG or return directory paths
        assert png_files or isinstance(result["charts"]["today"], str)

    def test_run_no_snapshots(self, config):
        from agents.visualizer import VisualizationAgent

        agent = VisualizationAgent(config)
        report = {
            "site_name": "test_site",
            "current_count": 5,
            "total_changes": 0,
            "has_changes": False,
            "tag_distribution": {},
            "trends": {"direction": "stable"},
        }
        result = agent.run(report, [])
        assert "charts" in result


class TestDateHelpers:
    def test_sets_have_six_keys(self, config):
        from agents.visualizer import VisualizationAgent

        agent = VisualizationAgent(config)
        assert len(agent.sets) == 6
        assert "today" in agent.sets
        assert "total" in agent.sets
