"""Site profiles: per-site extraction rules for multi-source news parsing."""

from dataclasses import dataclass, field
from typing import Optional

# ── built-in profiles ──────────────────────────────────────────────


@dataclass
class SiteProfile:
    name: str
    display_name: str
    domain_patterns: list[str] = field(default_factory=list)
    use_browser: bool = False

    # extraction strategy: "section_walk" | "css_selector" | "llm" | "rss"
    strategy: str = "section_walk"

    # ── section_walk params ──
    section_map: dict = field(default_factory=dict)
    noise_patterns: list[str] = field(default_factory=list)
    ui_labels: set[str] = field(default_factory=set)
    section_max_len: int = 6

    # ── css_selector params ──
    article_selector: str = ""
    title_selector: str = "a"
    link_attr: str = "href"
    tag_from: str = "fixed"  # "fixed" | "selector" | "url"
    fixed_tag: str = "新闻"
    tag_selector: str = ""

    # ── llm strategy params ──
    llm_tag_candidates: list[str] = field(default_factory=list)

    # ── rss strategy params ──
    rss_item_tag: str = "item"  # "item" for RSS 2.0, "entry" for Atom
    rss_title_tag: str = "title"
    rss_link_tag: str = "link"
    rss_summary_tag: str = "description"  # "summary" for Atom
    rss_date_tag: str = "pubDate"  # "published" or "updated" for Atom

    # ── common ──
    min_title_len: int = 6
    max_title_len: int = 200

    # ── article mode (papers) ──
    is_article_source: bool = False  # True = treat as paper/article, skip news analytics

    @classmethod
    def from_dict(cls, data: dict) -> "SiteProfile":
        return cls(
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            domain_patterns=data.get("domain_patterns", []),
            use_browser=data.get("use_browser", False),
            strategy=data.get("strategy", "section_walk"),
            section_map=data.get("section_map", {}),
            noise_patterns=data.get("noise_patterns", []),
            ui_labels=set(data.get("ui_labels", [])),
            section_max_len=data.get("section_max_len", 6),
            article_selector=data.get("article_selector", ""),
            title_selector=data.get("title_selector", "a"),
            link_attr=data.get("link_attr", "href"),
            tag_from=data.get("tag_from", "fixed"),
            fixed_tag=data.get("fixed_tag", "新闻"),
            tag_selector=data.get("tag_selector", ""),
            llm_tag_candidates=data.get("llm_tag_candidates", []),
            rss_item_tag=data.get("rss_item_tag", "item"),
            rss_title_tag=data.get("rss_title_tag", "title"),
            rss_link_tag=data.get("rss_link_tag", "link"),
            rss_summary_tag=data.get("rss_summary_tag", "description"),
            rss_date_tag=data.get("rss_date_tag", "pubDate"),
            min_title_len=data.get("min_title_len", 6),
            max_title_len=data.get("max_title_len", 200),
            is_article_source=data.get("is_article_source", False),
        )


# ── built-in profiles ──────────────────────────────────────────────

BAIDU_NEWS = SiteProfile(
    name="baidu_news",
    display_name="百度新闻",
    domain_patterns=["news.baidu.com", "baidu.com"],
    use_browser=True,
    strategy="section_walk",
    section_map={
        "热点": "要闻", "要闻": "要闻", "热榜": "热榜",
        "北京": "本地", "上海": "本地", "广东": "本地", "深圳": "本地", "本地": "本地",
        "国内": "国内", "国际": "国际", "军事": "军事",
        "财经": "财经", "娱乐": "娱乐", "体育": "体育",
        "科技": "科技", "互联网": "科技", "游戏": "游戏",
        "女人": "女性", "汽车": "汽车", "房产": "房产",
        "教育": "教育", "健康": "健康",
        "视频": "视频", "图片": "图片",
        "推荐": "推荐", "精选": "精选",
        "专题": "专题", "探索": "探索",
        "明星": "娱乐", "NBA": "体育", "中国军情": "军事",
    },
    noise_patterns=[
        r"^加载中", r"^正在加载", r"^点击刷新",
        r"^\d+$", r"^HOT WORDS$",
        r"^百度", r"^更多", r"^图文资讯",
        r"^新闻图片", r"^热门点击",
        r"^用户协议", r"^隐私策略", r"^营业执照",
        r"^京ICP", r"^京公网",
        r"辟谣平台$", r"举报中心",
        r"^切换城市", r"^热搜新闻词",
        r"^互联网新闻信息服务许可", r"^互联网宗教信息服务许可证",
        r"^随时随地收看更多新闻", r"版下载$",
    ],
    ui_labels={
        "首页", "登录", "注册", "帮助", "新闻全文", "新闻标题", "更多", "收起",
        "返回", "用户协议", "隐私策略", "营业执照", "收藏本站", "用户反馈",
        "辅助模式", "扫描二维码", "使用百度前必读", "百度新闻客户端",
    },
    section_max_len=6,
)

SINA_NEWS = SiteProfile(
    name="sina_news",
    display_name="新浪新闻",
    domain_patterns=["news.sina.com.cn", "sina.com.cn"],
    use_browser=False,
    strategy="llm",
    min_title_len=4,
    llm_tag_candidates=[
        "国内", "国际", "军事", "财经", "科技", "体育", "娱乐",
        "社会", "教育", "健康", "汽车", "房产", "游戏", "女性",
    ],
    noise_patterns=[
        r"^加载中", r"^广告", r"^\d+$",
        r"^新浪", r"^微博", r"^登录",
    ],
)

# ── Article / Paper sources (RSS feeds) ─────────────────────────────

DEEPMIND_BLOG = SiteProfile(
    name="deepmind_blog",
    display_name="DeepMind Blog",
    domain_patterns=["deepmind.google", "blog.google"],
    use_browser=False,
    strategy="rss",
    is_article_source=True,
    fixed_tag="AI研究",
    min_title_len=2,
    rss_item_tag="item",
    rss_title_tag="title",
    rss_link_tag="link",
    rss_summary_tag="description",
    rss_date_tag="pubDate",
)

OPENAI_BLOG = SiteProfile(
    name="openai_blog",
    display_name="OpenAI Blog",
    domain_patterns=["openai.com"],
    use_browser=False,
    strategy="rss",
    is_article_source=True,
    fixed_tag="AI研究",
    min_title_len=2,
    rss_item_tag="item",
    rss_title_tag="title",
    rss_link_tag="link",
    rss_summary_tag="description",
    rss_date_tag="pubDate",
)

GOOGLE_AI_BLOG = SiteProfile(
    name="google_ai_blog",
    display_name="Google AI Blog",
    domain_patterns=["ai.googleblog.com", "blogger.com", "blogspot.com"],
    use_browser=False,
    strategy="rss",
    is_article_source=True,
    fixed_tag="AI研究",
    min_title_len=2,
    rss_item_tag="entry",  # Atom format
    rss_title_tag="title",
    rss_link_tag="link",
    rss_summary_tag="summary",
    rss_date_tag="published",
)

# Registry
BUILTIN_PROFILES: dict[str, SiteProfile] = {
    "baidu_news": BAIDU_NEWS,
    "sina_news": SINA_NEWS,
    "deepmind_blog": DEEPMIND_BLOG,
    "openai_blog": OPENAI_BLOG,
    "google_ai_blog": GOOGLE_AI_BLOG,
}


def get_profile(name: str, custom: Optional[dict] = None) -> SiteProfile:
    """Get a site profile by name, falling back to custom config."""
    if custom:
        return SiteProfile.from_dict(custom)
    profile = BUILTIN_PROFILES.get(name)
    if profile is None:
        profile = SiteProfile(name=name, display_name=name, strategy="css_selector")
    return profile
