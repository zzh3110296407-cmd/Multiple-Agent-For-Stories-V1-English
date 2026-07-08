const PENDING_TEXT = "正在读取项目数据";
const EMPTY_BACKEND_TEXT = "暂无此项数据";

const STATIC_TEXT = new Set([
  "Multiple Agent",
  "For Stories",
  "Multiple Agent For Stories",
  "故事创作工作台",
  "让世界、角色与章节在同一张长卷中苏醒",
  "主页",
  "返回",
  "返回主页",
  "返回总览",
  "设置",
  "新手引导",
  "开始创作",
  "新创作",
  "继续创作",
  "历史创作",
  "作品集",
  "导入故事",
  "灵感库",
  "创作资料库",
  "新故事",
  "搜索故事、角色、世界",
  "最近更新",
  "网格",
  "状态",
  "全部故事",
  "进行中",
  "已完成",
  "暂停",
  "归档",
  "题材",
  "当前选中",
  "上次草稿",
  "当前主题",
  "继续",
  "详细",
  "创建项目",
  "项目创建",
  "项目列表",
  "当前项目总览",
  "模板与演示",
  "Framework 编排",
  "Framework Library",
  "故事设定",
  "世界画布",
  "角色主轴",
  "章节计划",
  "场景写作",
  "最终输出",
  "插件输出",
  "生成",
  "生成中",
  "审阅",
  "草案审阅",
  "问题处理",
  "修订",
  "确认",
  "确认保存",
  "下一步",
  "上一步",
  "保存",
  "提交",
  "应用",
  "导出",
  "下载",
  "运行",
  "刷新",
  "选择",
  "校验",
  "检查点",
  "外观与主题",
  "模型配置",
  "当前模型与健康检查",
  "密钥与安全",
  "创作偏好",
  "运行健康检查",
  "返回 Framework",
  "开始分析",
  "查看结果",
  "使用候选",
  "导入编辑会话",
  "输出设置",
  "查看成果",
  "查看成稿",
]);

const STATIC_TEXT_PATTERNS = [
  /^0\.\d{2}-\d\.\d{2}s$/,
  /^#?[A-Fa-f0-9]{6}$/,
  /^Phase\s*\d+(\.\d+)?$/i,
  /^M\d+$/,
];

const DYNAMIC_PATTERNS = [
  /待后端接入|正在读取项目数据/,
  /第三章|雨夜港口|钟楼|证词|港口|雾中列车|灰鸽档案|龙影|城堡|飞龙|潮汐|白塔|沉默同盟|误认关系|失忆碎片|低魔|主压力线|公爵|守夜|星港|边境|城市里有|龙影传说/,
  /上次草稿|当前主题|继续创作会从最近|最近节点|当前选中|会话\s*\d+|版本|草稿与版本/,
  /Morandi\s*·\s*Dragon Parchment|Classic Morandi|qwen[_-]default|qwen-plus|Qwen/i,
  /奇幻史诗|城市悬疑|温柔日常|科幻远征|低魔悬疑|古典学院|赛博都市|黑暗奇幻|群像|A\s*级角色\s*\d+|[A-D]\s*级角色\s*\d+/i,
  /更新.*。|继续确认.*。|待续.*。|已从.*。|草案\s*\d+|硬\s*\d+\s*\/\s*软\s*\d+\s*\/\s*未知\s*\d+/,
  /温暖|克制|雨夜阴影|大规模战争|知情隐瞒|残缺档案|集体记忆缺口|最终事实底座|触发条件|港口城悬疑前提|旧贵族是否掌握真相/,
  /港口城|港城|钟楼|证词|潮汐禁区|旧贵族|龙影传说|外海|其他城市|日常秩序|真相|剧情线索|角色证词|世界规则导致/,
  /真实最终包|最终故事包快照|风格基调|非阻塞残留|成稿附注|叙事债务|远钟之后|暗潮名单|龙影落城|最后的灯|莱昂|书记|守密者|见证者/,
  /\d+\s*(章|幕|场景|角色|条|个|项|轮|步|%|分钟|小时|天|KB|MB|tokens?|sources?|warnings?|Scenes?|Items?|Patterns?|Rules?)/i,
  /港城钟楼证词|雾港钟楼证词|灰雾王庭|星河驿站|雨巷机械师|星际旅程|远钟之后|艾琳|旧约|木匣|塔楼|邮差|跨星系|濒死文明|机械师|记忆裂缝|龙的遗骨|继承人/,
  /[，。；：].*(港城|钟声|集体记忆|真相|王庭|灰雾|龙|星系|邮差|机械师|记忆|塔楼|手稿|木匣|旧名|船|人物|规则|禁区|外海|贵族|证言|线索|偿付|债务|宏组件)/,
  /今天\s*\d{1,2}:\d{2}|昨天\s*\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日|第\s*\d+\s*幕|第[一二三四五六七八九十]+章/,
  /\d{1,3}(,\d{3})+\s*(字符|字|tokens?)/i,
  /(draft|validated|ready|candidate|warnings?|blocked|archived|private|project|low|medium|high|reference|user_reviewed|requires_review|macro_component|payoff_pattern|composition_rule|contradiction|suggestion|m\d+_[a-z_]+)/i,
  /(gpt|claude|gemini|model|api|key|profile|provider|endpoint|latency|health|secret|token|qwen|deepseek|local mock|deterministic|configured|not required)/i,
  /(docx|pdf|epub|markdown|json|zip|manifest|artifact|export|download)/i,
  /(已确认|已锁定|已归档|可恢复|未解|警告\s*\d+|阻塞\s*\d+|完成度|通过率|覆盖率|字数|目录|角色表|世界摘要|事件线|锁定约束)/,
  /(章节|场景|角色|世界|Framework|插件|导出|报告|候选|素材|规则).{0,18}(摘要|列表|状态|数量|进度|来源|候选|结果|详情|内容|时间|文件|记录|快照)/,
];

const LABEL_PREFIXES = [
  "上次草稿",
  "当前主题",
  "进度",
  "最近节点",
  "会话状态",
  "素材目录",
  "来源引用",
  "文件",
  "模型",
  "状态",
  "结果",
  "摘要",
];

const DATA_VALUE_SELECTOR = [
  ".project-title",
  ".summary",
  ".detail-title",
  ".detail-summary",
  ".meta",
  ".result-sub",
  ".note span",
  ".summary-card strong",
  ".summary-item strong",
  ".fact-card strong",
  ".fact-card p",
  ".fact-row strong",
  ".fact-row span:last-child",
  ".state-card strong",
  ".state-card span",
  ".state-card p",
  ".status-item span:last-child",
  ".impact-item strong",
  ".impact-item span:last-child",
  ".issue-title",
  ".issue-type",
  ".issue-detail p",
  ".reader-meta strong",
  "#readerMetaValue",
  ".review-badge span",
  ".review-badge strong",
  "#badgeLabel",
  "#topStatus",
  ".health-cell strong",
  ".health-cell span:last-child",
  ".health-grid div strong",
  ".warning-row strong",
  ".warning-row span:not(.mark)",
  "#warningDetail",
  ".reader-body .manuscript",
  ".index-row strong",
  ".index-row span",
  ".data-row strong",
  ".data-row span",
  "#sectionBody",
].join(", ");

function normalize(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function isStaticText(text) {
  if (!text) {
    return true;
  }
  if (STATIC_TEXT.has(text)) {
    return true;
  }
  return STATIC_TEXT_PATTERNS.some((pattern) => pattern.test(text));
}

function isInteractiveRoot(element) {
  return Boolean(element?.closest?.("button, a, input, textarea, select, option, [contenteditable='true']"));
}

function isControlOnlyText(element, text) {
  if (!isInteractiveRoot(element)) {
    return false;
  }
  return isStaticText(text);
}

function isPageChromeText(element) {
  return Boolean(element?.closest?.(".hero h1, .hero p, .breadcrumb, .topbar, .route-strip"));
}

function isBackendDataSlot(element) {
  return Boolean(element?.closest?.(DATA_VALUE_SELECTOR));
}

function isDynamicNumericBadge(element, text) {
  if (!/^\d+(\.\d+)?%?$/.test(text)) {
    return false;
  }
  return Boolean(element?.closest?.(".filter-button span:last-child, .status-item span:last-child, .metric-value, .stat-value, .count, .badge-count"));
}

function isDynamicText(text, element) {
  if (!text) {
    return false;
  }
  if (isBackendDataSlot(element) || isDynamicNumericBadge(element, text)) {
    return true;
  }
  if (isStaticText(text)) {
    return false;
  }
  return DYNAMIC_PATTERNS.some((pattern) => pattern.test(text));
}

function replacementFor(text) {
  for (const prefix of LABEL_PREFIXES) {
    const shouldUseLabelPrefix = text.startsWith(prefix) && text !== prefix;
    if (shouldUseLabelPrefix) {
      return `${prefix}: ${EMPTY_BACKEND_TEXT}`;
    }
    if (text.startsWith(prefix) && text !== prefix) {
      return `${prefix}：${PENDING_TEXT}`;
    }
  }
  return EMPTY_BACKEND_TEXT;
}

function markElement(element) {
  if (!element || element.dataset?.backendPending === "true") {
    return;
  }
  if (element.dataset) {
    element.dataset.backendPending = "true";
  }
  element.classList?.add?.("mafs-backend-pending");
}

function injectStyle(doc) {
  if (doc.getElementById("mafs-backend-pending-style")) {
    return;
  }
  const style = doc.createElement("style");
  style.id = "mafs-backend-pending-style";
  style.textContent = `
    .mafs-backend-pending {
      color: rgba(82, 68, 58, 0.58) !important;
      font-style: normal !important;
    }
    .mafs-backend-pending::selection {
      background: rgba(180, 138, 120, 0.22);
    }
    text.mafs-backend-pending,
    tspan.mafs-backend-pending {
      fill: rgba(82, 68, 58, 0.58) !important;
    }
    input,
    textarea,
    select {
      color: #211d19 !important;
      caret-color: #211d19 !important;
    }
    input::placeholder,
    textarea::placeholder {
      color: rgba(86, 74, 65, 0.62) !important;
    }
  `;
  doc.head?.appendChild(style);
}

function replaceTextNode(node) {
  const original = normalize(node.nodeValue);
  if (!original) {
    return 0;
  }

  const parent = node.parentElement;
  if (!parent) {
    return 0;
  }
  if (
    parent.closest(
      [
        "script",
        "style",
        "title",
        "svg defs",
        "[data-mafs-live-status='true']",
        "[data-mafs-backend-rendered='true']",
        "[data-mafs-backend-bound='true']",
        ".mafs-backend-rendered",
        ".mafs-bridge-toast",
      ].join(", "),
    )
  ) {
    return 0;
  }
  if (isControlOnlyText(parent, original) && !isBackendDataSlot(parent) && !isDynamicNumericBadge(parent, original)) {
    return 0;
  }
  if (isPageChromeText(parent) && !isBackendDataSlot(parent)) {
    return 0;
  }
  if (!isDynamicText(original, parent)) {
    return 0;
  }

  node.nodeValue = node.nodeValue.replace(original, replacementFor(original));
  markElement(parent);
  return 1;
}

function replaceSvgTextElement(element) {
  const text = normalize(element.textContent);
  if (!isDynamicText(text, element) || (isControlOnlyText(element, text) && !isBackendDataSlot(element) && !isDynamicNumericBadge(element, text))) {
    return 0;
  }
  element.textContent = replacementFor(text);
  markElement(element);
  return 1;
}

function replacePendingText(doc) {
  if (!doc?.body) {
    return 0;
  }

  injectStyle(doc);
  let replacements = 0;

  doc.querySelectorAll("svg text, svg tspan").forEach((element) => {
    replacements += replaceSvgTextElement(element);
  });

  const nodeFilter = doc.defaultView?.NodeFilter || NodeFilter;
  const walker = doc.createTreeWalker(doc.body, nodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const text = normalize(node.nodeValue);
      if (!text || text === PENDING_TEXT) {
        return nodeFilter.FILTER_REJECT;
      }
      return nodeFilter.FILTER_ACCEPT;
    },
  });

  const nodes = [];
  while (walker.nextNode()) {
    nodes.push(walker.currentNode);
  }
  nodes.forEach((node) => {
    replacements += replaceTextNode(node);
  });

  return replacements;
}

function installMutationObserver(doc) {
  if (!doc?.body || doc.body.dataset.backendPendingObserver === "true") {
    return;
  }

  const MutationObserver = doc.defaultView?.MutationObserver;
  if (!MutationObserver) {
    return;
  }

  doc.body.dataset.backendPendingObserver = "true";
  let queued = false;
  let applying = false;

  const run = () => {
    if (applying) {
      return;
    }
    applying = true;
    replacePendingText(doc);
    applying = false;
  };

  const observer = new MutationObserver(() => {
    if (applying || queued) {
      return;
    }
    queued = true;
    doc.defaultView.requestAnimationFrame(() => {
      queued = false;
      run();
    });
  });

  observer.observe(doc.body, {
    childList: true,
    subtree: true,
    characterData: true,
  });
}

export function applyBackendPendingState(doc) {
  const replacements = replacePendingText(doc);
  installMutationObserver(doc);
  return replacements;
}
