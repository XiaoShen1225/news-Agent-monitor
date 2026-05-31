"""Tests for BaseAgent JSON parsing and fallback logic."""

import pytest
from agents.base_agent import BaseAgent


@pytest.fixture
def agent():
    config = {"llm": {"api_key": "test", "model": "glm-4-flash"}}
    return BaseAgent("TestAgent", config)


class TestJsonParsing:
    def test_valid_json_array(self, agent):
        result = agent.parse_json_response('[{"a": 1}, {"b": 2}]')
        assert result == [{"a": 1}, {"b": 2}]

    def test_markdown_code_fence(self, agent):
        result = agent.parse_json_response('```json\n[{"x": "y"}]\n```')
        assert result == [{"x": "y"}]

    def test_trailing_comma(self, agent):
        result = agent.parse_json_response('[{"a": 1,}]')
        assert result == [{"a": 1}]

    def test_surrounded_noise(self, agent):
        result = agent.parse_json_response('some text [{"k": "v"}] extra')
        assert result == [{"k": "v"}]

    def test_single_object(self, agent):
        # Single JSON object is wrapped in a list
        result = agent.parse_json_response('{"name": "test"}')
        assert result == [{"name": "test"}]

    def test_multiple_objects_no_array(self, agent):
        # The regex fallback (Attempt 5) extracts flat JSON objects
        result = agent.parse_json_response('{"a": 1}\n{"b": 2}')
        assert len(result) >= 1
        assert result[0] == {"a": 1}

    def test_truncated_array(self, agent):
        result = agent.parse_json_response('[{"a": 1}, {"b": 2}')
        assert result == [{"a": 1}, {"b": 2}]

    def test_nested_object_valid_json(self, agent):
        # Single nested JSON object is wrapped in a list
        result = agent.parse_json_response('{"a": {"b": 1}}')
        assert result == [{"a": {"b": 1}}]

    def test_empty_raises(self, agent):
        with pytest.raises(ValueError):
            agent.parse_json_response("not json")


class TestBaseAgentInit:
    def test_client_lazy_init(self, agent):
        assert agent._provider is None

    def test_name_and_config(self, agent):
        assert agent.name == "TestAgent"
        assert agent.llm_config["model"] == "glm-4-flash"
