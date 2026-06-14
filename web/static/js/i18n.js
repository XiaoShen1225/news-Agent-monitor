// i18n — zh/en UI string dictionary
// Usage: t('key') or t('key', {count: 3}) for interpolation
// Set lang via ?lang=zh|en in URL, localStorage 'lang', or navigator.language

const I18N_DICT = {
  zh: {
    // ── Shell / Header ──
    app_title: 'News Agent Monitor',
    update_label_checking: '检查中...',
    update_label_latest: '已是最新',
    update_label_items: '{count} 项更新',
    update_panel_title: '最新更新',
    update_panel_empty: '暂无新内容',
    update_panel_no_update: '暂无更新',
    hamburger_menu: '菜单',
    hamburger_open: '打开菜单',
    ws_online: '在线',
    ws_offline: '离线',
    ws_connecting: '连接中...',

    // ── Sidebar ──
    nav_ai_assistant: 'AI 助手',
    nav_news_monitor: '新闻监控',
    nav_paper_tracking: '论文追踪',
    nav_ops_management: '运营管理',
    nav_history_sessions: '历史会话',
    nav_new_session: '新建会话',

    // ── Chat ──
    chat_title: 'AI 助手',
    chat_clear: '清空对话',
    chat_welcome_title: 'AI 监控数据助手',
    chat_welcome_desc: '可以查询新闻、统计、搜索文章<br>试试问："有哪些监控站点？" 或 "最近有哪些科技新闻？"',
    chat_input_placeholder: '输入消息...',
    chat_input_aria: '聊天消息输入',
    chat_send: '发送',
    chat_loading_history: '加载历史消息中...',
    chat_you: 'You',
    chat_ai_label: 'AI 助手',
    chat_empty_reply: '(空回复)',
    chat_request_failed: '请求失败，请稍后重试。',
    chat_send_failed_toast: '聊天请求失败，请稍后重试',
    chat_tool_prefix: '🔧 ',
    chat_no_title: 'No title',
    chat_session_delete_confirm: '确定删除该会话？此操作不可撤销。',
    chat_token_bar: '{used}/{max} tokens ({exchanges}轮)',

    // ── Chat Example Chips ──
    chip_tech_news: '今天有什么科技新闻？',
    chip_hot_trends: '最近一周有什么热点趋势？',
    chip_baidu_health: '百度新闻运行正常吗？',
    chip_set_alert: '帮我设置一个AI相关的告警',

    // ── Login ──
    login_prompt: '请输入访问密钥',
    login_placeholder: '访问密钥',
    login_confirm: '确认',
    login_error_wrong: '密钥错误，请重试',
    login_failed_toast: '登录失败，请检查网络连接',

    // ── Drawer ──
    drawer_close: '× 关闭',
    drawer_monitor: '新闻监控',
    drawer_papers: '论文追踪',
    drawer_deep: '深度分析',
    drawer_ops: '运营管理',

    // ── Monitor ──
    monitor_overview: 'Overview',
    monitor_total_runs: 'Total Runs',
    monitor_items_collected: 'Items Collected',
    monitor_sites: 'Sites',
    monitor_last_run: 'Last Run',
    monitor_site_health: 'Site Health',
    monitor_realtime_charts: 'Realtime Charts',
    monitor_tag_distribution: 'Tag Distribution',
    monitor_count_trend: 'Count Trend',
    monitor_changes: 'Changes',
    monitor_update_summary: 'Update Summary',
    monitor_select_site: 'Select site...',
    monitor_select_site_view: 'Select a site to view.',
    monitor_select_site_2: 'Select a site.',
    monitor_news_items: 'News Items',
    monitor_all_sites: 'All sites',
    monitor_all_tags: 'All tags',
    monitor_search_titles: 'Search titles...',
    monitor_search: 'Search',
    monitor_quick: 'Quick:',
    monitor_tag_tech: 'Tech',
    monitor_tag_china: 'China',
    monitor_tag_finance: 'Finance',
    monitor_tag_world: 'World',
    monitor_tag_clear: 'Clear',
    monitor_col_title: 'Title',
    monitor_col_tag: 'Tag',
    monitor_col_site: 'Site',
    monitor_col_time: 'Time',
    monitor_loading: 'Loading...',
    monitor_recent_runs: 'Recent Runs',
    monitor_col_timestamp: 'Time',
    monitor_col_status: 'Status',
    monitor_col_items: 'Items',
    monitor_col_changes: 'Changes',
    monitor_col_confidence: 'Confidence',
    monitor_col_duration: 'Duration',
    monitor_no_items: 'No items found.',
    monitor_no_runs: 'No runs yet.',
    monitor_no_update_data: 'No update data.',
    monitor_pagination_page: 'Page {page} / {total} ({count} items)',
    monitor_pagination_first: 'First',
    monitor_pagination_prev: 'Prev',
    monitor_pagination_next: 'Next',
    monitor_pagination_last: 'Last',
    monitor_ai_summary: 'AI Summary:',
    monitor_last_update: 'Last update:',
    monitor_refresh_all: 'Refresh All',
    monitor_running: 'Running...',
    monitor_run_complete: 'Run complete:',
    monitor_run_failed: 'Run failed:',
    monitor_run_accepted: 'Run triggered for {site}, will refresh when done',
    monitor_article_summary: 'Article Summary',
    monitor_summary_failed: 'Summary failed',
    monitor_no_sites: 'No sites configured',
    monitor_circuit_open: 'Circuit Open',
    monitor_status_ok: 'OK',
    monitor_status_error: 'Error',
    monitor_status_no_change: 'No Change',
    monitor_status_waiting: 'Waiting',
    monitor_run_btn: '▶ Run',
    monitor_reset_btn: '↺ Reset',
    monitor_reset_confirm: 'Reset all history for {site}? This cannot be undone.',
    monitor_reset_done: 'Reset complete',
    monitor_reset_failed: 'Reset failed: {error}',
    monitor_summary: 'Summary',
    monitor_current: 'Current',
    monitor_previous: 'Previous',
    monitor_trend: 'Trend',
    monitor_stable: 'stable',
    monitor_up: 'up',
    monitor_down: 'down',
    monitor_new: 'New',
    monitor_removed: 'Removed',
    monitor_modified: 'Modified',

    // ── Papers ──
    papers_tracking: 'Paper Tracking',
    papers_total: 'Total Papers',
    papers_deepmind: 'DeepMind',
    papers_openai: 'OpenAI',
    papers_title: 'Papers',
    papers_all_sources: 'All sources',
    papers_search_titles: 'Search titles...',
    papers_search: 'Search',
    papers_col_title: 'Title',
    papers_col_source: 'Source',
    papers_col_summary: 'Summary',
    papers_col_date: 'Date',
    papers_loading: 'Loading...',
    papers_no_found: 'No papers found.',
    papers_fetch_prefix: 'Fetch: ',
    papers_summary_btn: 'Summary',

    // ── Ops ──
    ops_preferences_memory: 'Preferences & Memory',
    ops_refresh: 'Refresh',
    ops_run_accepted: '已触发 {site} 的采集任务',
    ops_loading: 'Loading...',
    ops_no_preferences: '暂无偏好数据',
    ops_watch_management: 'Watch Management',
    ops_watch_all: 'All',
    ops_watch_topic: 'Topic',
    ops_watch_event: 'Event',
    ops_watch_no_watches: 'No watches yet. Use the AI assistant to start tracking.',
    ops_watch_active: 'Active',
    ops_watch_completed: 'Done',
    ops_watch_paused: 'Paused',
    ops_watch_untitled: 'Untitled',
    ops_watch_matches: '{count} matches',
    ops_watch_config: 'Config:',
    ops_watch_threshold: 'Threshold {val}',
    ops_watch_cooldown: 'Cooldown {val}h',
    ops_watch_stale_prompt: 'Stale prompt after {val}d',
    ops_watch_stale_count: '{count} stale',
    ops_watch_detail: 'Watch Detail',
    ops_watch_latest_summary: 'Latest Summary',
    ops_watch_match_timeline: 'Match Timeline',
    ops_watch_related_news: 'Related News',
    ops_watch_no_matches: 'No matches yet.',
    ops_watch_complete_btn: 'Complete',
    ops_watch_pause_btn: 'Pause',
    ops_watch_resume_btn: 'Resume',
    ops_watch_delete_btn: 'Delete',
    ops_watch_complete_confirm: 'Mark this watch as completed?',
    ops_watch_pause_confirm: 'Pause this watch?',
    ops_watch_resume_confirm: 'Resume this watch?',
    ops_watch_delete_confirm: 'Delete watch "{title}"?',
    ops_watch_not_found: 'Watch not found',
    ops_watch_never: 'Never',
    ops_watch_keyword: 'keyword',
    ops_watch_semantic: 'semantic',
    ops_targets_title: 'Monitoring Targets',
    ops_targets_add: '+ Add Site',
    ops_targets_url_label: 'URL',
    ops_targets_url_placeholder: 'https://...',
    ops_targets_name_label: 'Site Name',
    ops_targets_name_placeholder: 'my_site',
    ops_targets_interval: 'Interval (min)',
    ops_targets_strategy: 'Strategy',
    ops_targets_strategy_auto: 'Auto-detect',
    ops_targets_strategy_rss: 'RSS',
    ops_targets_strategy_llm: 'LLM',
    ops_targets_strategy_css: 'CSS Selector',
    ops_targets_strategy_walk: 'Section Walk',
    ops_targets_use_browser: 'Use Browser',
    ops_targets_article_source: 'Article Source',
    ops_targets_validate_url: 'Validate URL',
    ops_targets_confirm_add: 'Confirm Add',
    ops_targets_required: '*',
    ops_targets_col_name: 'Name',
    ops_targets_col_url: 'URL',
    ops_targets_col_interval: 'Interval',
    ops_targets_col_strategy: 'Strategy',
    ops_targets_col_browser: 'Browser',
    ops_targets_col_article: 'Article',
    ops_targets_col_status: 'Status',
    ops_targets_col_actions: 'Actions',
    ops_targets_builtin: 'built-in',
    ops_targets_sys_tag: '[sys]',
    ops_targets_usr_tag: '[usr]',
    ops_targets_active: 'Active',
    ops_targets_paused: 'Paused',
    ops_targets_edit_btn: 'Edit',
    ops_targets_pause_btn: 'Pause',
    ops_targets_resume_btn: 'Resume',
    ops_targets_del_btn: 'Del',
    ops_targets_run_btn: 'Run',
    ops_targets_no_targets: 'No monitoring targets configured. Click "+ Add Site" to add one.',
    ops_targets_edit_interval: 'Interval:',
    ops_targets_save_btn: 'Save',
    ops_targets_cancel_btn: 'Cancel',
    ops_targets_add_failed: 'Add failed',
    ops_targets_delete_failed: 'Delete failed',
    ops_targets_toggle_failed: 'Toggle failed',
    ops_targets_delete_confirm: 'Delete target "{name}"? This will stop monitoring but keep existing data.',
    ops_targets_url_name_required: 'URL and Site Name are required',
    ops_targets_enter_url: 'Please enter a URL first',
    ops_targets_checking: 'Checking...',

    // ── Ops Memory Status ──
    ops_events: 'Events:',
    ops_clicks_30d: '30d clicks:',
    ops_searches_30d: '30d searches:',
    ops_l0_events: 'L0 events:',
    ops_episodic: 'Episodic:',
    ops_identity: 'Identity:',

    // ── Misc / Alerts ──
    request_failed: 'Request failed: {msg}',
    unknown: 'Unknown',
  },

  en: {
    // ── Shell / Header ──
    app_title: 'News Agent Monitor',
    update_label_checking: 'Checking...',
    update_label_latest: 'Up to date',
    update_label_items: '{count} updates',
    update_panel_title: 'Latest Updates',
    update_panel_empty: 'No new content',
    update_panel_no_update: 'No updates',
    hamburger_menu: 'Menu',
    hamburger_open: 'Open menu',
    ws_online: 'Online',
    ws_offline: 'Offline',
    ws_connecting: 'Connecting...',

    // ── Sidebar ──
    nav_ai_assistant: 'AI Assistant',
    nav_news_monitor: 'News Monitor',
    nav_paper_tracking: 'Paper Tracking',
    nav_ops_management: 'Operations',
    nav_history_sessions: 'History',
    nav_new_session: 'New Session',

    // ── Chat ──
    chat_title: 'AI Assistant',
    chat_clear: 'Clear Chat',
    chat_welcome_title: 'AI Monitor Assistant',
    chat_welcome_desc: 'Query news, statistics, search articles<br>Try: "What sites are monitored?" or "Latest tech news?"',
    chat_input_placeholder: 'Type a message...',
    chat_input_aria: 'Chat message input',
    chat_send: 'Send',
    chat_loading_history: 'Loading history...',
    chat_you: 'You',
    chat_ai_label: 'AI Assistant',
    chat_empty_reply: '(empty reply)',
    chat_request_failed: 'Request failed. Please try again.',
    chat_send_failed_toast: 'Chat request failed, please try again',
    chat_tool_prefix: '🔧 ',
    chat_no_title: 'No title',
    chat_session_delete_confirm: 'Delete this session? This cannot be undone.',
    chat_token_bar: '{used}/{max} tokens ({exchanges} turns)',

    // ── Chat Example Chips ──
    chip_tech_news: 'Any tech news today?',
    chip_hot_trends: 'What are the hot trends this week?',
    chip_baidu_health: 'Is Baidu News running normally?',
    chip_set_alert: 'Set up an AI-related alert',

    // ── Login ──
    login_prompt: 'Enter access token',
    login_placeholder: 'Access token',
    login_confirm: 'Confirm',
    login_error_wrong: 'Invalid token, please try again',
    login_failed_toast: 'Login failed, please check your network',

    // ── Drawer ──
    drawer_close: '× Close',
    drawer_monitor: 'News Monitor',
    drawer_papers: 'Paper Tracking',
    drawer_deep: 'Deep Analysis',
    drawer_ops: 'Operations',

    // ── Monitor ──
    monitor_overview: 'Overview',
    monitor_total_runs: 'Total Runs',
    monitor_items_collected: 'Items Collected',
    monitor_sites: 'Sites',
    monitor_last_run: 'Last Run',
    monitor_site_health: 'Site Health',
    monitor_realtime_charts: 'Realtime Charts',
    monitor_tag_distribution: 'Tag Distribution',
    monitor_count_trend: 'Count Trend',
    monitor_changes: 'Changes',
    monitor_update_summary: 'Update Summary',
    monitor_select_site: 'Select site...',
    monitor_select_site_view: 'Select a site to view.',
    monitor_select_site_2: 'Select a site.',
    monitor_news_items: 'News Items',
    monitor_all_sites: 'All sites',
    monitor_all_tags: 'All tags',
    monitor_search_titles: 'Search titles...',
    monitor_search: 'Search',
    monitor_quick: 'Quick:',
    monitor_tag_tech: 'Tech',
    monitor_tag_china: 'China',
    monitor_tag_finance: 'Finance',
    monitor_tag_world: 'World',
    monitor_tag_clear: 'Clear',
    monitor_col_title: 'Title',
    monitor_col_tag: 'Tag',
    monitor_col_site: 'Site',
    monitor_col_time: 'Time',
    monitor_loading: 'Loading...',
    monitor_recent_runs: 'Recent Runs',
    monitor_col_timestamp: 'Time',
    monitor_col_status: 'Status',
    monitor_col_items: 'Items',
    monitor_col_changes: 'Changes',
    monitor_col_confidence: 'Confidence',
    monitor_col_duration: 'Duration',
    monitor_no_items: 'No items found.',
    monitor_no_runs: 'No runs yet.',
    monitor_no_update_data: 'No update data.',
    monitor_pagination_page: 'Page {page} / {total} ({count} items)',
    monitor_pagination_first: 'First',
    monitor_pagination_prev: 'Prev',
    monitor_pagination_next: 'Next',
    monitor_pagination_last: 'Last',
    monitor_ai_summary: 'AI Summary:',
    monitor_last_update: 'Last update:',
    monitor_refresh_all: 'Refresh All',
    monitor_running: 'Running...',
    monitor_run_complete: 'Run complete:',
    monitor_run_failed: 'Run failed:',
    monitor_run_accepted: 'Run triggered for {site}, will refresh when done',
    monitor_article_summary: 'Article Summary',
    monitor_summary_failed: 'Summary failed',
    monitor_no_sites: 'No sites configured',
    monitor_circuit_open: 'Circuit Open',
    monitor_status_ok: 'OK',
    monitor_status_error: 'Error',
    monitor_status_no_change: 'No Change',
    monitor_status_waiting: 'Waiting',
    monitor_run_btn: '▶ Run',
    monitor_reset_btn: '↺ Reset',
    monitor_reset_confirm: 'Reset all history for {site}? This cannot be undone.',
    monitor_reset_done: 'Reset complete',
    monitor_reset_failed: 'Reset failed: {error}',
    monitor_summary: 'Summary',
    monitor_current: 'Current',
    monitor_previous: 'Previous',
    monitor_trend: 'Trend',
    monitor_stable: 'stable',
    monitor_up: 'up',
    monitor_down: 'down',
    monitor_new: 'New',
    monitor_removed: 'Removed',
    monitor_modified: 'Modified',

    // ── Papers ──
    papers_tracking: 'Paper Tracking',
    papers_total: 'Total Papers',
    papers_deepmind: 'DeepMind',
    papers_openai: 'OpenAI',
    papers_title: 'Papers',
    papers_all_sources: 'All sources',
    papers_search_titles: 'Search titles...',
    papers_search: 'Search',
    papers_col_title: 'Title',
    papers_col_source: 'Source',
    papers_col_summary: 'Summary',
    papers_col_date: 'Date',
    papers_loading: 'Loading...',
    papers_no_found: 'No papers found.',
    papers_fetch_prefix: 'Fetch: ',
    papers_summary_btn: 'Summary',

    // ── Ops ──
    ops_preferences_memory: 'Preferences & Memory',
    ops_refresh: 'Refresh',
    ops_run_accepted: 'Run triggered for {site}',
    ops_loading: 'Loading...',
    ops_no_preferences: 'No preference data',
    ops_watch_management: 'Watch Management',
    ops_watch_all: 'All',
    ops_watch_topic: 'Topic',
    ops_watch_event: 'Event',
    ops_watch_no_watches: 'No watches yet. Use the AI assistant to start tracking.',
    ops_watch_active: 'Active',
    ops_watch_completed: 'Done',
    ops_watch_paused: 'Paused',
    ops_watch_untitled: 'Untitled',
    ops_watch_matches: '{count} matches',
    ops_watch_config: 'Config:',
    ops_watch_threshold: 'Threshold {val}',
    ops_watch_cooldown: 'Cooldown {val}h',
    ops_watch_stale_prompt: 'Stale prompt after {val}d',
    ops_watch_stale_count: '{count} stale',
    ops_watch_detail: 'Watch Detail',
    ops_watch_latest_summary: 'Latest Summary',
    ops_watch_match_timeline: 'Match Timeline',
    ops_watch_related_news: 'Related News',
    ops_watch_no_matches: 'No matches yet.',
    ops_watch_complete_btn: 'Complete',
    ops_watch_pause_btn: 'Pause',
    ops_watch_resume_btn: 'Resume',
    ops_watch_delete_btn: 'Delete',
    ops_watch_complete_confirm: 'Mark this watch as completed?',
    ops_watch_pause_confirm: 'Pause this watch?',
    ops_watch_resume_confirm: 'Resume this watch?',
    ops_watch_delete_confirm: 'Delete watch "{title}"?',
    ops_watch_not_found: 'Watch not found',
    ops_watch_never: 'Never',
    ops_watch_keyword: 'keyword',
    ops_watch_semantic: 'semantic',
    ops_targets_title: 'Monitoring Targets',
    ops_targets_add: '+ Add Site',
    ops_targets_url_label: 'URL',
    ops_targets_url_placeholder: 'https://...',
    ops_targets_name_label: 'Site Name',
    ops_targets_name_placeholder: 'my_site',
    ops_targets_interval: 'Interval (min)',
    ops_targets_strategy: 'Strategy',
    ops_targets_strategy_auto: 'Auto-detect',
    ops_targets_strategy_rss: 'RSS',
    ops_targets_strategy_llm: 'LLM',
    ops_targets_strategy_css: 'CSS Selector',
    ops_targets_strategy_walk: 'Section Walk',
    ops_targets_use_browser: 'Use Browser',
    ops_targets_article_source: 'Article Source',
    ops_targets_validate_url: 'Validate URL',
    ops_targets_confirm_add: 'Confirm Add',
    ops_targets_required: '*',
    ops_targets_col_name: 'Name',
    ops_targets_col_url: 'URL',
    ops_targets_col_interval: 'Interval',
    ops_targets_col_strategy: 'Strategy',
    ops_targets_col_browser: 'Browser',
    ops_targets_col_article: 'Article',
    ops_targets_col_status: 'Status',
    ops_targets_col_actions: 'Actions',
    ops_targets_builtin: 'built-in',
    ops_targets_sys_tag: '[sys]',
    ops_targets_usr_tag: '[usr]',
    ops_targets_active: 'Active',
    ops_targets_paused: 'Paused',
    ops_targets_edit_btn: 'Edit',
    ops_targets_pause_btn: 'Pause',
    ops_targets_resume_btn: 'Resume',
    ops_targets_del_btn: 'Del',
    ops_targets_run_btn: 'Run',
    ops_targets_no_targets: 'No monitoring targets configured. Click "+ Add Site" to add one.',
    ops_targets_edit_interval: 'Interval:',
    ops_targets_save_btn: 'Save',
    ops_targets_cancel_btn: 'Cancel',
    ops_targets_add_failed: 'Add failed',
    ops_targets_delete_failed: 'Delete failed',
    ops_targets_toggle_failed: 'Toggle failed',
    ops_targets_delete_confirm: 'Delete target "{name}"? This will stop monitoring but keep existing data.',
    ops_targets_url_name_required: 'URL and Site Name are required',
    ops_targets_enter_url: 'Please enter a URL first',
    ops_targets_checking: 'Checking...',

    // ── Ops Memory Status ──
    ops_events: 'Events:',
    ops_clicks_30d: '30d clicks:',
    ops_searches_30d: '30d searches:',
    ops_l0_events: 'L0 events:',
    ops_episodic: 'Episodic:',
    ops_identity: 'Identity:',

    // ── Misc / Alerts ──
    request_failed: 'Request failed: {msg}',
    unknown: 'Unknown',
  }
};

// ── Language detection & persistence ──────────────────────────────────

function detectLang() {
  // 1. URL param
  const params = new URLSearchParams(location.search);
  const urlLang = params.get('lang');
  if (urlLang && I18N_DICT[urlLang]) return urlLang;
  // 2. localStorage
  const stored = localStorage.getItem('lang');
  if (stored && I18N_DICT[stored]) return stored;
  // 3. navigator
  const nav = navigator.language || '';
  if (nav.startsWith('zh')) return 'zh';
  return 'en';
}

let currentLang = detectLang();

function setLang(lang) {
  if (!I18N_DICT[lang]) return;
  currentLang = lang;
  localStorage.setItem('lang', lang);
  document.documentElement.setAttribute('lang', lang === 'zh' ? 'zh-CN' : 'en');
  refreshI18n();
}

// ── Translation function ──────────────────────────────────────────────

function t(key, params) {
  const dict = I18N_DICT[currentLang] || I18N_DICT['en'];
  let text = dict[key];
  if (text === undefined) {
    // Fallback to zh (primary), then key itself
    text = (I18N_DICT['zh'] || {})[key];
    if (text === undefined) return key;
  }
  if (params) {
    for (const k in params) {
      text = text.replace('{' + k + '}', params[k]);
    }
  }
  return text;
}

// ── Auto-apply data-i18n attributes on page load ───────────────────────

function refreshI18n() {
  document.querySelectorAll('[data-i18n]').forEach(function(el) {
    const key = el.getAttribute('data-i18n');
    if (el.tagName === 'INPUT' && (el.type === 'text' || el.type === 'password' || el.type === 'search')) {
      el.placeholder = t(key);
    } else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      // value-based inputs — skip (user data)
    } else {
      el.textContent = t(key);
    }
  });
  document.querySelectorAll('[data-i18n-title]').forEach(function(el) {
    el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
  });
  document.querySelectorAll('[data-i18n-aria]').forEach(function(el) {
    el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria')));
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
    el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
  });
}

// Apply on initial load
document.addEventListener('DOMContentLoaded', function() {
  document.documentElement.setAttribute('lang', currentLang === 'zh' ? 'zh-CN' : 'en');
  refreshI18n();
});
