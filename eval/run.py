"""Offline evaluation runner — dataset-driven LLM-as-Judge quality assessment.

Usage:
    python -m eval.run                    # evaluate default dataset
    python -m eval.run --dataset default  # same
    python -m eval.run --list             # list available datasets
"""

import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"
RESULTS_DIR = Path(__file__).parent / "results"


def load_dataset(name: str) -> list[dict]:
    path = DATASETS_DIR / f"{name}.json"
    if not path.exists():
        print(f"Dataset '{name}' not found at {path}")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def list_datasets():
    for f in sorted(DATASETS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        print(f"  {f.stem} — {len(data)} cases")


async def run_evaluation(dataset_name: str, config: dict):
    from eval.judge import EvalJudge

    cases = load_dataset(dataset_name)
    if not cases:
        print(f"Dataset '{dataset_name}' is empty.")
        return

    judge = EvalJudge(config)
    scores = await judge.evaluate_batch(cases)

    # Merge with original cases for richer reporting
    results = []
    for case, score in zip(cases, scores["details"]):
        entry = {**case, "score": score}
        results.append(entry)

    # Group by category
    by_category = defaultdict(list)
    for r in results:
        cat = r.get("category", "unknown")
        by_category[cat].append(r)

    # Print report
    print(f"\n{'=' * 60}")
    print(f"  Evaluation Report: {dataset_name} ({len(cases)} cases)")
    print(f"{'=' * 60}")
    print(f"  Overall faithfulness: {scores['avg_faithfulness']}")
    print(f"  Overall relevance:    {scores['avg_relevance']}")
    print()

    for cat, items in sorted(by_category.items()):
        valid = [i["score"] for i in items if not i["score"].get("error")]
        if not valid:
            continue
        avg_f = sum(s["faithfulness"] for s in valid) / len(valid)
        avg_r = sum(s["relevance"] for s in valid) / len(valid)
        print(
            f"  [{cat}] {len(valid)} cases — faithfulness {avg_f:.1f}, relevance {avg_r:.1f}"
        )

    # Flag failing cases
    failing = [
        r
        for r in results
        if not r["score"].get("error")
        and (
            r["score"]["faithfulness"] < r.get("min_faithfulness", 0)
            or r["score"]["relevance"] < r.get("min_relevance", 0)
        )
    ]
    if failing:
        print(f"\n  ⚠ {len(failing)} case(s) below threshold:")
        for r in failing:
            s = r["score"]
            print(
                f"    [{r['id']}] faithfulness={s['faithfulness']} "
                f"(min {r.get('min_faithfulness', '?')}), "
                f"relevance={s['relevance']} "
                f"(min {r.get('min_relevance', '?')}) — {s.get('reason', '')}"
            )

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{dataset_name}_result.json"
    out_path.write_text(
        json.dumps(
            {
                "dataset": dataset_name,
                "total": scores["total"],
                "evaluated": scores.get("evaluated", 0),
                "avg_faithfulness": scores["avg_faithfulness"],
                "avg_relevance": scores["avg_relevance"],
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  Results saved to: {out_path}")

    await judge.aclose()
    return scores


async def main():
    parser = argparse.ArgumentParser(description="LLM output quality evaluator")
    parser.add_argument(
        "--dataset", type=str, default="default", help="Dataset name to evaluate"
    )
    parser.add_argument("--list", action="store_true", help="List available datasets")
    args = parser.parse_args()

    if args.list:
        print("Available datasets:")
        list_datasets()
        return

    from main import load_config

    config = load_config()

    await run_evaluation(args.dataset, config)


if __name__ == "__main__":
    asyncio.run(main())
