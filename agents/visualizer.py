from __future__ import annotations

"""VisualizationAgent: generate static PNG charts with chart retention policy.

Chart sets:
  today/         - Today's latest snapshot, updated every run
  yesterday/     - Yesterday's snapshot, updated when date changes
  two_days_ago/  - Two days ago snapshot, updated when date changes
  one_week_ago/  - Snapshot from ~7 days ago, updated on Sundays
  one_month_ago/ - Snapshot from ~30 days ago, updated on last day of month
  total/         - Aggregate historical trends, updated every run
"""

import logging  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402
from datetime import date  # noqa: E402
from calendar import monthrange  # noqa: E402

from .base_agent import BaseAgent  # noqa: E402

# Heavy imports deferred — matplotlib/numpy load is ~1s and unnecessary
# for tests that only import CoordinatorAgent (which pulls in VisualizerAgent).
_plt = None
_np = None
_fm = None


def _get_plt():
    global _plt, _np, _fm
    if _plt is None:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt_module
        import matplotlib.font_manager as _fm_module
        import numpy as _np_module

        _plt = _plt_module
        _fm = _fm_module
        _np = _np_module
    return _plt, _np, _fm


class _LazyModule:
    """Proxy that defers module import until first attribute access."""

    def __init__(self, loader):
        self._loader = loader
        self._module = None

    def __getattr__(self, name):
        if self._module is None:
            self._module = self._loader()
        return getattr(self._module, name)


plt = _LazyModule(lambda: _get_plt()[0])
np = _LazyModule(lambda: _get_plt()[1])
fm = _LazyModule(lambda: _get_plt()[2])

logger = logging.getLogger(__name__)


class VisualizationAgent(BaseAgent):
    def __init__(self, config: dict):
        super().__init__("Visualizer", config)
        viz_config: dict = config.get("visualization", {})
        self.dpi: int = viz_config.get("dpi", 150)
        self.fig_w: int = viz_config.get("figure_width", 12)
        self.fig_h: int = viz_config.get("figure_height", 8)
        self.base_dir: Path = Path(viz_config.get("output_dir", "outputs/charts"))
        self.sets: dict[str, Path] = {
            "today": self.base_dir / "today",
            "yesterday": self.base_dir / "yesterday",
            "two_days_ago": self.base_dir / "two_days_ago",
            "one_week_ago": self.base_dir / "one_week_ago",
            "one_month_ago": self.base_dir / "one_month_ago",
            "total": self.base_dir / "total",
        }
        # Remove legacy 'current' dir if it exists
        legacy = self.base_dir / "current"
        if legacy.exists():
            shutil.rmtree(legacy)
        for d in self.sets.values():
            d.mkdir(parents=True, exist_ok=True)
        self._setup_font(viz_config.get("font_family", "SimHei"))

    def _setup_font(self, preferred: str) -> None:
        available = {f.name for f in fm.fontManager.ttflist}
        candidates = [
            preferred,
            "SimHei",
            "Microsoft YaHei",
            "WenQuanYi Micro Hei",
            "Noto Sans CJK SC",
            "Source Han Sans SC",
            "Arial Unicode MS",
        ]
        chosen = None
        for font in candidates:
            if font in available:
                chosen = font
                break
        if chosen:
            plt.rcParams["font.family"] = chosen
            plt.rcParams["axes.unicode_minus"] = False
            logger.info("[Visualizer] Using font: %s", chosen)
        else:
            logger.warning("[Visualizer] No Chinese font found.")

    def run(self, report: dict, snapshots: list[dict] | None = None) -> dict[str, str]:
        """Generate charts for today + historical sets."""
        site_name = report.get("site_name", "unknown")
        logger.info("[Visualizer] Generating charts for %s", site_name)

        today = date.today()
        charts = {}

        # 1. Always update 'today' set
        self._generate_set("today", report, snapshots)
        charts["today"] = str(self.sets["today"])

        # 2. Always update 'total' set (aggregate historical)
        self._generate_total_set(report, snapshots)
        charts["total"] = str(self.sets["total"])

        # 3. yesterday / two_days_ago — find snapshots from those dates
        if snapshots and len(snapshots) >= 1:
            # Try yesterday
            yest_snapshots = self._snapshots_up_to(snapshots, today, 1)
            if yest_snapshots:
                yest_report = self._build_report_from_snapshot(
                    yest_snapshots, site_name
                )
                self._generate_set("yesterday", yest_report, yest_snapshots)
                charts["yesterday"] = str(self.sets["yesterday"])
                logger.info("[Visualizer] Updated yesterday snapshot")

            # Try two days ago
            tda_snapshots = self._snapshots_up_to(snapshots, today, 2)
            if tda_snapshots:
                tda_report = self._build_report_from_snapshot(tda_snapshots, site_name)
                self._generate_set("two_days_ago", tda_report, tda_snapshots)
                charts["two_days_ago"] = str(self.sets["two_days_ago"])
                logger.info("[Visualizer] Updated two_days_ago snapshot")

        # 4. Conditionally update week/month sets
        if today.weekday() == 6:  # Sunday
            # Find a snapshot from ~7 days ago
            week_snapshots = (
                self._snapshots_up_to(snapshots, today, 7) if snapshots else None
            )
            if week_snapshots:
                week_report = self._build_report_from_snapshot(
                    week_snapshots, site_name
                )
                self._generate_set("one_week_ago", week_report, week_snapshots)
                charts["one_week_ago"] = str(self.sets["one_week_ago"])
                logger.info("[Visualizer] Updated one_week_ago snapshot (Sunday)")

        last_day = monthrange(today.year, today.month)[1]
        if today.day == last_day:
            month_snapshots = (
                self._snapshots_up_to(snapshots, today, 30) if snapshots else None
            )
            if month_snapshots:
                month_report = self._build_report_from_snapshot(
                    month_snapshots, site_name
                )
                self._generate_set("one_month_ago", month_report, month_snapshots)
                charts["one_month_ago"] = str(self.sets["one_month_ago"])
                logger.info("[Visualizer] Updated one_month_ago snapshot (month end)")

        return {"charts": charts, "output_dir": str(self.base_dir)}

    def _snapshots_up_to(
        self, snapshots: list[dict], ref_date: date, days_back: int
    ) -> list[dict]:
        """Return snapshots up to and including (ref_date - days_back)."""
        from datetime import timedelta

        target_date = (ref_date - timedelta(days=days_back)).isoformat()

        result = []
        for s in snapshots:
            s_date = s.get("timestamp", "")[:10]
            if s_date <= target_date:
                result.append(s)

        return result if result else []

    def _build_report_from_snapshot(
        self, snapshots: list[dict], site_name: str
    ) -> dict:
        """Build a minimal report from the last snapshot in the list."""
        if not snapshots:
            return {"site_name": site_name, "has_changes": False, "is_first_run": True}

        last = snapshots[-1]
        items = last.get("items", [])

        tags = {}
        for item in items:
            t = item.get("tag", "其他")
            tags[t] = tags.get(t, 0) + 1

        return {
            "site_name": site_name,
            "timestamp": last.get("timestamp", ""),
            "content_hash": last.get("content_hash", ""),
            "current_count": len(items),
            "previous_count": 0,
            "new_items": [],
            "removed_items": [],
            "modified_items": [],
            "total_changes": 0,
            "has_changes": False,
            "is_first_run": False,
            "tag_distribution": dict(
                sorted(tags.items(), key=lambda x: x[1], reverse=True)
            ),
            "trends": self._compute_trends_from_snapshots(snapshots),
        }

    def _compute_trends_from_snapshots(self, snapshots: list[dict]) -> dict:
        counts = [s.get("items_count", 0) for s in snapshots]
        times = [s.get("timestamp", "") for s in snapshots]
        if len(counts) < 2:
            return {}
        recent_avg = sum(counts[-3:]) / min(3, len(counts[-3:]))
        older_avg = sum(counts[: max(1, len(counts) - 3)]) / max(1, len(counts) - 3)
        if recent_avg > older_avg * 1.1:
            direction = "up"
        elif recent_avg < older_avg * 0.9:
            direction = "down"
        else:
            direction = "stable"
        return {
            "direction": direction,
            "snapshot_counts": counts,
            "snapshot_times": times,
            "recent_average": round(recent_avg, 1),
            "older_average": round(older_avg, 1),
        }

    def _generate_set(
        self, set_name: str, report: dict, snapshots: list[dict] | None
    ) -> None:
        """Generate a full set of charts into the given set directory."""
        out_dir = self.sets[set_name]
        # Clean and regenerate
        for f in out_dir.glob("*.png"):
            f.unlink()

        prefix = "chart"

        if report.get("tag_distribution"):
            self._tag_pie(report["tag_distribution"], out_dir, prefix)

        if report.get("trends", {}).get("snapshot_counts"):
            self._trend_line(report["trends"], out_dir, prefix)

        if not report.get("is_first_run"):
            self._change_bar(report, out_dir, prefix)

        # New items: dedicated chart with titles, tags, and URLs
        new_items = report.get("new_items", [])
        if new_items:
            new_tag_dist = {}
            for it in new_items:
                t = it.get("tag", "其他") or "其他"
                new_tag_dist[t] = new_tag_dist.get(t, 0) + 1
            self._tag_pie(
                new_tag_dist,
                out_dir,
                "new_items_distribution",
                title="New Items Category Distribution",
            )
            self._new_items_table(new_items, out_dir, prefix)

        # Regular summary table (15 latest items, marking new ones)
        if snapshots:
            items = snapshots[-1].get("items", []) if snapshots else []
            if items:
                new_titles = {it.get("title", "") for it in new_items}
                self._summary_table(items[:15], out_dir, prefix, new_titles=new_titles)

        self._overview_dashboard(report, out_dir, prefix)
        logger.info(
            "[Visualizer] Generated '%s' chart set (%d files)",
            set_name,
            len(list(out_dir.glob("*.png"))),
        )

    def _generate_total_set(self, report: dict, snapshots: list[dict] | None) -> None:
        """Generate aggregate historical charts."""
        out_dir = self.sets["total"]
        for f in out_dir.glob("*.png"):
            f.unlink()

        if not snapshots or len(snapshots) < 2:
            # Not enough history; copy today's overview as placeholder
            src = self.sets["today"] / "chart_overview.png"
            if src.exists():
                shutil.copy(src, out_dir / "chart_overview.png")
            return

        prefix = "total"

        # 1. Historical news volume trend
        self._historical_trend(snapshots, out_dir, prefix)

        # 2. Historical tag evolution (stacked area)
        self._tag_evolution(snapshots, out_dir, prefix)

        # 3. Cumulative overview
        self._cumulative_overview(snapshots, out_dir, prefix)

        logger.info(
            "[Visualizer] Generated 'total' chart set (%d files)",
            len(list(out_dir.glob("*.png"))),
        )

    # ========== Single-snapshot charts ==========

    def _save(self, fig: plt.Figure, name: str, out_dir: Path) -> str:
        filepath = out_dir / f"{name}.png"
        fig.savefig(
            str(filepath),
            dpi=self.dpi,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        plt.close(fig)
        return str(filepath)

    def _tag_pie(
        self, dist: dict[str, int], out_dir: Path, prefix: str, title: str | None = None
    ) -> None:
        fig, ax = plt.subplots(figsize=(self.fig_w, self.fig_h))
        labels = list(dist.keys())
        sizes = list(dist.values())
        colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        wedges, _, autotexts = ax.pie(
            sizes,
            labels=labels,
            autopct="%1.1f%%",
            colors=colors,
            startangle=90,
            pctdistance=0.85,
        )
        for t in autotexts:
            t.set_fontsize(9)
        ax.set_title(
            title or "News Category Distribution",
            fontsize=16,
            fontweight="bold",
            pad=20,
        )
        ax.axis("equal")
        self._save(fig, f"{prefix}_tag_pie", out_dir)

    def _trend_line(self, trends: dict, out_dir: Path, prefix: str) -> None:
        fig, ax = plt.subplots(figsize=(self.fig_w, self.fig_h))
        counts = trends.get("snapshot_counts", [])
        times = trends.get("snapshot_times", [])
        x = list(range(1, len(counts) + 1))
        ax.plot(
            x,
            counts,
            marker="o",
            linewidth=2,
            markersize=8,
            color="#2196F3",
            markerfacecolor="#1565C0",
        )
        if len(counts) >= 2:
            z = np.polyfit(x, counts, 1)
            p = np.poly1d(z)
            ax.plot(x, p(x), "--", color="#FF5722", linewidth=1.5, alpha=0.7)
        for xi, yi in zip(x, counts):
            ax.annotate(
                str(yi),
                (xi, yi),
                textcoords="offset points",
                xytext=(0, 10),
                ha="center",
                fontsize=9,
            )
        ax.set_xlabel("Snapshot #", fontsize=12)
        ax.set_ylabel("News Items Count", fontsize=12)
        ax.set_title("News Volume Trend", fontsize=16, fontweight="bold")
        ax.grid(True, alpha=0.3)
        if times:
            short = [t[:10] if len(t) > 10 else t for t in times]
            ax.set_xticks(x)
            ax.set_xticklabels(short, rotation=45, ha="right", fontsize=8)
        self._save(fig, f"{prefix}_trend_line", out_dir)

    def _change_bar(self, report: dict, out_dir: Path, prefix: str) -> None:
        fig, ax = plt.subplots(figsize=(8, 6))
        categories = ["New", "Removed", "Modified"]
        values = [
            len(report.get("new_items", [])),
            len(report.get("removed_items", [])),
            len(report.get("modified_items", [])),
        ]
        colors = ["#4CAF50", "#F44336", "#FF9800"]
        bars = ax.bar(
            categories,
            values,
            color=colors,
            width=0.5,
            edgecolor="white",
            linewidth=1.2,
        )
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.3,
                str(val),
                ha="center",
                fontsize=14,
                fontweight="bold",
            )
        ax.set_ylabel("Count", fontsize=12)
        ax.set_title(
            "Change Summary: Current vs Previous", fontsize=16, fontweight="bold"
        )
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        self._save(fig, f"{prefix}_change_bar", out_dir)

    def _summary_table(
        self,
        items: list[dict],
        out_dir: Path,
        prefix: str,
        new_titles: set[str] | None = None,
    ) -> None:
        n = len(items)
        new_titles = new_titles or set()
        fig, ax = plt.subplots(figsize=(16, max(5, n * 0.45)))
        ax.axis("off")
        col_labels = ["#", "Title", "Tag", "Source"]
        col_widths = [0.04, 0.50, 0.10, 0.36]
        table_data = []
        for i, item in enumerate(items, 1):
            title = item.get("title", "")[:60]
            tag = item.get("tag", "") or "-"
            url = item.get("url", "") or "-"
            # Prefix new items with a marker
            is_new = title in new_titles
            display_title = f"NEW | {title}" if is_new else title
            if len(url) > 55:
                url = url[:52] + "..."
            table_data.append([str(i), display_title, tag, url])
        table = ax.table(
            cellText=table_data,
            colLabels=col_labels,
            colWidths=col_widths,
            cellLoc="left",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.4)
        for i in range(len(col_labels)):
            cell = table[0, i]
            cell.set_facecolor("#37474F")
            cell.set_text_props(color="white", fontweight="bold")
        for row in range(1, n + 1):
            is_new_row = table_data[row - 1][1].startswith("NEW |")
            for col in range(len(col_labels)):
                if is_new_row:
                    table[row, col].set_facecolor("#E8F5E9")  # green tint for new
                else:
                    table[row, col].set_facecolor(
                        "#F5F5F5" if row % 2 == 0 else "#FFFFFF"
                    )
        new_count = sum(1 for td in table_data if td[1].startswith("NEW |"))
        ax.set_title(
            f"Latest News Headlines ({new_count} new)",
            fontsize=16,
            fontweight="bold",
            pad=20,
        )
        self._save(fig, f"{prefix}_summary_table", out_dir)

    def _new_items_table(
        self, new_items: list[dict], out_dir: Path, prefix: str
    ) -> None:
        """Dedicated table showing only new items with title, tag, and URL."""
        n = min(len(new_items), 30)
        items = new_items[:n]
        fig, ax = plt.subplots(figsize=(16, max(5, n * 0.42)))
        ax.axis("off")
        col_labels = ["#", "Title", "Tag", "URL"]
        col_widths = [0.04, 0.46, 0.10, 0.40]
        table_data = []
        for i, item in enumerate(items, 1):
            title = item.get("title", "")[:70]
            tag = item.get("tag", "") or "-"
            url = item.get("url", "") or "-"
            if len(url) > 60:
                url = url[:57] + "..."
            table_data.append([str(i), title, tag, url])
        table = ax.table(
            cellText=table_data,
            colLabels=col_labels,
            colWidths=col_widths,
            cellLoc="left",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.35)
        for i in range(len(col_labels)):
            cell = table[0, i]
            cell.set_facecolor("#2E7D32")
            cell.set_text_props(color="white", fontweight="bold")
        for row in range(1, n + 1):
            for col in range(len(col_labels)):
                table[row, col].set_facecolor("#F1F8E9" if row % 2 == 0 else "#FFFFFF")
        ax.set_title(
            f"New Items Today ({len(new_items)} total, showing {n})",
            fontsize=16,
            fontweight="bold",
            pad=20,
        )
        self._save(fig, f"{prefix}_new_items", out_dir)

    def _overview_dashboard(self, report: dict, out_dir: Path, prefix: str) -> None:
        has_summary = bool(report.get("update_summary"))
        fig = plt.figure(figsize=(14, 10.5 if has_summary else 10))
        fig.suptitle(
            f"Monitoring: {report.get('site_name', 'Unknown')}",
            fontsize=18,
            fontweight="bold",
            y=0.98,
        )
        gs = fig.add_gridspec(
            2 if not has_summary else 3,
            2,
            hspace=0.35,
            wspace=0.3,
            height_ratios=([1, 1] if not has_summary else [0.4, 1, 1]),
        )

        # LLM summary row (full width) — shown when available
        if has_summary:
            ax_summary = fig.add_subplot(gs[0, :])
            ax_summary.axis("off")
            summary_text = report.get("update_summary", "")
            ax_summary.text(
                0.02,
                0.5,
                f"AI Summary:\n{summary_text}",
                transform=ax_summary.transAxes,
                fontsize=11,
                verticalalignment="center",
                bbox=dict(
                    boxstyle="round",
                    facecolor="#FFF8E1",
                    edgecolor="#FFC107",
                    alpha=0.9,
                ),
            )
            ax_summary.set_title(
                "LLM Analysis", fontsize=14, fontweight="bold", color="#F57F17"
            )

        row_offset = 0 if not has_summary else 1

        ax_stats = fig.add_subplot(gs[row_offset, 0])
        ax_stats.axis("off")
        stats_text = (
            f"Time: {report.get('timestamp', '')[:19]}\n"
            f"Items Found: {report.get('current_count', 0)}\n"
            f"Previous Count: {report.get('previous_count', 0)}\n"
            f"Total Changes: {report.get('total_changes', 0)}\n"
            f"Trend: {report.get('trends', {}).get('direction', 'N/A')}\n"
            f"First Run: {report.get('is_first_run', True)}"
        )
        ax_stats.text(
            0.1,
            0.5,
            stats_text,
            transform=ax_stats.transAxes,
            fontsize=14,
            verticalalignment="center",
            fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="#E3F2FD", alpha=0.8),
        )
        ax_stats.set_title("Run Statistics", fontsize=14, fontweight="bold")

        ax_tag = fig.add_subplot(gs[row_offset, 1])
        dist = report.get("tag_distribution", {})
        if dist:
            labels = list(dist.keys())
            sizes = list(dist.values())
            colors = plt.cm.Pastel1(np.linspace(0, 1, len(labels)))
            ax_tag.pie(
                sizes, labels=labels, autopct="%1.1f%%", colors=colors, startangle=90
            )
            ax_tag.set_title("Category Distribution", fontsize=14, fontweight="bold")

        ax_new = fig.add_subplot(gs[row_offset + 1, 0])
        ax_new.axis("off")
        new_items = report.get("new_items", [])[:8]
        text = (
            "\n".join(f"- {item.get('title', '')[:50]}" for item in new_items)
            if new_items
            else "No new items."
        )
        ax_new.text(
            0.05,
            0.95,
            f"New ({len(report.get('new_items', []))}):\n{text}",
            transform=ax_new.transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="#E8F5E9", alpha=0.8),
        )
        ax_new.set_title("New Content", fontsize=14, fontweight="bold")

        ax_rem = fig.add_subplot(gs[row_offset + 1, 1])
        ax_rem.axis("off")
        removed = report.get("removed_items", [])[:8]
        text = (
            "\n".join(f"- {item.get('title', '')[:50]}" for item in removed)
            if removed
            else "No removed items."
        )
        ax_rem.text(
            0.05,
            0.95,
            f"Removed ({len(report.get('removed_items', []))}):\n{text}",
            transform=ax_rem.transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="#FFEBEE", alpha=0.8),
        )
        ax_rem.set_title("Removed Content", fontsize=14, fontweight="bold")
        self._save(fig, f"{prefix}_overview", out_dir)

    # ========== Historical / Total charts ==========

    def _historical_trend(
        self, snapshots: list[dict], out_dir: Path, prefix: str
    ) -> None:
        """Line chart: news count across all snapshots, with moving average."""
        fig, ax = plt.subplots(figsize=(14, 7))
        counts = [s["items_count"] for s in snapshots]
        times = [s["timestamp"][:10] for s in snapshots]
        x = list(range(1, len(counts) + 1))

        ax.fill_between(x, counts, alpha=0.15, color="#2196F3")
        ax.plot(
            x,
            counts,
            marker="o",
            linewidth=2,
            markersize=6,
            color="#2196F3",
            markerfacecolor="#1565C0",
            label="News Count",
        )

        if len(counts) >= 3:
            window = min(5, len(counts))
            ma = np.convolve(counts, np.ones(window) / window, mode="valid")
            ma_x = list(range(window, len(counts) + 1))
            ax.plot(
                ma_x,
                ma,
                "--",
                linewidth=2,
                color="#FF5722",
                label=f"{window}-point Moving Avg",
            )

        # Annotate first and last
        ax.annotate(
            str(counts[0]),
            (x[0], counts[0]),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            fontsize=10,
        )
        ax.annotate(
            str(counts[-1]),
            (x[-1], counts[-1]),
            textcoords="offset points",
            xytext=(0, 12),
            ha="center",
            fontsize=10,
            fontweight="bold",
            color="#1565C0",
        )

        ax.set_xlabel("Snapshot", fontsize=12)
        ax.set_ylabel("Items Count", fontsize=12)
        ax.set_title(
            f"Historical Trend ({len(snapshots)} snapshots, {times[0]} ~ {times[-1]})",
            fontsize=15,
            fontweight="bold",
        )
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
        if len(times) <= 20:
            ax.set_xticks(x)
            ax.set_xticklabels(times, rotation=45, ha="right", fontsize=8)
        self._save(fig, f"{prefix}_historical_trend", out_dir)

    def _tag_evolution(self, snapshots: list[dict], out_dir: Path, prefix: str) -> None:
        """Stacked area chart: tag distribution evolution over time."""
        # Collect all tags across all snapshots
        all_tags = set()
        for s in snapshots:
            for item in s.get("items", []):
                all_tags.add(item.get("tag", "其他"))
        all_tags = sorted(all_tags)

        if len(all_tags) <= 1 or len(snapshots) < 2:
            return

        times = [s["timestamp"][:10] for s in snapshots]
        x = list(range(len(snapshots)))

        # Build stacked data
        tag_data = {tag: [] for tag in all_tags}
        for s in snapshots:
            counts = {}
            for item in s.get("items", []):
                tag = item.get("tag", "其他")
                counts[tag] = counts.get(tag, 0) + 1
            total = sum(counts.values()) or 1
            for tag in all_tags:
                tag_data[tag].append(counts.get(tag, 0) / total * 100)

        fig, ax = plt.subplots(figsize=(14, 7))
        colors = plt.cm.tab10(np.linspace(0, 1, len(all_tags)))
        ax.stackplot(x, *tag_data.values(), labels=all_tags, colors=colors, alpha=0.8)

        ax.set_xlabel("Snapshot", fontsize=12)
        ax.set_ylabel("Percentage (%)", fontsize=12)
        ax.set_title("Category Distribution Over Time", fontsize=15, fontweight="bold")
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9)
        ax.grid(True, alpha=0.3)
        if len(times) <= 20:
            ax.set_xticks(x)
            ax.set_xticklabels(times, rotation=45, ha="right", fontsize=8)
        self._save(fig, f"{prefix}_tag_evolution", out_dir)

    def _cumulative_overview(
        self, snapshots: list[dict], out_dir: Path, prefix: str
    ) -> None:
        """Summary stats across all history."""
        fig = plt.figure(figsize=(14, 8))
        fig.suptitle("Cumulative Monitoring Summary", fontsize=18, fontweight="bold")

        total_items = sum(s["items_count"] for s in snapshots)
        first_ts = snapshots[0]["timestamp"][:19]
        last_ts = snapshots[-1]["timestamp"][:19]
        avg_items = total_items / len(snapshots) if snapshots else 0

        # Collect all tags across history
        all_tags = {}
        for s in snapshots:
            for item in s.get("items", []):
                tag = item.get("tag", "其他")
                all_tags[tag] = all_tags.get(tag, 0) + 1

        gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.3)

        # Stats panel
        ax_stats = fig.add_subplot(gs[0, 0])
        ax_stats.axis("off")
        text = (
            f"Monitoring Period:\n  {first_ts}\n  ~ {last_ts}\n\n"
            f"Total Snapshots: {len(snapshots)}\n"
            f"Total Items Collected: {total_items}\n"
            f"Avg Items per Snapshot: {avg_items:.1f}\n"
            f"Unique Tags: {len(all_tags)}"
        )
        ax_stats.text(
            0.1,
            0.5,
            text,
            transform=ax_stats.transAxes,
            fontsize=13,
            verticalalignment="center",
            fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="#E3F2FD", alpha=0.8),
        )
        ax_stats.set_title("Cumulative Statistics", fontsize=14, fontweight="bold")

        # Tag totals pie
        ax_pie = fig.add_subplot(gs[0, 1])
        if all_tags:
            labels = list(all_tags.keys())
            sizes = list(all_tags.values())
            colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
            ax_pie.pie(
                sizes, labels=labels, autopct="%1.1f%%", colors=colors, startangle=90
            )
            ax_pie.set_title(
                f"All-Time Tag Distribution ({total_items} items)",
                fontsize=14,
                fontweight="bold",
            )

        # Items per snapshot bar chart
        ax_bar = fig.add_subplot(gs[1, :])
        counts = [s["items_count"] for s in snapshots]
        times = [s["timestamp"][:10] for s in snapshots]
        x = list(range(len(snapshots)))
        ax_bar.bar(x, counts, color="#42A5F5", edgecolor="white")
        ax_bar.axhline(
            y=avg_items,
            color="#FF5722",
            linestyle="--",
            linewidth=1.5,
            label=f"Average: {avg_items:.1f}",
        )
        ax_bar.set_xlabel("Snapshot", fontsize=12)
        ax_bar.set_ylabel("Items", fontsize=12)
        ax_bar.set_title("Items per Snapshot", fontsize=14, fontweight="bold")
        ax_bar.legend(fontsize=10)
        if len(times) <= 20:
            ax_bar.set_xticks(x)
            ax_bar.set_xticklabels(times, rotation=45, ha="right", fontsize=8)

        self._save(fig, f"{prefix}_cumulative_overview", out_dir)
