"""Stateless preference utility functions extracted from ChatAgent."""

from datetime import datetime


def now_iso() -> str:
    return datetime.now().isoformat()


def decay_weight(entry, halflife_days: int = 14) -> float:
    """Apply exponential time decay: count * 0.5^(days / halflife)."""
    if isinstance(entry, (int, float)):
        count = float(entry)
        days = 0  # legacy format — no timestamp, treat as fresh
    elif isinstance(entry, dict):
        count = float(entry.get("count", 0))
        try:
            ts = entry.get("last_ts", "")
            if ts:
                dt = datetime.fromisoformat(ts)
                days = (datetime.now() - dt).total_seconds() / 86400
            else:
                days = 0
        except (ValueError, TypeError):
            days = 0
    else:
        return 0.0
    return round(count * (0.5 ** (days / max(halflife_days, 1))), 2)


def bump_signal(signals_dict: dict, key: str) -> None:
    """Increment a signal counter with timestamp. Migrates legacy int format."""
    entry = signals_dict.get(key)
    if isinstance(entry, dict):
        entry["count"] = entry.get("count", 0) + 1
        entry["last_ts"] = now_iso()
    else:
        signals_dict[key] = {
            "count": (int(entry) if entry else 0) + 1,
            "last_ts": now_iso(),
        }


def confidence_label(conf: float) -> str:
    if conf >= 0.8:
        return "高"
    if conf >= 0.5:
        return "中"
    return "低"
