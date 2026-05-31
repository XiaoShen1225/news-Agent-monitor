"""Tests for SentimentAnalyzer — rule-based Chinese sentiment classification."""

from agents.sentiment_analyzer import classify


class TestClassify:
    def test_positive_title(self):
        assert classify("华为科技创新领先全球") == "positive"
        assert classify("中国经济强劲复苏增长") == "positive"
        assert classify("中国队夺冠获得金牌") == "positive"

    def test_negative_title(self):
        assert classify("股市暴跌投资者恐慌") == "negative"
        assert classify("某地发生严重交通事故") == "negative"
        assert classify("黑客攻击导致系统瘫痪") == "negative"

    def test_neutral_title(self):
        assert classify("今天天气多云转晴") == "neutral"
        assert classify("市政府召开工作会议") == "neutral"
        assert classify("某公司发布年度财报") == "neutral"

    def test_empty_title(self):
        assert classify("") == "neutral"

    def test_amplifier_intensifies(self):
        # Strongly negative word with amplifier
        assert classify("创纪录暴跌引发市场恐慌") == "negative"
        # Strongly positive with amplifier
        assert classify("历史新高经济增长创新高") == "positive"

    def test_mixed_sentiment_picks_stronger(self):
        # "突破" is positive, "危机" is negative — should pick based on count
        assert classify("突破危机实现增长") == "positive"  # 2 positive vs 1 negative

    def test_return_type(self):
        r = classify("任意文本")
        assert r in ("positive", "negative", "neutral")
