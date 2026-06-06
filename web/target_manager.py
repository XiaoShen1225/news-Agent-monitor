"""Federated target source: built-in (config.yaml) + user (DB)."""

from __future__ import annotations

import json
import logging
from typing import Any

from agents.site_profiles import SiteProfile, get_profile

logger = logging.getLogger(__name__)

TARGET_KEYS = [
    "name",
    "url",
    "interval_minutes",
    "use_browser",
    "strategy",
    "profile_json",
    "is_article_source",
    "enabled",
    "created_at",
    "updated_at",
]


class TargetManager:
    """Unifies built-in targets from config.yaml with user targets from DB."""

    def __init__(self, config: dict, data_store: Any):
        self._builtin = [
            {
                "name": t["name"],
                "url": t["url"],
                "interval_minutes": t.get("interval_minutes", 60),
                "use_browser": t.get("use_browser", False),
                "strategy": self._strategy_from_builtin(t["name"]),
                "profile_json": "{}",
                "is_article_source": get_profile(t["name"]).is_article_source,
                "enabled": True,
                "source": "builtin",
                "created_at": "",
                "updated_at": "",
            }
            for t in config.get("targets", [])
        ]
        self._store = data_store

    @staticmethod
    def _strategy_from_builtin(site_name: str) -> str:
        profile = get_profile(site_name)
        return profile.strategy if profile else "css_selector"

    # ── Query ───────────────────────────────────────────────────────

    def all_targets(self) -> list[dict]:
        """Merge built-in and user targets, user overriding built-in by name."""
        user_targets = self._store.list_user_targets(enabled_only=False)
        user_map = {t["name"]: t for t in user_targets}
        merged = {}
        for t in self._builtin:
            name = t["name"]
            if name in user_map:
                t2 = dict(t)
                ut = user_map[name]
                t2.update({k: ut[k] for k in TARGET_KEYS if k in ut})
                t2["source"] = "user"
                merged[name] = t2
            else:
                merged[name] = dict(t)
        for ut in user_targets:
            if ut["name"] not in merged:
                t = dict(ut)
                t["source"] = "user"
                merged[ut["name"]] = t
        return list(merged.values())

    def is_builtin(self, site_name: str) -> bool:
        return any(t["name"] == site_name for t in self._builtin)

    def get_profile(self, site_name: str) -> SiteProfile:
        builtin = get_profile(site_name)
        ut = self._store.get_user_target(site_name)
        if not ut:
            return builtin
        # Merge user target data: strategy + is_article_source from DB,
        # plus optional custom selectors from profile_json
        overrides = {}
        try:
            overrides = json.loads(ut.get("profile_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass
        strategy = ut.get("strategy") or builtin.strategy
        is_article = bool(ut.get("is_article_source", False))
        if overrides:
            overrides.setdefault("strategy", strategy)
            overrides.setdefault("is_article_source", is_article)
            return SiteProfile.from_dict(overrides)
        return SiteProfile(
            name=site_name,
            display_name=site_name,
            strategy=strategy,
            is_article_source=is_article or builtin.is_article_source,
        )

    def get_paper_source_names(self) -> set[str]:
        return {t["name"] for t in self.all_targets() if t.get("is_article_source")}

    def is_article_site(self, site_name: str) -> bool:
        return site_name in self.get_paper_source_names()

    # ── Mutation ────────────────────────────────────────────────────

    def add_target(self, **fields) -> dict:
        site_name = fields.get("site_name", "").strip()
        url = fields.get("url", "").strip()
        if not site_name or not url:
            raise ValueError("site_name and url are required")
        return self._store.add_user_target(
            site_name=site_name,
            url=url,
            interval_minutes=fields.get("interval_minutes", 60),
            use_browser=fields.get("use_browser", False),
            extraction_strategy=fields.get("extraction_strategy", "auto"),
            profile_json=json.dumps(fields.get("profile", {}))
            if isinstance(fields.get("profile"), dict)
            else fields.get("profile_json", "{}"),
            is_article_source=fields.get("is_article_source", False),
        )

    def remove_target(self, site_name: str) -> bool:
        return self._store.remove_user_target(site_name)

    def update_target(self, site_name: str, **fields) -> bool:
        return self._store.update_user_target(site_name, **fields)

    def toggle_target(self, site_name: str, enabled: bool) -> bool:
        return self._store.toggle_user_target(site_name, enabled)
