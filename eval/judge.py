"""LLM output quality evaluator — offline tool, not run in pipeline.

Usage:
    python -m eval.judge --site baidu_news --limit 5
    python -m eval.judge --chat  # Evaluate recent chat replies
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JUDGE_PROMPT = """你是一个 AI 输出质量评估专家。请对以下 AI 回复进行评分。

评分维度（1-5 分，整数）：
- faithfulness: 回复内容是否忠实于给定的上下文/数据？是否没有任何编造或幻觉？
- relevance: 回复是否直接、完整地回答了用户的问题或任务？

请严格以 JSON 格式输出评分，不要包含其他文字：
{"faithfulness": 4, "relevance": 5, "reason": "一句话简要说明扣分原因或好评理由"}"""


class EvalJudge:
    """Call LLM to rate faithfulness and relevance of AI responses."""

    def __init__(self, config: dict):
        from agents.provider_factory import create_provider

        self.provider = create_provider(config)

    async def evaluate(self, question: str, context: str, response: str) -> dict:
        """Score a single (question, context, response) triple."""
        user_prompt = (
            f"用户问题/任务: {question}\n\n"
            f"上下文/数据: {context}\n\n"
            f"AI 回复: {response}"
        )
        try:
            result = await self.provider.chat(
                messages=[
                    {"role": "system", "content": JUDGE_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=128,
                timeout=20.0,
            )
            return self._parse_score(result.content or "")
        except Exception as e:
            logger.warning("EvalJudge failed: %s", e)
            return {"faithfulness": 0, "relevance": 0, "reason": str(e), "error": True}

    def _parse_score(self, text: str) -> dict:
        """Extract JSON score from LLM response, with fallback."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{[^}]+\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {"faithfulness": 0, "relevance": 0, "reason": f"解析失败: {text[:100]}"}

    async def evaluate_batch(self, cases: list[dict]) -> dict:
        """Evaluate multiple cases concurrently, return summary."""
        tasks = [
            self.evaluate(c["question"], c.get("context", ""), c["response"])
            for c in cases
        ]
        scores = await asyncio.gather(*tasks)

        valid = [s for s in scores if not s.get("error")]
        if not valid:
            return {
                "total": len(cases),
                "avg_faithfulness": 0,
                "avg_relevance": 0,
                "details": scores,
            }

        return {
            "total": len(cases),
            "evaluated": len(valid),
            "avg_faithfulness": round(
                sum(s["faithfulness"] for s in valid) / len(valid), 2
            ),
            "avg_relevance": round(sum(s["relevance"] for s in valid) / len(valid), 2),
            "details": scores,
        }

    async def aclose(self):
        await self.provider.close()


async def evaluate_analyzer_summaries(config: dict, site: str, limit: int):
    """Evaluate analyzer update_summary quality for a given site."""
    from data.store import DataStore

    storage = config.get("storage", {})
    store = DataStore(
        history_dir=storage.get("history_dir"),
        db_path=storage.get("db_path"),
    )

    judge = EvalJudge(config)

    meta = store.get_metadata(site)
    if not meta or not meta.get("latest_update_summary"):
        print(f"站点 {site} 暂无 update_summary 数据。")
        await judge.aclose()
        return

    summary = meta["latest_update_summary"]
    changes = meta.get("latest_changes", {})
    context = json.dumps(changes, ensure_ascii=False)

    score = await judge.evaluate(
        question=f"为站点 {site} 的最新变更生成中文摘要",
        context=f"变更数据: {context}",
        response=summary,
    )

    print(f"\n站点: {site}")
    print(f"  faithfulness: {score.get('faithfulness', 'N/A')}")
    print(f"  relevance:    {score.get('relevance', 'N/A')}")
    print(f"  reason:       {score.get('reason', 'N/A')}")
    print(f"  摘要内容:     {summary[:120]}...")

    await judge.aclose()


async def evaluate_chat_replies(config: dict, limit: int):
    """Evaluate recent ChatAgent replies (placeholder — requires chat history storage)."""
    print(
        "Chat reply evaluation requires chat history persistence (not yet implemented)."
    )
    print("Skipping chat evaluation.")


async def main():
    parser = argparse.ArgumentParser(description="LLM output quality evaluator")
    parser.add_argument(
        "--site",
        type=str,
        default="baidu_news",
        help="Site name for analyzer evaluation",
    )
    parser.add_argument("--limit", type=int, default=5, help="Max cases to evaluate")
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Evaluate chat replies instead of analyzer summaries",
    )
    args = parser.parse_args()

    import yaml

    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        print("config.yaml not found. Run from project root.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolve env vars in config
    for key, val in config.get("llm", {}).items():
        if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
            import os

            env_var = val[2:-1]
            config["llm"][key] = os.environ.get(env_var, "")

    if args.chat:
        await evaluate_chat_replies(config, args.limit)
    else:
        await evaluate_analyzer_summaries(config, args.site, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
