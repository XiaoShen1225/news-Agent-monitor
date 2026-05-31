"""Rule-based Chinese sentiment analyzer for news titles.

Uses lightweight lexicon matching — no LLM dependency, runs in microseconds.
"""

import logging

logger = logging.getLogger(__name__)

# ── Chinese sentiment lexicon (~200 high-frequency words) ──────────────
# Positive words: growth, breakthrough, innovation, cooperation, etc.
POSITIVE_WORDS = {
    "上涨",
    "增长",
    "突破",
    "创新",
    "合作",
    "成功",
    "提升",
    "利好",
    "回暖",
    "复苏",
    "夺冠",
    "获奖",
    "首发",
    "领先",
    "优化",
    "改善",
    "推进",
    "落地",
    "签约",
    "融资",
    "上市",
    "盈利",
    "分红",
    "获批",
    "表彰",
    "点赞",
    "惠民",
    "减税",
    "升级",
    "加速",
    "翻倍",
    "新高",
    "强劲",
    "繁荣",
    "稳定",
    "和平",
    "安全",
    "保障",
    "治愈",
    "康复",
    "竣工",
    "通车",
    "开通",
    "启用",
    "发射",
    "圆满",
    "胜利",
    "辉煌",
    "荣耀",
    "赞扬",
    "支持",
    "鼓励",
    "扶持",
    "补贴",
    "红利",
    "机遇",
    "崛起",
    "腾飞",
    "超越",
    "夺冠",
    "金牌",
    "冠军",
    "第一",
    "签署",
    "共建",
    "共享",
    "共赢",
    "协作",
    "携手",
    "助力",
    "赋能",
    "振兴",
    "脱贫",
    "致富",
    "普惠",
    "便捷",
    "高效",
    "智能",
    "绿色",
    "低碳",
    "环保",
    "可持续",
    "新质生产力",
}

NEGATIVE_WORDS = {
    "下跌",
    "暴跌",
    "下滑",
    "下降",
    "亏损",
    "倒闭",
    "裁员",
    "违法",
    "犯罪",
    "处罚",
    "罚款",
    "调查",
    "拘留",
    "逮捕",
    "事故",
    "爆炸",
    "火灾",
    "地震",
    "洪水",
    "灾害",
    "灾难",
    "冲突",
    "战争",
    "袭击",
    "恐怖",
    "伤亡",
    "死亡",
    "遇难",
    "抗议",
    "示威",
    "骚乱",
    "暴乱",
    "危机",
    "崩溃",
    "衰退",
    "污染",
    "泄露",
    "超标",
    "致癌",
    "有毒",
    "违规",
    "造假",
    "欺诈",
    "腐败",
    "贪污",
    "受贿",
    "滥用",
    "失职",
    "渎职",
    "受伤",
    "失踪",
    "被困",
    "倒塌",
    "坠毁",
    "沉没",
    "故障",
    "停飞",
    "停运",
    "停牌",
    "退市",
    "违约",
    "爆雷",
    "债务",
    "危机",
    "紧张",
    "恶化",
    "制裁",
    "封锁",
    "限制",
    "断交",
    "谴责",
    "抗议",
    "警告",
    "威胁",
    "挑衅",
    "侵犯",
    "干涉",
    "分裂",
    "动荡",
    "混乱",
    "恐慌",
    "抢购",
    "囤积",
    "涨价",
    "失业",
    "贫困",
    "饥饿",
    "疫情",
    "病毒",
    "感染",
    "确诊",
    "歧视",
    "霸凌",
    "虐待",
    "暴力",
    "枪击",
    "刺杀",
    "绑架",
    "黑客",
    "攻击",
    "泄露",
    "入侵",
    "瘫痪",
    "崩溃",
    "异常",
}

# Intensity modifiers that amplify or flip sentiment
NEGATION_WORDS = {
    "不",
    "没",
    "无",
    "未",
    "否",
    "非",
    "别",
    "莫",
    "勿",
    "杜绝",
    "避免",
    "防止",
}
AMPLIFIERS = {"大幅", "急剧", "严重", "剧烈", "极度", "极其", "最", "创纪录", "历史"}


def classify(title: str) -> str:
    """Classify a Chinese title as 'positive', 'negative', or 'neutral'.

    Returns one of: "positive", "negative", "neutral".
    """
    if not title:
        return "neutral"

    pos_score = _count_matches(title, POSITIVE_WORDS)
    neg_score = _count_matches(title, NEGATIVE_WORDS)

    # Apply amplifier bonus
    has_amplifier = any(w in title for w in AMPLIFIERS)
    if has_amplifier:
        if pos_score > neg_score:
            pos_score += 1
        elif neg_score > pos_score:
            neg_score += 1

    # Check negation: "避免事故" should be positive not negative
    has_negation = any(w in title for w in NEGATION_WORDS)
    if has_negation and neg_score > 0:
        # Negation before a negative word → could be good news
        neg_score = max(0, neg_score - 1)
        pos_score += 0.5

    if pos_score > neg_score:
        return "positive"
    elif neg_score > pos_score:
        return "negative"
    return "neutral"


def _count_matches(text: str, word_set: set) -> float:
    """Count how many lexicon words appear in text. Returns float for partial scores."""
    count = 0.0
    for w in word_set:
        if w in text:
            count += 1.0
    return count
