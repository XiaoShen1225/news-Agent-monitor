"""Tests for EvalJudge: score parsing, batch evaluation."""

import pytest
from eval.judge import EvalJudge


@pytest.fixture
def judge():
    config = {"llm": {"api_key": "test", "model": "glm-4-flash"}}
    return EvalJudge(config)


class TestParseScore:
    def test_valid_json(self, judge):
        result = judge._parse_score(
            '{"faithfulness": 4, "relevance": 5, "reason": "准确完整"}'
        )
        assert result["faithfulness"] == 4
        assert result["relevance"] == 5
        assert result["reason"] == "准确完整"

    def test_json_with_extra_text(self, judge):
        result = judge._parse_score(
            '评分如下：{"faithfulness": 3, "relevance": 4, "reason": "部分编造"}'
        )
        assert result["faithfulness"] == 3
        assert result["relevance"] == 4

    def test_invalid_response(self, judge):
        result = judge._parse_score("这不是有效的 JSON 回复")
        assert result["faithfulness"] == 0
        assert result["relevance"] == 0

    def test_empty_response(self, judge):
        result = judge._parse_score("")
        assert result["faithfulness"] == 0
        assert result["relevance"] == 0
