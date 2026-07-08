import { useEffect, useMemo, useRef, useState } from "react";

import { getApiMode, hydrateWorkspaceRefs, runWorkspaceAction, workspaceIdForPageId } from "./api/workspaceActions.js";
import { PAGE_BY_ID, getPage, getPreviousPage } from "./data/confirmedPages.js";
import { applyBackendPendingState } from "./utils/backendPendingState.js";
import "./styles.css";

const DIRECTORY_ITEMS = [
  { id: "project-create", label: "新创作", to: "project-create", active: ["project-create"] },
  { id: "projects", label: "项目列表", to: "projects", active: ["projects"] },
  { id: "current-project", label: "项目总览", to: "current-project", active: ["current-project"] },
  { id: "template-demo", label: "模板与演示", to: "template-demo", active: ["template-demo"] },
  {
    id: "framework",
    label: "Framework",
    to: "framework",
    active: ["framework", "framework-library", "imported-session"],
  },
  { id: "import-source", label: "故事分析器", to: "import-source", active: ["import-source", "analyzing", "analysis-result", "framework-candidate"] },
  {
    id: "story-setup",
    label: "故事设定",
    to: "story-setup-entry",
    active: ["story-setup-entry", "story-setup-generating", "story-setup-review", "story-setup-missing", "story-setup-decision", "story-setup-handoff"],
  },
  {
    id: "world-canvas",
    label: "世界画布",
    to: "world-entry",
    active: ["world-entry", "world-generating", "world-review", "world-gap", "world-revision", "world-confirm"],
  },
  {
    id: "character-spine",
    label: "角色主轴",
    to: "character-entry",
    active: ["character-entry", "character-generating", "character-review", "character-conflict", "character-missing", "character-revision", "character-confirm", "role-library", "role-context", "a-tier-state-change"],
  },
  {
    id: "chapter-planning",
    label: "章节计划",
    to: "chapter-source",
    active: ["chapter-source", "chapter-building", "chapter-framework-review", "chapter-route-entry", "chapter-route-generating", "chapter-route-review", "chapter-scene-count", "chapter-issue", "chapter-revision", "chapter-confirm"],
  },
  {
    id: "scene-writing",
    label: "场景写作",
    to: "scene-entry",
    active: ["scene-entry", "scene-brief", "scene-generating", "scene-review", "scene-revision", "scene-continuity", "scene-confirm", "scene-gate", "scene-impact", "chapter-closeout"],
  },
  {
    id: "final-output",
    label: "最终输出",
    to: "final-entry",
    active: ["final-entry", "final-assembly", "final-review", "final-settings", "final-exporting", "final-result", "final-issue"],
  },
  {
    id: "plugin-output",
    label: "插件输出",
    to: "plugin-entry",
    active: ["plugin-entry", "plugin-select", "plugin-running", "plugin-checkpoint", "plugin-review", "plugin-issue"],
  },
  {
    id: "settings",
    label: "设置",
    to: "settings-overview",
    active: ["settings-overview", "settings-appearance", "settings-model", "settings-health", "settings-secrets", "settings-preferences"],
  },
];

const DIRECTORY_HIDDEN_PAGES = new Set(["opening", "home", "start-popout"]);
const MODEL_BACKEND_STATUS_PAGE_IDS = new Set(["settings-health"]);
const WORLD_CANVAS_PAGE_IDS = new Set(["world-entry", "world-generating", "world-review", "world-gap", "world-revision", "world-confirm"]);
const FRAMEWORK_PAGE_IDS = new Set(["framework"]);
const FRAMEWORK_LIBRARY_PAGE_IDS = new Set(["framework-library"]);
const STORY_SETUP_ENTRY_PAGE_IDS = new Set(["story-setup-entry"]);
const CHARACTER_PAGE_IDS = new Set([
  "character-entry",
  "character-generating",
  "character-review",
  "character-conflict",
  "character-missing",
  "character-revision",
  "character-confirm",
  "a-tier-state-change",
]);
const ROLE_LIBRARY_PAGE_IDS = new Set(["role-library"]);
const ROLE_CONTEXT_PAGE_IDS = new Set(["role-context"]);
const SCENE_PAGE_IDS = new Set(["scene-entry", "scene-generating", "scene-review", "scene-confirm", "chapter-closeout"]);

const READ_ONLY_LOAD_ACTION_BY_PAGE_ID = {
  "project-create": "navigation.createProject",
  projects: "projects.refresh",
  "current-project": "app.progress",
  "template-demo": "template.refresh",
  framework: "framework.workbench",
  "framework-library": "framework.library",
  "imported-session": "framework.openImportedSession",
  "import-source": "analyze.refresh",
  analyzing: "analyze.refresh",
  "analysis-result": "analyze.refresh",
  "framework-candidate": "analyze.refresh",
  "story-setup-entry": "storySetup.current",
  "story-setup-generating": "storySetup.current",
  "story-setup-review": "storySetup.current",
  "story-setup-missing": "storySetup.current",
  "story-setup-decision": "storySetup.current",
  "story-setup-handoff": "storySetup.current",
  "world-entry": "world.current",
  "world-generating": "world.current",
  "world-review": "world.current",
  "world-gap": "world.current",
  "world-revision": "world.current",
  "world-confirm": "world.current",
  "character-entry": "characters.current",
  "character-generating": "characters.current",
  "character-review": "characters.current",
  "character-conflict": "characters.current",
  "character-missing": "characters.current",
  "character-revision": "characters.current",
  "character-confirm": "characters.current",
  "role-library": "roles.refresh",
  "role-context": "characters.current",
  "a-tier-state-change": "roles.pendingStateChanges",
  "chapter-source": "chapter.currentPlan",
  "chapter-building": "chapter.currentFramework",
  "chapter-framework-review": "chapter.currentFramework",
  "chapter-route-entry": "chapter.currentPlan",
  "chapter-route-generating": "chapter.currentPlan",
  "chapter-route-review": "chapter.currentPlan",
  "chapter-scene-count": "chapter.currentPlan",
  "chapter-issue": "chapter.currentPlan",
  "chapter-revision": "chapter.currentPlan",
  "chapter-confirm": "chapter.currentPlan",
  "scene-entry": "scene.current",
  "scene-brief": "scene.current",
  "scene-generating": "scene.current",
  "scene-review": "scene.current",
  "scene-revision": "scene.current",
  "scene-continuity": "scene.current",
  "scene-confirm": "scene.current",
  "scene-gate": "scene.current",
  "scene-impact": "scene.current",
  "chapter-closeout": "scene.current",
  "final-entry": "final.refreshExports",
  "final-assembly": "final.refreshExports",
  "final-review": "final.refreshExports",
  "final-settings": "final.refreshExports",
  "final-exporting": "final.refreshExports",
  "final-result": "final.refreshExports",
  "final-issue": "final.readiness",
  "plugin-entry": "plugins.refresh",
  "plugin-select": "plugins.refresh",
  "plugin-running": "plugins.run",
  "plugin-checkpoint": "plugins.run",
  "plugin-review": "plugins.artifacts",
  "plugin-issue": "plugins.safetyReport",
  "settings-overview": "settings.workbench",
  "settings-appearance": "settings.workbench",
  "settings-model": "settings.workbench",
  "settings-health": "settings.activeModel",
  "settings-secrets": "settings.secretPolicy",
  "settings-preferences": "settings.workbench",
};

const REALTIME_LOAD_ACTION_BY_PAGE_ID = {
  analyzing: "analyze.refresh",
  "story-setup-generating": "storySetup.current",
  "world-generating": "world.current",
  "character-generating": "characters.current",
  "chapter-building": "chapter.currentFramework",
  "chapter-route-generating": "chapter.currentPlan",
  "scene-generating": "scene.current",
  "final-assembly": "final.refreshExports",
  "final-exporting": "final.refreshExports",
  "plugin-running": "plugins.run",
};

const GENERATION_START_ACTION_BY_PAGE_ID = {
  "story-setup-generating": "storySetup.createDraft",
};

const GENERATION_READY_REF_BY_PAGE_ID = {
  "story-setup-generating": "storySetupDraftBundleId",
};

const REALTIME_POLL_INTERVAL_MS = 2000;
const REALTIME_MAX_POLLS = 18;

const ACTION_STATUS_LABEL_BY_ID = {
  "analyze.refresh": "故事分析状态已同步",
  "navigation.storySetup": "故事设定状态已同步",
  "world.current": "世界画布状态已同步",
  "characters.current": "角色状态已同步",
  "chapter.currentFramework": "当前章 Framework 状态已同步",
  "chapter.currentPlan": "章节路线状态已同步",
  "scene.current": "场景正文状态已同步",
  "final.refreshExports": "最终输出状态已同步",
  "plugins.run": "插件运行状态已同步",
  "storySetup.createDraft": "故事设定草案已生成",
  "storySetup.current": "故事设定状态已同步",
};

function parseHash() {
  const value = window.location.hash.replace(/^#\/?/, "");
  return value && PAGE_BY_ID[value] ? value : "home";
}

function framePageId(doc) {
  return doc?.body?.dataset?.mafsPageId || "";
}

function isFramePage(doc, pageIds) {
  const pageId = framePageId(doc);
  return !pageId || pageIds.has(pageId);
}

function navigate(pageId) {
  window.location.hash = pageId;
}

function isImmediateNavigationAction(action) {
  return Boolean(action?.to && action?.actionId?.startsWith("navigation."));
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, "");
}

function cssEscapeValue(doc, value) {
  const text = String(value || "");
  return doc?.defaultView?.CSS?.escape ? doc.defaultView.CSS.escape(text) : text.replace(/["\\]/g, "\\$&");
}

function actionMatches(element, action) {
  if (action.selector && element.matches(action.selector)) {
    return true;
  }
  const text = normalizeText(`${element.textContent || ""} ${element.getAttribute("aria-label") || ""} ${element.title || ""}`);
  return (action.match || []).some((item) => text.includes(normalizeText(item)));
}

function findDatasetAction(target) {
  const element = target?.closest?.("[data-mafs-action-id], [data-mafs-target]");
  if (!element) {
    return null;
  }
  const actionId = String(element.dataset.mafsActionId || "").trim();
  const to = String(element.dataset.mafsTarget || "").trim();
  if (!actionId && !to) {
    return null;
  }
  return {
    ...(actionId ? { actionId } : {}),
    ...(to ? { to } : {}),
  };
}

function isBackElement(element) {
  const label = normalizeText(`${element.textContent || ""} ${element.getAttribute("aria-label") || ""} ${element.className || ""} ${element.id || ""}`);
  return label.includes("返回") || label.toLowerCase().includes("back");
}

function findHomeCoordinateAction(page, event, doc) {
  if (page.id === "opening") {
    return page.actions[0] || { to: "home" };
  }
  if (page.id !== "home") {
    return null;
  }
  const width = doc.defaultView.innerWidth || doc.documentElement.clientWidth || 1;
  const height = doc.defaultView.innerHeight || doc.documentElement.clientHeight || 1;
  const x = event.clientX / width;
  const y = event.clientY / height;
  const hit = (left, top, right, bottom) => x >= left && x <= right && y >= top && y <= bottom;

  if (hit(0.41, 0.58, 0.59, 0.70)) {
    return page.actions.find((action) => action.to === "start-popout");
  }
  if (hit(0.23, 0.70, 0.40, 0.83)) {
    return page.actions.find((action) => action.to === "projects");
  }
  if (hit(0.39, 0.70, 0.55, 0.83)) {
    return page.actions.find((action) => action.to === "framework");
  }
  if (hit(0.53, 0.70, 0.69, 0.83)) {
    return page.actions.find((action) => action.to === "template-demo");
  }
  if (hit(0.67, 0.70, 0.84, 0.83)) {
    return page.actions.find((action) => action.to === "template-demo");
  }
  if (hit(0.86, 0, 1, 0.11)) {
    return page.actions.find((action) => action.to === "settings-overview");
  }
  return null;
}

function findPrimaryFallbackAction(page, element) {
  if (!element) {
    return null;
  }
  const key = `${element.className || ""} ${element.id || ""}`.toLowerCase();
  const isPrimary =
    key.includes("primary") ||
    key.includes("confirm") ||
    key.includes("next") ||
    key.includes("generate") ||
    key.includes("create");

  if (!isPrimary) {
    return null;
  }
  return page.actions.find((action) => action.to || action.actionId) || null;
}

function findBlankDismissAction(page, target) {
  if (page.id !== "start-popout" || target) {
    return null;
  }
  return { to: "home" };
}

function findSelectorAction(page, target) {
  if (!target?.closest) {
    return null;
  }
  if (page.id === "story-setup-review" && target.closest(".mini-save")) {
    const button = target.closest(".mini-save");
    const questionCard = button?.closest?.(".question") || button?.closest?.("[data-story-setup-question-id]");
    const questionId =
      button?.dataset?.storySetupQuestionId ||
      questionCard?.dataset?.storySetupQuestionId ||
      "";
    return {
      to: "story-setup-review",
      actionId: "storySetup.answerQuestion",
      localContext: { storySetupQuestionId: questionId },
    };
  }
  if (page.id === "character-confirm" && target.closest("#confirmButton, #sideConfirmButton")) {
    return { to: "role-library", actionId: "characters.confirm" };
  }
  if (page.id === "character-confirm" && target.closest("#saveRole")) {
    return { to: "role-library", actionId: "roles.refresh" };
  }
  if (page.id === "role-context" && target.closest("#confirmButton")) {
    return { to: "framework", actionId: "characters.finishMainCast" };
  }
  if (page.id === "character-entry" && target.closest("#generateButton")) {
    return { to: "character-generating", actionId: "characters.generate" };
  }
  if (page.id === "character-generating" && target.closest("#reviewButton")) {
    return { to: "character-review", actionId: "characters.current" };
  }
  if (page.id === "role-library" && target.closest("#saveRole")) {
    return { to: "role-library", actionId: "roles.refresh" };
  }
  if (page.id === "role-library" && target.closest("#buildContext, #mafsRoleContextButton")) {
    return { to: "role-context", actionId: "roles.contextPreview" };
  }
  if (page.id === "framework" && target.closest('.source-tab[data-source="资料库"]')) {
    return { to: "framework-library", actionId: "framework.library" };
  }
  if (page.id === "framework" && target.closest("#generateButton")) {
    return { to: "chapter-source", actionId: "framework.validateAndConfirm" };
  }
  if (page.id === "chapter-source" && target.closest("#build-button")) {
    return { to: "chapter-building", actionId: "chapter.buildCurrent" };
  }
  if (page.id === "chapter-building" && target.closest(".soft-button")) {
    return { to: "chapter-framework-review", actionId: "chapter.currentFramework" };
  }
  if (page.id === "chapter-framework-review" && target.closest(".primary-button")) {
    return { to: "chapter-route-entry", actionId: "chapter.currentPlan" };
  }
  if (page.id === "chapter-route-entry" && target.closest("#generate-button")) {
    return { to: "chapter-route-generating", actionId: "chapter.generatePlan" };
  }
  if (page.id === "chapter-route-generating" && target.closest(".soft-button")) {
    return { to: "chapter-route-review", actionId: "chapter.currentPlan" };
  }
  if (page.id === "chapter-route-review" && target.closest(".primary-button")) {
    return { to: "chapter-scene-count", actionId: "chapter.setSceneCount" };
  }
  if (page.id === "chapter-route-review" && target.closest(".button-group .soft-button:nth-child(2)")) {
    return { to: "chapter-issue", actionId: "chapter.repairRoles" };
  }
  if (page.id === "chapter-scene-count" && target.closest("#save-count-button")) {
    return { to: "chapter-route-review", actionId: "chapter.setSceneCount" };
  }
  if (page.id === "chapter-issue" && target.closest("#resolve-button")) {
    return { to: "chapter-route-review", actionId: "chapter.repairRoles" };
  }
  if (page.id === "chapter-confirm" && target.closest("#confirm-button")) {
    return { to: "chapter-confirm", actionId: "chapter.confirm" };
  }
  if (page.id === "chapter-confirm" && target.closest("#goSceneButton")) {
    return { to: "scene-entry", actionId: "navigation.scene" };
  }
  if (page.id === "scene-generating" && target.closest("button, a, [role='button']")) {
    const text = normalizeText(target.closest("button, a, [role='button']")?.textContent || "");
    if (text.includes("草案审阅") || text.includes("查看") || text.includes("完成")) {
      return { to: "scene-review", actionId: "scene.current" };
    }
  }
  if (page.id === "scene-generating" && target.closest("#mafsSceneReviewButton")) {
    return { to: "scene-review", actionId: "scene.current" };
  }
  if (page.id === "scene-review" && target.closest("#confirmButton")) {
    return { to: "scene-confirm", actionId: "scene.commit" };
  }
  if (page.id === "scene-confirm" && target.closest("button, a, [role='button']")) {
    const text = normalizeText(target.closest("button, a, [role='button']")?.textContent || "");
    if (target.closest("#mafsChapterCloseoutButton")) {
      return { to: "chapter-closeout", actionId: "scene.archivePreview" };
    }
    if (text.includes("下一场景")) {
      return { to: "scene-entry", actionId: "scene.generateNext" };
    }
    if (text.includes("章节收尾") || text.includes("章节末尾") || text.includes("准备下一章")) {
      return { to: "chapter-closeout", actionId: "scene.archivePreview" };
    }
  }
  if (page.id === "chapter-closeout" && target.closest("button, a, [role='button']")) {
    const text = normalizeText(target.closest("button, a, [role='button']")?.textContent || "");
    if (target.closest("#mafsNextChapterButton") || text.includes("下一章")) {
      return { to: "chapter-source", actionId: "scene.confirmNextChapter" };
    }
    if (target.closest("#mafsStoryCompleteButton") || text.includes("最终输出") || text.includes("故事草稿完成")) {
      return { to: "final-entry", actionId: "scene.confirmStoryComplete" };
    }
  }
  return page.actions.find((action) => action.selector && target.closest(action.selector)) || null;
}

function isLocalOnlyControl(page, target) {
  if (!target?.closest) {
    return false;
  }
  if (page.id === "story-setup-review" && target.closest(".question-toggle, .answer-input")) {
    return true;
  }
  if (page.id === "story-setup-review" && target.closest(".mini-save")) {
    const questionCard = target.closest(".question") || target.closest("[data-story-setup-question-id]");
    const questionId = questionCard?.dataset?.storySetupQuestionId || target.closest(".mini-save")?.dataset?.storySetupQuestionId || "";
    if (!questionId || questionId.startsWith("story_setup_static_question_")) {
      return true;
    }
  }
  if (page.id === "story-setup-decision" && target.closest(".decision-option, #resetButton")) {
    return true;
  }
  if (
    WORLD_CANVAS_PAGE_IDS.has(page.id) &&
    target.closest(".section-tab, .filter-button, #issueList .issue-item")
  ) {
    return true;
  }
  if (
    CHARACTER_PAGE_IDS.has(page.id) &&
    target.closest(".stage-button, .tier-trigger, .tier-option, #clearButton")
  ) {
    return true;
  }
  if (
    FRAMEWORK_PAGE_IDS.has(page.id) &&
    target.closest(
      ".source-tab, .material-card, .slot-card, .chapter-node, .mafs-framework-source-tab, .mafs-framework-material-card, .mafs-framework-add, .mafs-framework-remove, .mafs-framework-dropzone, .mafs-framework-canvas-item, #chapterCountPicker, #chapterMenu",
    )
  ) {
    return true;
  }
  return page.id === "story-setup-handoff" && Boolean(target.closest("#createButton"));
}

function setAlias(form, key, value) {
  if (!key || form[key] !== undefined) {
    return;
  }
  form[key] = value;
}

function normalizeFieldAliases(form, rawKey, value) {
  const compactKey = rawKey.replace(/[-_\s]+(.)?/g, (_, char = "") => char.toUpperCase());
  const lowerKey = rawKey.toLowerCase();

  setAlias(form, compactKey, value);

  const aliasMap = {
    "project-title": ["projectTitle", "requestedTitle"],
    "story-prompt": ["projectPrompt", "promptText", "setupPrompt"],
    projectname: ["projectTitle", "requestedTitle"],
    storyprompt: ["setupPrompt", "promptText", "projectPrompt"],
    storyidea: ["worldIdea"],
    sourcetext: ["storyImport", "textContent"],
    storytitle: ["storyTitle", "requestedTitle"],
    sourcenote: ["sourceNote", "safeUserNote"],
    kindselect: ["sourceKind", "sourceType"],
    characterprompt: ["characterPrompt"],
    selectedtierbadge: ["roleTier"],
    roleTier: ["roleTier"],
    "story-goal": ["chapterPlanPrompt", "storyGoal"],
    storygoal: ["chapterPlanPrompt", "storyGoal"],
    "chapter-count": ["chapterCount"],
    chaptercount: ["chapterCount"],
    "current-chapter": ["chapterIndex"],
    currentchapter: ["chapterIndex"],
    exportformat: ["exportFormat"],
  };

  (aliasMap[rawKey] || aliasMap[compactKey] || aliasMap[lowerKey] || []).forEach((alias) => {
    setAlias(form, alias, value);
  });

  if (lowerKey.includes("revision")) {
    form.worldRevision = value;
    form.characterRevision = value;
    form.chapterRevision = value;
    form.sceneRevision = value;
  }
  if (lowerKey.includes("answer")) {
    setAlias(form, "answerText", value);
  }
}

function textContent(doc, selector) {
  return doc.querySelector(selector)?.textContent?.trim() || "";
}

function addDerivedFrameFields(doc, form) {
  const chapterCountText = textContent(doc, "#chapterCountButton, .count-button.active");
  const chapterCount = chapterCountText.match(/\d+/)?.[0];
  if (chapterCount) {
    form.chapterCount = chapterCount;
  }

  const sceneCountText = textContent(doc, "#count-value");
  const sceneCount = sceneCountText.match(/\d+/)?.[0];
  if (sceneCount) {
    form.sceneCount = sceneCount;
  }

  const tierText = textContent(doc, "#selectedTierBadge, #tierTrigger");
  const tierMatch = tierText.match(/[A-D]/i);
  if (tierMatch) {
    form.roleTier = tierMatch[0].toUpperCase();
  }

  const activeFormat = doc.querySelector(
    ".format-card.active[data-format], .download-button.active[data-format], [aria-checked='true'][data-format]",
  )?.dataset?.format;
  if (activeFormat) {
    form.exportFormat = activeFormat;
  }

  const pageText = textContent(doc, "body");
  if (!form.exportFormat && /Markdown/i.test(pageText)) {
    form.exportFormat = "markdown";
  }
}

function collectFrameForm(doc) {
  const form = {};
  doc.querySelectorAll("input, textarea, select").forEach((element) => {
    const rawKey = element.name || element.id || element.getAttribute("aria-label") || "";
    if (!rawKey) {
      return;
    }
    const value = element.type === "checkbox" ? element.checked : element.value;
    form[rawKey] = value;
    normalizeFieldAliases(form, rawKey, value);
  });
  addDerivedFrameFields(doc, form);
  return form;
}

function storySetupQuestionId(question) {
  return String(
    question?.story_setup_question_id ||
      question?.storySetupQuestionId ||
      question?.question_id ||
      question?.questionId ||
      question?.id ||
      "",
  );
}
function storySetupQuestionType(question) {
  return String(question?.question_type || question?.questionType || "");
}

function storySetupQuestionAnswered(question) {
  const status = String(question?.answer_status || question?.answerStatus || "").toLowerCase();
  const normalizedStatus = status.replace(/[\s-]+/g, "_");
  const hasExplicitUserAnswer = Boolean(
    question?.user_answer_ref ||
      question?.userAnswerRef ||
      String(question?.answer_text || question?.answerText || question?.user_answer || question?.userAnswer || "").trim(),
  );
  if (hasExplicitUserAnswer) {
    return true;
  }
  const negativeStatuses = new Set([
    "unanswered",
    "not_answered",
    "pending",
    "missing",
    "empty",
    "unresolved",
    "todo",
    "unconfirmed",
  ]);
  if (
    negativeStatuses.has(normalizedStatus) ||
    normalizedStatus.includes("unanswered") ||
    normalizedStatus.includes("not_answered")
  ) {
    return false;
  }
  const positiveStatuses = new Set([
    "answered",
    "saved",
    "confirmed",
    "complete",
    "completed",
    "resolved",
    "user_answered",
    "answer_saved",
  ]);
  return Boolean(positiveStatuses.has(normalizedStatus));
}

function storySetupQuestionAnswerText(question) {
  return String(
    question?.answer_text ||
    question?.answerText ||
      question?.user_answer ||
      question?.userAnswer ||
      "",
  ).trim();
}

function extractActionLocalContext(action, sourceTarget, form) {
  const refs = { ...(action?.localContext || {}) };
  const nextForm = {};
  if (action?.actionId !== "storySetup.answerQuestion" || !sourceTarget?.closest) {
    return { refs, form: nextForm };
  }

  const button = sourceTarget.closest(".mini-save");
  const questionCard =
    sourceTarget.closest(".question") ||
    button?.closest?.(".question") ||
    sourceTarget.closest("[data-story-setup-question-id]") ||
    button?.closest?.("[data-story-setup-question-id]");
  const questionId =
    action?.localContext?.storySetupQuestionId ||
    button?.dataset?.storySetupQuestionId ||
    questionCard?.dataset?.storySetupQuestionId ||
    form?.storySetupQuestionId ||
    "";
  const answerInput =
    questionCard?.querySelector?.(".answer-input") ||
    button?.parentElement?.querySelector?.(".answer-input") ||
    null;
  const answerText = answerInput?.value ?? form?.answerText ?? "";

  if (questionId) {
    refs.storySetupQuestionId = questionId;
    nextForm.storySetupQuestionId = questionId;
  }
  nextForm.answerText = answerText;
  return { refs, form: nextForm };
}

function injectBridgeStyle(doc) {
  if (doc.getElementById("mafs-bridge-style")) {
    return;
  }
  const style = doc.createElement("style");
  style.id = "mafs-bridge-style";
  style.textContent = `
    html,
    body {
      overflow-y: auto !important;
    }
    .mafs-bridge-toast {
      position: fixed;
      right: 24px;
      bottom: 24px;
      z-index: 2147483647;
      max-width: min(420px, calc(100vw - 48px));
      border: 1px solid rgba(121, 89, 74, 0.24);
      border-radius: 12px;
      padding: 12px 14px;
      background: rgba(255, 252, 244, 0.94);
      box-shadow: 0 18px 48px rgba(67, 52, 40, 0.18);
      color: #2d2823;
      font: 700 13px/1.55 "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Arial, sans-serif;
      letter-spacing: 0;
      backdrop-filter: blur(12px);
    }
    .mafs-bridge-toast[data-tone="error"] {
      border-color: rgba(151, 71, 61, 0.34);
      color: #5b2b25;
    }
    .mafs-bridge-toast[data-tone="success"] {
      border-color: rgba(93, 113, 91, 0.32);
      color: #2f4435;
    }
    .mafs-action-busy [data-mafs-interactive="true"] {
      pointer-events: none;
      opacity: 0.72;
    }
    .mafs-empty-suppressed {
      display: none !important;
    }
    .mafs-backend-rendered {
      font-style: normal !important;
    }
    [data-mafs-backend-gate="pending"] {
      cursor: wait !important;
      opacity: 0.62 !important;
    }
  `;
  doc.head?.appendChild(style);
}

function showFrameMessage(doc, message, tone = "neutral") {
  if (!doc?.body || !message) {
    return;
  }
  injectBridgeStyle(doc);
  let toast = doc.getElementById("mafs-bridge-toast");
  if (!toast) {
    toast = doc.createElement("div");
    toast.id = "mafs-bridge-toast";
    toast.className = "mafs-bridge-toast";
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");
    doc.body.appendChild(toast);
  }
  toast.dataset.tone = tone;
  toast.textContent = message;
  window.clearTimeout(toast._mafsTimer);
  toast._mafsTimer = window.setTimeout(() => {
    toast?.remove();
  }, tone === "error" ? 6500 : 2600);
}

function setFrameBusy(doc, busy) {
  doc?.body?.classList?.toggle("mafs-action-busy", Boolean(busy));
}

function isUserFacingResultText(text) {
  if (!text) {
    return false;
  }
  const normalized = String(text).trim();
  if (!normalized || /^[-\w]{16,}$/.test(normalized) || /^https?:\/\//i.test(normalized)) {
    return false;
  }
  return ![
    /^Product workbench/i,
    /^Open or inspect project shells/i,
    /^Create a project shell/i,
    /^Draft proposes project shell/i,
    /does not confirm story facts/i,
    /evidence is represented/i,
    /record count only/i,
    /^Active project selection/i,
    /^Project creation request for /i,
    /^Project .* is classified as /i,
    /^prompt_input_sha256:/i,
    /^phase[_-]/i,
    /^multiple-agent-for-stories-backend$/i,
  ].some((pattern) => pattern.test(normalized));
}

function collectResultValues(value, output = []) {
  if (output.length >= 80 || value === null || value === undefined) {
    return output;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    const text = String(value).trim();
    if (isUserFacingResultText(text)) {
      output.push(text.length > 120 ? `${text.slice(0, 120)}...` : text);
    }
    return output;
  }
  if (Array.isArray(value)) {
    value.slice(0, 4).forEach((item) => collectResultValues(item, output));
    return output;
  }
  if (typeof value === "object") {
    [
      "title",
      "requested_title",
      "display_name",
      "summary",
      "scope",
      "tone",
      "world_structure",
      "history_summary",
      "geography_summary",
      "culture_summary",
      "prose",
      "body",
      "format",
      "download_url",
      "project_title",
      "requested_title",
      "prompt_text",
      "progress_label",
      "active_workspace_id",
      "workspace_id",
      "completion_ratio",
      "chapter_count",
      "scene_count",
      "current_chapter_index",
      "current_scene_index",
      "readiness_status",
      "provider_type",
      "model_name",
      "display_name",
      "safe_summary",
      "issue_count",
      "blocking_count",
    ].forEach((key) => collectResultValues(value[key], output));
  }
  return output;
}

function backendEmptyText(result) {
  if (!result) {
    return "正在读取项目数据";
  }
  const health = result.health || result.action_result?.health || {};
  const status = health.status || result.status || result.action_result?.status || "";
  if (String(status).toLowerCase() === "ok") {
    return "暂无此项数据";
  }
  return "暂无此项数据";
}

function applyBackendResultState(doc, result) {
  if (!doc?.body || !result) {
    return;
  }
  const values = collectResultValues(result);
  const pendingNodes = Array.from(doc.querySelectorAll(".mafs-backend-pending, [data-mafs-backend-bound='true']")).filter(
    (element) =>
      !element.closest("[data-mafs-backend-rendered='true'], .mafs-backend-rendered") &&
      !element.closest("button, a, input, select, textarea, option, [role='button'], [role='tab']"),
  );
  if (!pendingNodes.length) {
    return;
  }
  const fallback = "暂无此项数据";
  let emptyCount = 0;
  pendingNodes.forEach((element, index) => {
    const boundIndex = Number(element.dataset.mafsBackendSlot);
    const valueIndex = Number.isFinite(boundIndex) ? boundIndex : index;
    const value = values[valueIndex] || "";
    if (value) {
      element.textContent = value;
      element.classList.remove("mafs-empty-suppressed");
    } else {
      emptyCount += 1;
      element.textContent = emptyCount <= 2 ? fallback : "";
      element.classList.toggle("mafs-empty-suppressed", emptyCount > 2);
    }
    element.dataset.mafsBackendBound = "true";
    element.dataset.mafsBackendSlot = String(valueIndex);
    element.classList.remove("mafs-backend-pending");
    delete element.dataset.backendPending;
  });
}

function findNestedObject(value, predicate, depth = 0) {
  if (value === null || value === undefined || depth > 8) {
    return null;
  }
  if (typeof value !== "object") {
    return null;
  }
  if (predicate(value)) {
    return value;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findNestedObject(item, predicate, depth + 1);
      if (found) {
        return found;
      }
    }
    return null;
  }
  for (const item of Object.values(value)) {
    const found = findNestedObject(item, predicate, depth + 1);
    if (found) {
      return found;
    }
  }
  return null;
}

function findStorySetupDraftBundle(result) {
  return findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.world_canvas_draft_suggestion ||
          item?.worldCanvasDraftSuggestion ||
          item?.main_cast_draft_direction ||
          item?.mainCastDraftDirection ||
          item?.framework_setup_suggestion ||
          item?.frameworkSetupSuggestion ||
          item?.chapter_route_suggestion ||
          item?.chapterRouteSuggestion,
      ),
  );
}

function findStorySetupQuestions(result) {
  const container = findNestedObject(result, (item) => {
    const questions = item?.story_setup_questions || item?.storySetupQuestions || item?.questions;
    return Array.isArray(questions) && questions.some((question) => question?.question_text || question?.questionText);
  });
  if (!container) {
    return [];
  }
  return container.story_setup_questions || container.storySetupQuestions || container.questions || [];
}

function storySetupFieldLabel(key) {
  const labels = {
    world_scope: "世界范围",
    tone_candidates: "基调候选",
    hard_rule_candidates: "硬规则候选",
    soft_rule_candidates: "软规则候选",
    unknown_logic_gaps: "待确认缺口",
    potential_conflict: "核心冲突",
    main_cast_size: "主角团规模",
    protagonist_function: "主角功能",
    desire_direction: "角色欲望方向",
    opposing_force_direction: "对抗压力方向",
    relationship_tension_direction: "关系张力方向",
    macro_framework_shape: "全局骨架",
    chapter_count_range: "章节范围",
    conflict_escalation_path: "冲突推进",
    reversal_crisis_climax_direction: "转折与高潮",
    constraint_strength_suggestion: "约束强度",
    genre_tags: "类型信号",
    route_type: "路线类型",
    chapter_route: "章节路线",
    length_hint: "篇幅提示",
    notes: "备注",
    prompt_signal_summary: "输入信号",
    detected_key_terms: "关键词",
  };
  return labels[key] || String(key || "").replace(/_/g, " ");
}

function storySetupCodeLabel(value) {
  const labels = {
    world_scope_to_confirm: "世界范围待确认",
    focused_location_suggestion: "单一地点或局部区域",
    large_scope_suggestion: "大型世界范围",
    tone_to_confirm: "基调待确认",
    protagonist_function_to_confirm: "主角功能待确认",
    length_to_confirm: "篇幅待确认",
    small_to_medium_cast: "小到中型主角团",
    setup_escalation_crisis_resolution: "开端-升级-危机-解决",
    lightweight_macro_route: "轻量全局路线",
    opening_context: "开端与处境",
    pressure_and_discovery: "压力与发现",
    choice_and_consequence: "选择与后果",
    open_genre: "开放类型",
    medium: "中等",
    draft_suggestion: "草案建议",
    draft_direction: "方向草案",
    world_scope: "世界范围",
    tone: "基调",
    protagonist: "主角",
    core_conflict: "核心冲突",
    length_or_audience: "篇幅或读者定位",
    magic_or_rule_system: "规则系统",
    technology_or_speculative_rule: "技术或异常规则",
    relationship_focus: "关系焦点",
    information_release: "信息释放",
    single_location: "单一地点",
    city_or_region: "城市或区域",
    large_world: "大型世界",
    serious: "严肃",
    warm: "温暖",
    dark: "偏暗",
    light: "轻快",
    seeker: "追寻者",
    protector: "守护者",
    witness: "见证者",
    disruptor: "破局者",
    external_threat: "外部威胁",
    moral_choice: "道德选择",
    mystery: "谜团",
    relationship_pressure: "关系压力",
    short_story: "短篇",
    novella: "中篇",
    multi_chapter: "多章节",
    young_adult: "青少年读者",
    young_protagonist_function_suggestion: "年轻/核心主角功能建议",
    sci_fi_suspense: "科幻悬疑",
    cold_tech: "冷峻技术感",
    suspense: "悬疑",
    mystery_suspense: "悬疑",
    low_fantasy: "低魔",
    fantasy: "奇幻",
    xianxia: "仙侠",
    wuxia: "武侠",
    romance: "爱情",
    comedy: "喜剧",
    comedic: "喜剧",
    horror: "恐怖",
    crime: "犯罪",
    historical: "历史",
    campus: "校园",
    urban: "都市",
    slice_of_life: "日常",
    adventure: "冒险",
    adventurous: "冒险",
    war: "战争",
    romantic: "浪漫",
    epic: "史诗",
    healing: "治愈",
    tragic: "悲伤",
    satirical: "讽刺",
    speculative: "思辨",
    realistic: "现实",
    thriller: "惊悚",
    encounter_tension_choice_resolution: "相遇-张力-选择-结果",
    premise_discovery_escalation_consequence: "前提-发现-升级-后果",
    rule_reveal_trial_cost_transformation: "规则显影-试炼-代价-变化",
    clue_discovery_pressure_reversal_truth: "线索-压力-反转-真相",
    setup_misread_escalation_payoff: "误读-升级-回收",
    setup_escalation_choice_resolution: "开端-升级-选择-解决",
    unanswered: "未回答",
    answered: "已回答",
    pending: "待处理",
    confirmed: "已确认",
    ready: "已就绪",
    missing: "缺失",
    empty: "暂无交接",
    controlled_prompt: "受控提示词",
    prompt_first: "提示词优先",
    handoff_ready: "交接已就绪",
    world_canvas_workspace: "世界画布工作台",
  };
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const dynamicPrefixes = [
    ["Controlled prompt conflict signals:", "输入中检测到的冲突信号"],
    ["Controlled prompt signals detected:", "输入中检测到的具体信号"],
    ["Preserve prompt signals:", "保留输入信号"],
    ["named_protagonist_suggestion:", "主角线索"],
    ["pressure:", "压力"],
  ];
  for (const [prefix, label] of dynamicPrefixes) {
    if (text.startsWith(prefix)) {
      const rest = text.slice(prefix.length).trim();
      return rest ? `${label}：${storySetupCodeLabel(rest)}` : label;
    }
  }
  const sentenceLabels = {
    "Clarify protagonist desire in Character workspace.": "在角色主轴中确认主角欲望。",
    "Define opposing pressure after World Canvas review.": "在世界画布审阅后确认对抗压力。",
    "Keep relationship facts unconfirmed until Character workspace.": "关系事实留到角色工作台再确认。",
    "No hard rule is confirmed in M3.": "当前未直接确认硬规则。",
    "No hard rule is confirmed by Story Setup bootstrap.": "故事设定交接尚未确认硬规则，请在世界画布中确认技术、异常与代价边界。",
    "Draft initialized from Story Setup; confirm details in World Canvas.": "已从故事设定草案初始化，请在世界画布中确认具体历史。",
    "Draft initialized from Story Setup; locations are not confirmed yet.": "地点尚未确认，请根据项目前提补全主要区域与边界。",
    "Draft initialized from Story Setup; culture and factions are not confirmed yet.": "文化、组织与势力尚未确认，请在世界画布中补全。",
    "Confirm World Canvas before character, framework, chapter, or scene generation.": "请先确认世界画布，再进入角色、Framework、章节和场景生成。",
    "This is not a confirmed ChapterRoute. It is a StorySetup suggestion for Chapter Planning.": "这还不是正式章节路线，需要在章节计划工作台确认。",
    "prompt remains a seed, not final canon.": "用户输入仍是创作种子，不直接写入最终事实。",
  };
  return labels[text] || sentenceLabels[text] || text.replace(/_/g, " ");
}

function displayStorySetupCodeToken(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const label = storySetupCodeLabel(text);
  return label && label !== text.replace(/_/g, " ") ? label : text;
}

function worldCanvasReadableText(value) {
  let text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "";
  }
  const direct = storySetupCodeLabel(text);
  if (direct && direct !== text.replace(/_/g, " ")) {
    text = direct;
  }
  text = text
    .replace(
      /Draft initialized from Story Setup; confirm details in World Canvas\./g,
      "已从故事设定草案初始化，请在世界画布中确认具体历史。",
    )
    .replace(
      /Draft initialized from Story Setup; locations are not confirmed yet\./g,
      "地点尚未确认，请根据项目前提补全主要区域与边界。",
    )
    .replace(
      /Draft initialized from Story Setup; culture and factions are not confirmed yet\./g,
      "文化、组织与势力尚未确认，请在世界画布中补全。",
    )
    .replace(
      /No hard rule is confirmed by Story Setup bootstrap\./g,
      "故事设定交接尚未确认硬规则，请在世界画布中确认技术、异常与代价边界。",
    )
    .replace(
      /Confirm World Canvas before character, framework, chapter, or scene generation\./g,
      "请先确认世界画布，再进入角色、Framework、章节和场景生成。",
    )
    .replace(/Controlled prompt conflict signals:\s*/g, "输入中检测到的冲突信号：")
    .replace(/Controlled prompt signals detected:\s*/g, "输入中检测到的具体信号：")
    .replace(/Preserve prompt signals:\s*/g, "保留输入信号：")
    .replace(/;\s*pressure:\s*/g, "；压力：")
    .replace(/\bpressure:\s*/g, "压力：")
    .replace(/\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b/g, (match) => displayStorySetupCodeToken(match))
    .replace(
      /\b(speculative|adventurous|suspense|mystery|serious|dark|warm|light|romantic|comedic|horror|thriller|tragic|satirical|epic|healing)\b/g,
      (match) => displayStorySetupCodeToken(match),
    );
  return text;
}

function formatStorySetupValue(value) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map((item) => formatStorySetupValue(item)).filter(Boolean).join("、");
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${storySetupFieldLabel(key)}：${formatStorySetupValue(item)}`)
      .filter((item) => !item.endsWith("："))
      .join("；");
  }
  return storySetupCodeLabel(value);
}

function fieldLines(source, keys, limit = 4) {
  return keys
    .map((key) => {
      const text = formatStorySetupValue(source?.[key]);
      return text ? `${storySetupFieldLabel(key)}：${text}` : "";
    })
    .filter(Boolean)
    .slice(0, limit);
}

function buildStorySetupModuleData(draftBundle) {
  if (!draftBundle) {
    return null;
  }
  const world = draftBundle.world_canvas_draft_suggestion || draftBundle.worldCanvasDraftSuggestion || {};
  const cast = draftBundle.main_cast_draft_direction || draftBundle.mainCastDraftDirection || {};
  const framework = draftBundle.framework_setup_suggestion || draftBundle.frameworkSetupSuggestion || {};
  const chapters = draftBundle.chapter_route_suggestion || draftBundle.chapterRouteSuggestion || {};

  return {
    world: {
      eyebrow: "世界画布草案",
      title: "世界画布建议",
      summary: fieldLines(world, ["world_scope", "tone_candidates", "potential_conflict"], 3).join("；") || draftBundle.safe_summary || "后端已生成世界画布候选方向。",
      badge: world.requires_confirmation === false ? "可直接采用" : "需下游确认",
      source: "故事设定草案",
      target: "世界画布",
      keep: fieldLines(world, ["hard_rule_candidates", "soft_rule_candidates", "detected_key_terms"], 3),
      confirm: fieldLines(world, ["unknown_logic_gaps", "world_scope", "tone_candidates"], 3),
    },
    cast: {
      eyebrow: "角色方向草案",
      title: "角色方向",
      summary: fieldLines(cast, ["main_cast_size", "protagonist_function", "desire_direction"], 3).join("；") || "后端已生成角色主轴候选方向。",
      badge: cast.requires_confirmation === false ? "可直接采用" : "方向草案",
      source: "故事设定草案",
      target: "角色主轴",
      keep: fieldLines(cast, ["main_cast_size", "protagonist_function", "opposing_force_direction"], 3),
      confirm: fieldLines(cast, ["desire_direction", "relationship_tension_direction"], 3),
    },
    framework: {
      eyebrow: "Framework 建议",
      title: "Framework 建议",
      summary: fieldLines(framework, ["macro_framework_shape", "conflict_escalation_path", "constraint_strength_suggestion"], 3).join("；") || "后端已生成全局叙事骨架候选方向。",
      badge: framework.requires_confirmation === false ? "可直接采用" : "可映射 Framework",
      source: "故事设定草案",
      target: "Framework",
      keep: fieldLines(framework, ["macro_framework_shape", "genre_tags", "constraint_strength_suggestion"], 3),
      confirm: fieldLines(framework, ["conflict_escalation_path", "reversal_crisis_climax_direction"], 3),
    },
    chapters: {
      eyebrow: "章节路线建议",
      title: "章节路线建议",
      summary: fieldLines(chapters, ["route_type", "chapter_route", "length_hint"], 3).join("；") || "后端已生成章节路线候选方向。",
      badge: chapters.requires_confirmation === false ? "可直接采用" : "章节候选",
      source: "故事设定草案",
      target: "章节计划",
      keep: fieldLines(chapters, ["chapter_route", "length_hint"], 3),
      confirm: fieldLines(chapters, ["notes"], 2),
    },
  };
}

function markBackendRendered(element) {
  if (!element) {
    return;
  }
  element.dataset.mafsBackendRendered = "true";
  element.dataset.mafsBackendBound = "true";
  element.classList.add("mafs-backend-rendered");
  element.classList.remove("mafs-backend-pending", "mafs-empty-suppressed");
  delete element.dataset.backendPending;
}

function setRenderedText(element, text) {
  if (!element || !text) {
    return;
  }
  element.textContent = text;
  markBackendRendered(element);
}

function bindBackendActionElement(element, actionId = "", targetPage = "") {
  if (!element) {
    return;
  }
  if (actionId) {
    element.dataset.mafsActionId = actionId;
  }
  if (targetPage) {
    element.dataset.mafsTarget = targetPage;
  }
  element.dataset.mafsInteractive = "true";
  markBackendRendered(element);
}

function setActionPhase(doc, phase) {
  const view = doc?.defaultView;
  if (!view) {
    return;
  }
  view.__mafsActionPhase = phase;
}

function setActionForm(doc, form) {
  const view = doc?.defaultView;
  if (!view) {
    return;
  }
  view.__mafsActionForm = form;
}

function setLastAction(doc, actionName) {
  const view = doc?.defaultView;
  if (!view) {
    return;
  }
  view.__mafsLastAction = actionName || "";
}

function findNestedArray(value, keys, depth = 0) {
  if (value === null || value === undefined || depth > 8) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value !== "object") {
    return [];
  }
  for (const key of keys) {
    if (Array.isArray(value[key])) {
      return value[key];
    }
  }
  for (const child of Object.values(value)) {
    const found = findNestedArray(child, keys, depth + 1);
    if (found.length) {
      return found;
    }
  }
  return [];
}

function findNestedObjectByKeys(value, keys, depth = 0) {
  if (value === null || value === undefined || depth > 8 || typeof value !== "object") {
    return null;
  }
  if (Array.isArray(value)) {
    for (const child of value) {
      const found = findNestedObjectByKeys(child, keys, depth + 1);
      if (found) {
        return found;
      }
    }
    return null;
  }
  for (const key of keys) {
    if (value[key] && typeof value[key] === "object" && !Array.isArray(value[key])) {
      return value[key];
    }
  }
  for (const child of Object.values(value)) {
    const found = findNestedObjectByKeys(child, keys, depth + 1);
    if (found) {
      return found;
    }
  }
  return null;
}

function projectStatusLabel(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized.includes("complete") || normalized.includes("final")) {
    return "已完成";
  }
  if (normalized.includes("archive")) {
    return "归档";
  }
  if (normalized.includes("pause")) {
    return "暂停";
  }
  return "进行中";
}

function projectNextLabel(step) {
  const normalized = String(step || "").toLowerCase();
  if (normalized.includes("world")) {
    return "继续世界画布";
  }
  if (normalized.includes("character") || normalized.includes("role")) {
    return "继续角色主轴";
  }
  if (normalized.includes("framework") || normalized.includes("chapter")) {
    return "继续章节计划";
  }
  if (normalized.includes("scene") || normalized.includes("writing")) {
    return "继续场景写作";
  }
  if (normalized.includes("final") || normalized.includes("export")) {
    return "查看最终输出";
  }
  return "继续故事设定";
}

function projectProgress(step, status) {
  const normalized = `${step || ""} ${status || ""}`.toLowerCase();
  if (normalized.includes("final") || normalized.includes("complete")) {
    return 100;
  }
  if (normalized.includes("scene") || normalized.includes("writing")) {
    return 78;
  }
  if (normalized.includes("chapter") || normalized.includes("framework")) {
    return 58;
  }
  if (normalized.includes("character") || normalized.includes("role")) {
    return 42;
  }
  if (normalized.includes("world")) {
    return 30;
  }
  return 18;
}

function projectStageFlags(progress) {
  return [15, 30, 42, 58, 78].map((threshold) => progress >= threshold);
}

function formatProjectTime(value) {
  if (!value) {
    return "最近更新";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value).slice(0, 16);
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function normalizeProjectCard(project) {
  const title = String(project?.title || project?.requested_title || project?.project_title || "未命名故事").trim();
  const status = project?.status || "";
  const step = project?.current_step || project?.currentStep || "";
  const progress = projectProgress(step, status);
  const next = projectNextLabel(step);
  const summary = firstNonEmpty(
    project?.summary,
    project?.safe_summary,
    project?.description,
    `当前项目位于「${next.replace(/^继续/, "")}」阶段。`,
  );
  return {
    id: project?.project_id || project?.projectId || project?.id || title,
    title,
    status,
    statusLabel: projectStatusLabel(status),
    updated: formatProjectTime(project?.updated_at || project?.updatedAt || project?.created_at || project?.createdAt),
    stage: next.replace(/^继续/, ""),
    next,
    progress,
    summary,
    meta: [
      project?.origin_type || project?.originType || "story",
      project?.language || "zh",
      step || "story_setup",
    ].filter(Boolean),
    stages: projectStageFlags(progress),
    notes: [
      ["最近", `状态：${status || "进行中"}`],
      ["草稿", `当前步骤：${step || "故事设定"}`],
      ["下一步", next],
    ],
  };
}

function renderProjectsSurface(doc, result) {
  const cards = doc.querySelector("#cards");
  const detailTitle = doc.querySelector("#detail-title");
  const detailSummary = doc.querySelector("#detail-summary");
  if (!cards || !detailTitle || !detailSummary) {
    return false;
  }
  const rawProjects = findNestedArray(result, ["projects", "items", "records"]).filter((item) => item && typeof item === "object");
  if (!rawProjects.length) {
    return false;
  }
  const projects = rawProjects
    .map(normalizeProjectCard)
    .sort((a, b) => String(b.updated || "").localeCompare(String(a.updated || ""), "zh-CN"));
  let selectedId = doc.body.dataset.mafsSelectedProjectId || projects[0].id;

  const renderDetail = (project) => {
    const selected = project || projects.find((item) => item.id === selectedId) || projects[0];
    selectedId = selected.id;
    doc.body.dataset.mafsSelectedProjectId = selected.id;
    setRenderedText(detailTitle, selected.title);
    setRenderedText(detailSummary, selected.summary);
    setRenderedText(doc.querySelector("#continue-button"), selected.next);
    const stageLine = doc.querySelector("#stage-line");
    if (stageLine) {
      stageLine.innerHTML = "";
      ["项目", "设定", "世界", "角色", "写作"].forEach((label, index) => {
        const row = doc.createElement("div");
        row.className = `stage ${selected.stages[index] ? "done" : ""}`;
        const dot = doc.createElement("span");
        dot.className = "stage-dot";
        dot.textContent = String(index + 1);
        const text = doc.createElement("span");
        text.textContent = label;
        row.append(dot, text);
        stageLine.appendChild(row);
      });
      markBackendRendered(stageLine);
    }
    const noteList = doc.querySelector("#note-list");
    if (noteList) {
      noteList.innerHTML = "";
      selected.notes.forEach(([key, value]) => {
        const note = doc.createElement("div");
        note.className = "note";
        const strong = doc.createElement("strong");
        strong.textContent = key;
        const span = doc.createElement("span");
        span.textContent = value;
        note.append(strong, span);
        noteList.appendChild(note);
      });
      markBackendRendered(noteList);
    }
  };

  cards.innerHTML = "";
  projects.slice(0, 12).forEach((project) => {
    const card = doc.createElement("button");
    card.type = "button";
    card.className = `project-card ${project.id === selectedId ? "selected" : ""}`;
    card.dataset.id = project.id;
    const top = doc.createElement("div");
    const cardTop = doc.createElement("div");
    cardTop.className = "card-top";
    const title = doc.createElement("h2");
    title.className = "project-title";
    title.textContent = project.title;
    const status = doc.createElement("span");
    status.className = "status";
    status.textContent = project.statusLabel;
    cardTop.append(title, status);
    const summary = doc.createElement("p");
    summary.className = "summary";
    summary.textContent = project.summary;
    const metaRow = doc.createElement("div");
    metaRow.className = "meta-row";
    project.meta.slice(0, 3).forEach((item) => {
      const meta = doc.createElement("span");
      meta.className = "meta";
      meta.textContent = item;
      metaRow.appendChild(meta);
    });
    top.append(cardTop, summary, metaRow);
    const bottom = doc.createElement("div");
    const bottomMeta = doc.createElement("div");
    bottomMeta.className = "meta-row";
    [project.updated, project.next].forEach((item) => {
      const meta = doc.createElement("span");
      meta.className = "meta";
      meta.textContent = item;
      bottomMeta.appendChild(meta);
    });
    const progress = doc.createElement("div");
    progress.className = "progress";
    const fill = doc.createElement("span");
    fill.style.width = `${project.progress}%`;
    progress.appendChild(fill);
    bottom.append(bottomMeta, progress);
    card.append(top, bottom);
    card.addEventListener("click", () => {
      Array.from(cards.querySelectorAll(".project-card")).forEach((item) => item.classList.remove("selected"));
      card.classList.add("selected");
      renderDetail(project);
    });
    cards.appendChild(card);
  });
  markBackendRendered(cards);
  setRenderedText(doc.querySelector("#result-sub"), `${projects.length} 个故事档案`);
  setRenderedText(doc.querySelector("#result-title"), "最近继续");
  renderDetail(projects.find((item) => item.id === selectedId) || projects[0]);
  return true;
}

function findWorldCanvasPayload(result) {
  const candidates = [
    result?.world_canvas?.world_canvas,
    result?.worldCanvas?.worldCanvas,
    result?.world_canvas,
    result?.worldCanvas,
    result?.action_result?.world_canvas?.world_canvas,
    result?.action_result?.world_canvas,
    result?.project_data?.world_canvas,
    result?.projectData?.worldCanvas,
  ];
  for (const candidate of candidates) {
    if (
      candidate &&
      typeof candidate === "object" &&
      (candidate.world_canvas_id ||
        candidate.worldCanvasId ||
        candidate.story_direction ||
        candidate.storyDirection ||
        candidate.world_structure ||
        candidate.worldStructure ||
        candidate.history_summary ||
        candidate.historySummary ||
        candidate.scope ||
        candidate.tone)
    ) {
      return candidate;
    }
  }
  return findNestedObject(
    result,
    (item) =>
      Boolean(
        (item?.world_canvas_id || item?.worldCanvasId) &&
          (item?.story_direction ||
            item?.storyDirection ||
            item?.world_structure ||
            item?.worldStructure ||
            item?.history_summary ||
            item?.historySummary ||
            item?.scope ||
            item?.tone),
      ),
  );
}

function worldCanvasText(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(worldCanvasText).filter(Boolean).join("；");
  }
  if (typeof value === "object") {
    return firstNonEmpty(
      value.statement,
      value.summary,
      value.description,
      value.content,
      value.text,
      value.value,
      value.label,
      value.name,
      value.title,
      value.detail,
      value.rationale,
      value.why_it_matters,
      value.whyItMatters,
      value.suggested_fix,
      value.suggestedFix,
    );
  }
  return String(value).trim();
}

const INTERNAL_WORLD_CANVAS_PROMPT_PATTERN =
  /ProjectStoryPremise is authoritative|Prompt-first project|User story premise:|ProjectStoryPremise:|项目前提锚点[:：]/i;

function isInternalWorldCanvasPromptText(value) {
  return INTERNAL_WORLD_CANVAS_PROMPT_PATTERN.test(String(value || ""));
}

function compactWorldCanvasDisplayText(value, fallback = "", maxLength = 180) {
  const rawText = worldCanvasText(value).replace(/\s+/g, " ").trim();
  const text = worldCanvasReadableText(rawText);
  if (!text) {
    return fallback;
  }
  if (isInternalWorldCanvasPromptText(rawText)) {
    return fallback;
  }
  if (maxLength > 0 && text.length > maxLength) {
    return `${text.slice(0, maxLength).trim()}...`;
  }
  return text;
}

function worldCanvasPromptInputText(value, fallback = "") {
  let text = worldCanvasText(value).trim();
  if (!text) {
    return fallback;
  }
  if (isInternalWorldCanvasPromptText(text)) {
    const userPremiseMatch = text.match(/User story premise:\s*([\s\S]*)/i);
    text = userPremiseMatch ? userPremiseMatch[1] : text;
    text = text
      .replace(/^ProjectStoryPremise:\s*/i, "")
      .replace(/项目前提锚点[:：][\s\S]*$/g, "")
      .trim();
  }
  return text || fallback;
}

function worldCanvasDisplayText(value, fallback = "", maxLength = 180) {
  const cleaned = worldCanvasPromptInputText(value, "");
  return compactWorldCanvasDisplayText(cleaned || value, fallback, maxLength);
}

const WORLD_CANVAS_PROMPT_SECTION_HEADINGS = [
  "篇幅结构",
  "题材定位",
  "核心故事",
  "故事表层是志怪公案，深层主题是",
  "必须保留并反复吸收的故事标记词",
  "时代与地点",
  "世界硬规则",
  "角色结构要求",
  "关系压力",
  "章节方向",
  "每章 8 幕的基本节奏",
  "每章8幕的基本节奏",
  "正文风格",
  "最终目标",
];

function escapeRegExpText(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function worldCanvasPromptSourceText(world, rawDirection = "") {
  return worldCanvasPromptInputText(
    firstNonEmpty(
      world?.source_story_idea,
      world?.sourceStoryIdea,
      world?.story_direction,
      world?.storyDirection,
      rawDirection,
    ),
    "",
  ).replace(/\s+/g, " ").trim();
}

function extractWorldCanvasPromptSection(promptText, headings, maxLength = 260) {
  const source = String(promptText || "").trim();
  if (!source) {
    return "";
  }
  const headingList = Array.isArray(headings) ? headings : [headings];
  for (const heading of headingList) {
    const match = new RegExp(`${escapeRegExpText(heading)}\\s*[:：]`).exec(source);
    if (!match) {
      continue;
    }
    const start = match.index + match[0].length;
    let end = source.length;
    WORLD_CANVAS_PROMPT_SECTION_HEADINGS.forEach((candidate) => {
      if (candidate === heading) {
        return;
      }
      const rest = source.slice(start);
      const stopMatch = new RegExp(`\\s${escapeRegExpText(candidate)}\\s*[:：]`).exec(rest);
      if (stopMatch && stopMatch.index >= 0) {
        end = Math.min(end, start + stopMatch.index);
      }
    });
    const extracted = compactWorldCanvasDisplayText(source.slice(start, end), "", maxLength);
    if (extracted) {
      return extracted;
    }
  }
  return "";
}

function trimPromptSentence(value, maxLength = 260) {
  return compactWorldCanvasDisplayText(String(value || "").replace(/\s+/g, " ").trim(), "", maxLength);
}

function extractPromptMatch(promptText, patterns, maxLength = 260) {
  const source = String(promptText || "").replace(/\s+/g, " ").trim();
  for (const pattern of patterns) {
    const match = pattern.exec(source);
    if (match?.[1]) {
      return trimPromptSentence(match[1], maxLength);
    }
  }
  return "";
}

function inferWorldCanvasPromptSections(promptText) {
  const source = String(promptText || "").replace(/\s+/g, " ").trim();
  if (!source) {
    return {};
  }
  const title = extractPromptMatch(source, [/暂定名[《“"]?([^》。；;，,"]+)/, /名为[《“"]?([^》。；;，,"]+)/], 80);
  const scope = extractPromptMatch(
    source,
    [
      /背景是([^。；;]+)/,
      /发生在([^。；;]+)/,
      /舞台是([^。；;]+)/,
      /地点是([^。；;]+)/,
      /世界设定(?:为|是)?([^。；;]+)/,
    ],
    180,
  );
  const cast = extractPromptMatch(source, [/主角是([^。；;]+)/, /主角包括([^。；;]+)/, /主角为([^。；;]+)/], 180);
  const coreStory = extractPromptMatch(
    source,
    [/故事围绕([^。]+)/, /故事核心是([^。]+)/, /主线是([^。]+)/, /讲述([^。]+)/],
    260,
  );
  const rules = extractPromptMatch(
    source,
    [/世界规则[:：]\s*([^。]+)/, /规则[:：]\s*([^。]+)/, /硬规则[:：]\s*([^。]+)/],
    360,
  );
  const length = extractPromptMatch(
    source,
    [/全书共([^。；;]+)/, /共\s*([0-9一二三四五六七八九十]+章[^。；;]*)/, /([0-9一二三四五六七八九十]+章[0-9一二三四五六七八九十]+幕)/],
    120,
  );
  const genreTerms = ["科幻", "悬疑", "奇幻", "低魔", "仙侠", "武侠", "历史", "传奇", "爱情", "喜剧", "恐怖", "犯罪", "都市", "校园", "冒险", "战争", "治愈", "悲剧", "现实", "志怪", "公案"];
  const genre = genreTerms.filter((term) => source.includes(term)).slice(0, 4).join("、");
  const pressure = extractPromptMatch(
    source,
    [/围绕[^。]*?(权力斗争[^。]*)/, /(身份边界[^。]*)/, /(冲突[^。；;]*)/, /(事故[^。；;]*)/],
    180,
  );
  const markers = Array.from(
    new Set([title, scope, cast, coreStory, rules].join(" ").match(/[\u4e00-\u9fa5A-Za-z0-9]{2,}/g) || []),
  )
    .filter((item) => !/我想|创作|一部|故事|全书|总计|生成|维护/.test(item))
    .slice(0, 8)
    .join("、");
  return {
    title,
    scope,
    setting: scope,
    genre,
    coreStory: firstNonEmpty(coreStory, pressure),
    markers,
    rules,
    relationships: firstNonEmpty(pressure, cast),
    chapters: length,
    finalGoal: firstNonEmpty(coreStory, rules),
    culture: firstNonEmpty(pressure, cast),
  };
}

function isGenericWorldCanvasFallbackText(value) {
  const text = worldCanvasText(value).replace(/\s+/g, " ").trim();
  if (!text) {
    return true;
  }
  return /项目前提指定的核心舞台|项目前提世界|围绕项目前提建立最小可运行世界结构|关键历史事实必须从项目前提|主要地点以项目前提|社会关系、组织压力和日常秩序需要服务项目前提|所有特殊现象都必须有触发条件|后续用户确认|模板故事|格式降级路径|确定性草稿兜底|核心舞台待确认|世界范围待用户/.test(text);
}

function worldCanvasSpecificText(primary, promptFallback, genericFallback = "", maxLength = 220) {
  const primaryText = compactWorldCanvasDisplayText(primary, "", maxLength);
  if (primaryText && !isGenericWorldCanvasFallbackText(primaryText)) {
    return primaryText;
  }
  const promptText = compactWorldCanvasDisplayText(promptFallback, "", maxLength);
  return promptText || primaryText || genericFallback;
}

function buildWorldCanvasPromptDerivedSections(world, rawDirection = "") {
  const promptText = worldCanvasPromptSourceText(world, rawDirection);
  const inferred = inferWorldCanvasPromptSections(promptText);
  const genre = extractWorldCanvasPromptSection(promptText, "题材定位", 260);
  const coreStory = extractWorldCanvasPromptSection(promptText, "核心故事", 320);
  const theme = extractWorldCanvasPromptSection(promptText, "故事表层是志怪公案，深层主题是", 260);
  const markers = extractWorldCanvasPromptSection(promptText, "必须保留并反复吸收的故事标记词", 180);
  const setting = extractWorldCanvasPromptSection(promptText, "时代与地点", 260);
  const rules = extractWorldCanvasPromptSection(promptText, "世界硬规则", 420);
  const relationships = extractWorldCanvasPromptSection(promptText, "关系压力", 260);
  const chapters = extractWorldCanvasPromptSection(promptText, "章节方向", 300);
  const finalGoal = extractWorldCanvasPromptSection(promptText, "最终目标", 220);

  return {
    source: compactWorldCanvasDisplayText(promptText, "", 420),
    genre: firstNonEmpty(genre, inferred.genre),
    coreStory: firstNonEmpty(coreStory, inferred.coreStory),
    theme,
    markers: firstNonEmpty(markers, inferred.markers),
    setting: firstNonEmpty(setting, inferred.setting),
    rules: firstNonEmpty(rules, inferred.rules),
    relationships: firstNonEmpty(relationships, inferred.relationships),
    chapters: firstNonEmpty(chapters, inferred.chapters),
    finalGoal: firstNonEmpty(finalGoal, inferred.finalGoal),
    scope: firstNonEmpty(setting, inferred.scope, coreStory, inferred.coreStory, markers, inferred.markers),
    tone: firstNonEmpty(genre, inferred.genre, theme, finalGoal, inferred.finalGoal),
    structure: firstNonEmpty(coreStory, inferred.coreStory, markers, inferred.markers, chapters, inferred.chapters),
    history: firstNonEmpty(coreStory, inferred.coreStory, chapters, inferred.chapters),
    geography: firstNonEmpty(setting, inferred.setting),
    culture: firstNonEmpty(relationships, inferred.culture, genre, inferred.genre, theme),
    specialRules: firstNonEmpty(rules, inferred.rules),
  };
}

function findStorySetupStatePayload(result) {
  const candidates = [
    result?.story_setup_state,
    result?.storySetupState,
    result?.action_result?.story_setup_state,
    result?.actionResult?.storySetupState,
    result?.action_result?.storySetupState,
  ];
  for (const candidate of candidates) {
    if (
      candidate &&
      typeof candidate === "object" &&
      (candidate.story_setup_draft_bundle ||
        candidate.storySetupDraftBundle ||
        candidate.story_setup_handoff ||
        candidate.storySetupHandoff ||
        candidate.story_setup_prompt ||
        candidate.storySetupPrompt)
    ) {
      return candidate;
    }
  }
  return findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.story_setup_draft_bundle ||
          item?.storySetupDraftBundle ||
          item?.story_setup_handoff ||
          item?.storySetupHandoff,
      ),
  );
}

function findStorySetupHandoffPayload(result) {
  const state = findStorySetupStatePayload(result) || {};
  const candidates = [
    result?.story_setup_handoff,
    result?.storySetupHandoff,
    result?.action_result?.story_setup_handoff,
    result?.actionResult?.storySetupHandoff,
    result?.action_result?.storySetupHandoff,
    state.story_setup_handoff,
    state.storySetupHandoff,
  ];
  for (const candidate of candidates) {
    if (
      candidate &&
      typeof candidate === "object" &&
      (candidate.story_setup_handoff_id ||
        candidate.storySetupHandoffId ||
        candidate.handoff_status ||
        candidate.handoffStatus ||
        candidate.target_workspace ||
        candidate.targetWorkspace)
    ) {
      return candidate;
    }
  }
  return findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.story_setup_handoff_id ||
          item?.storySetupHandoffId ||
          (item?.handoff_status && item?.target_workspace),
      ),
  );
}

function findProjectStoryPremiseResponse(result) {
  const candidates = [
    result?.story_premise,
    result?.storyPremise,
    result?.project_story_premise,
    result?.projectStoryPremise,
    result?.action_result?.story_premise,
    result?.actionResult?.storyPremise,
    result?.action_result?.project_story_premise,
    result?.actionResult?.projectStoryPremise,
  ];
  for (const candidate of candidates) {
    if (
      candidate &&
      typeof candidate === "object" &&
      (candidate.premise ||
        candidate.readiness ||
        candidate.safe_summary ||
        candidate.safeSummary ||
        candidate.source_refs ||
        candidate.sourceRefs)
    ) {
      return candidate;
    }
  }
  return findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.premise &&
          typeof item.premise === "object" &&
          (item.premise.user_story_premise || item.premise.safe_user_story_summary),
      ),
  );
}

function findProjectStoryPremisePayload(result) {
  const response = findProjectStoryPremiseResponse(result);
  const candidates = [
    response?.premise,
    result?.premise,
    result?.action_result?.premise,
    result?.actionResult?.premise,
  ];
  for (const candidate of candidates) {
    if (
      candidate &&
      typeof candidate === "object" &&
      (candidate.user_story_premise ||
        candidate.userStoryPremise ||
        candidate.safe_user_story_summary ||
        candidate.safeUserStorySummary ||
        candidate.required_story_elements ||
        candidate.requiredStoryElements)
    ) {
      return candidate;
    }
  }
  return findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.user_story_premise ||
          item?.userStoryPremise ||
          item?.safe_user_story_summary ||
          item?.safeUserStorySummary,
      ),
  );
}

function cleanPremiseDisplayText(value, fallback = "", maxLength = 220) {
  const text = worldCanvasPromptInputText(value, "");
  return compactWorldCanvasDisplayText(text, fallback, maxLength);
}

function uniqueDisplayValues(values, limit = 8) {
  const seen = new Set();
  const output = [];
  values.flat(Infinity).forEach((value) => {
    const text = cleanPremiseDisplayText(formatStorySetupValue(value), "", 90);
    if (!text || seen.has(text)) {
      return;
    }
    seen.add(text);
    output.push(text);
  });
  return output.slice(0, limit);
}

function buildWorldCanvasPremiseSourceData(result, world = null) {
  const state = findStorySetupStatePayload(result) || {};
  const handoff = findStorySetupHandoffPayload(result) || {};
  const draftBundle =
    findStorySetupDraftBundle(result) ||
    state.story_setup_draft_bundle ||
    state.storySetupDraftBundle ||
    {};
  const premiseResponse = findProjectStoryPremiseResponse(result) || {};
  const premise = findProjectStoryPremisePayload(result) || {};
  const prompt = state.story_setup_prompt || state.storySetupPrompt || result?.story_setup_prompt || result?.storySetupPrompt || {};
  const worldSuggestion = draftBundle.world_canvas_draft_suggestion || draftBundle.worldCanvasDraftSuggestion || {};
  const structure = world?.world_structure || world?.worldStructure || {};
  const location = Array.isArray(world?.locations) && world.locations.length ? world.locations[0] : {};
  const hasRealSource = Boolean(
    firstNonEmpty(
      premise.safe_user_story_summary,
      premise.safeUserStorySummary,
      premise.user_story_premise,
      premise.userStoryPremise,
      prompt.safe_prompt_summary,
      prompt.safePromptSummary,
      prompt.safe_summary,
      prompt.safeSummary,
      draftBundle.safe_summary,
      draftBundle.safeSummary,
      handoff.story_setup_handoff_id,
      handoff.storySetupHandoffId,
      world?.source_story_idea,
      world?.sourceStoryIdea,
      formatStorySetupValue(worldSuggestion.world_scope || worldSuggestion.worldScope),
      formatStorySetupValue(worldSuggestion.detected_key_terms || worldSuggestion.detectedKeyTerms),
    ),
  );

  const userPremise = cleanPremiseDisplayText(
    firstNonEmpty(
      premise.safe_user_story_summary,
      premise.safeUserStorySummary,
      premise.user_story_premise,
      premise.userStoryPremise,
      prompt.safe_prompt_summary,
      prompt.safePromptSummary,
      prompt.safe_summary,
      prompt.safeSummary,
      draftBundle.safe_summary,
      draftBundle.safeSummary,
      handoff.safe_summary,
      handoff.safeSummary,
      world?.source_story_idea,
      world?.sourceStoryIdea,
    ),
    "尚未接收到故事设定交接内容。请先在故事设定中确认并创建交接，再回到世界画布生成草案。",
    360,
  );
  const worldScope = cleanPremiseDisplayText(
    firstNonEmpty(
      formatStorySetupValue(worldSuggestion.world_scope || worldSuggestion.worldScope),
      world?.scope,
      structure.name,
      location.name,
      Array.isArray(premise.setting_terms || premise.settingTerms) ? (premise.setting_terms || premise.settingTerms).join("、") : "",
    ),
    "世界范围待用户在世界画布中确认。",
    160,
  );
  const tone = cleanPremiseDisplayText(
    firstNonEmpty(
      formatStorySetupValue(worldSuggestion.tone_candidates || worldSuggestion.toneCandidates),
      world?.tone,
      Array.isArray(premise.core_terms || premise.coreTerms) ? (premise.core_terms || premise.coreTerms).join("、") : "",
    ),
    "基调仍需在世界画布中确认。",
    140,
  );
  const conflict = cleanPremiseDisplayText(
    firstNonEmpty(
      formatStorySetupValue(worldSuggestion.potential_conflict || worldSuggestion.potentialConflict),
      Array.isArray(premise.conflict_terms || premise.conflictTerms) ? (premise.conflict_terms || premise.conflictTerms).join("、") : "",
      world?.story_direction,
      world?.storyDirection,
    ),
    "核心冲突待世界画布继续整理。",
    180,
  );
  const keyTerms = uniqueDisplayValues(
    [
      premise.core_terms || premise.coreTerms || [],
      premise.setting_terms || premise.settingTerms || [],
      premise.conflict_terms || premise.conflictTerms || [],
      premise.role_terms || premise.roleTerms || [],
      worldSuggestion.detected_key_terms || worldSuggestion.detectedKeyTerms || [],
      worldSuggestion.tone_candidates || worldSuggestion.toneCandidates || [],
    ],
    10,
  );
  const requiredElements = uniqueDisplayValues(
    [
      premise.required_story_elements || premise.requiredStoryElements || [],
      worldSuggestion.hard_rule_candidates || worldSuggestion.hardRuleCandidates || [],
      worldSuggestion.soft_rule_candidates || worldSuggestion.softRuleCandidates || [],
    ],
    6,
  );
  const unknownGaps = uniqueDisplayValues(
    [worldSuggestion.unknown_logic_gaps || worldSuggestion.unknownLogicGaps || premise.blocking_issues || premise.blockingIssues || []],
    5,
  );
  const readiness = premiseResponse.readiness || {};
  const handoffStatus = storySetupCodeLabel(
    handoff.handoff_status || handoff.handoffStatus || state.state_status || state.stateStatus || (hasRealSource ? "ready" : "missing"),
  );
  const sourceStatus = storySetupCodeLabel(readiness.source_status || readiness.sourceStatus || premise.source_status || premise.sourceStatus || "controlled_prompt");
  const writeScope = handoff.story_setup_handoff_id || handoff.storySetupHandoffId
    ? "仅创建世界画布草案，确认前不写入最终故事事实。"
    : "尚未找到故事设定交接记录，需先完成故事设定确认。";

  return {
    hasSource: hasRealSource,
    title: worldScope || "故事设定交接摘要",
    summary: userPremise,
    details: [
      ["世界范围", worldScope],
      ["基调", tone],
      ["核心冲突", conflict],
      ["关键素材", keyTerms.join("、") || "关键素材将在生成世界画布时继续抽取。"],
    ],
    contract: [
      ["来源状态", sourceStatus],
      ["交接状态", handoffStatus],
      ["目标工作台", storySetupCodeLabel(handoff.target_workspace || handoff.targetWorkspace || "world_canvas_workspace")],
      ["写入范围", writeScope],
    ],
    tags: keyTerms.length ? keyTerms : ["故事设定交接", "世界画布", "待确认边界"],
    requiredElements,
    unknownGaps,
    generateInput: cleanPremiseDisplayText(
      firstNonEmpty(
        premise.user_story_premise,
        premise.userStoryPremise,
        premise.safe_user_story_summary,
        premise.safeUserStorySummary,
        prompt.safe_prompt_summary,
        prompt.safePromptSummary,
        draftBundle.safe_summary,
        userPremise,
      ),
      userPremise,
      1200,
    ),
    meta: [
      ["来源", "故事设定交接"],
      ["一致性", (handoff.story_setup_handoff_id || handoff.storySetupHandoffId) ? "可用于生成" : "等待交接"],
      ["项目来源", sourceStatus || "提示词优先项目"],
      ["写入范围", "仅创建草案"],
    ],
  };
}

function renderWorldCanvasPremiseSource(doc, result, world = null) {
  if (!doc?.body || !doc.querySelector(".source-card, #summaryPanel, #storyIdea")) {
    return false;
  }
  const data = buildWorldCanvasPremiseSourceData(result, world);
  const summaryPanel = doc.getElementById("summaryPanel");
  if (summaryPanel) {
    const requiredList = data.requiredElements.length
      ? `<ul>${data.requiredElements.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
      : "";
    summaryPanel.innerHTML = `
      <h4>${escapeHtml(data.title || "故事设定交接摘要")}</h4>
      <p>${escapeHtml(data.summary)}</p>
      ${requiredList}
    `;
    markBackendRendered(summaryPanel);
  }

  const renderContractList = (target, rows) => {
    if (!target) {
      return;
    }
    target.innerHTML = "";
    rows.filter(([, value]) => Boolean(value)).forEach(([label, value]) => {
      const article = doc.createElement("article");
      const strong = doc.createElement("b");
      strong.textContent = label;
      const span = doc.createElement("span");
      span.textContent = value;
      article.append(strong, span);
      target.appendChild(article);
    });
    markBackendRendered(target);
  };

  renderContractList(doc.getElementById("termsPanel"), data.details);
  renderContractList(doc.getElementById("contractPanel"), data.contract);

  const tagList = doc.getElementById("tagList");
  if (tagList) {
    tagList.innerHTML = "";
    data.tags.slice(0, 8).forEach((tag) => {
      const span = doc.createElement("span");
      span.className = "tag";
      span.textContent = tag;
      tagList.appendChild(span);
    });
    markBackendRendered(tagList);
  }

  const metaItems = Array.from(doc.querySelectorAll(".source-meta .meta-item"));
  metaItems.forEach((item, index) => {
    const [label, value] = data.meta[index] || [];
    if (!label || !value) {
      return;
    }
    const labelNode = item.querySelector("span");
    const valueNode = item.querySelector("strong");
    setRenderedText(labelNode, label);
    setRenderedText(valueNode, value);
    markBackendRendered(item);
  });

  setRenderedText(doc.getElementById("draftState"), world ? "草案已生成" : "前提已载入");
  setControlValue(doc, ["#storyIdea"], data.generateInput);
  setRenderedText(doc.getElementById("generateBadge"), data.hasSource ? "可生成" : "等待交接");
  const generateButton = doc.getElementById("generateButton");
  if (generateButton) {
    generateButton.disabled = !data.hasSource;
    generateButton.textContent = data.hasSource ? "生成世界画布草案" : "等待故事设定交接";
    markBackendRendered(generateButton);
  }
  const qualityItems = Array.from(doc.querySelectorAll(".quality-row .quality-item"));
  [
    ["来源前提", data.hasSource ? "已受控" : "待交接"],
    ["一致性", data.hasSource ? "可用于生成" : "等待交接"],
    ["生成动作", data.hasSource ? "可开始" : "暂不可开始"],
  ].forEach(([label, value], index) => {
    const item = qualityItems[index];
    if (!item) {
      return;
    }
    item.innerHTML = `<span>${escapeHtml(label)}</span><strong><span class="dot"></span>${escapeHtml(value)}</strong>`;
    markBackendRendered(item);
  });
  doc.querySelectorAll(".source-card .badge").forEach((badge) => {
    badge.textContent = data.hasSource ? "已载入" : "待交接";
    markBackendRendered(badge);
  });
  if (data.unknownGaps.length) {
    const footnote = doc.getElementById("entryNote");
    if (footnote) {
      footnote.textContent = `生成前需保留 ${data.unknownGaps.length} 个待确认边界：${data.unknownGaps.slice(0, 3).join("；")}`;
      markBackendRendered(footnote);
    }
  }
  return true;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function worldCanvasListItems(items, limit = 4) {
  if (!Array.isArray(items)) {
    return [];
  }
  return items.map((item) => compactWorldCanvasDisplayText(item, "", 140)).filter(Boolean).slice(0, limit);
}

function suppressWorldCanvasStaticText(doc, world) {
  if (!doc?.body || !world) {
    return;
  }
  const replacement = compactWorldCanvasDisplayText(
    worldCanvasPromptInputText(
      firstNonEmpty(
        world.story_direction,
        world.storyDirection,
        world.source_story_idea,
        world.sourceStoryIdea,
        world.history_summary,
        world.historySummary,
      ),
      "",
    ),
    "世界画布草案已同步。",
    120,
  );
  const rawReplacement = compactWorldCanvasDisplayText(
    firstNonEmpty(
      world.story_direction,
      world.storyDirection,
      world.source_story_idea,
      world.sourceStoryIdea,
      world.history_summary,
      world.historySummary,
    ),
    "世界画布草案已同步。",
    120,
  );
  const rawPromptPattern = INTERNAL_WORLD_CANVAS_PROMPT_PATTERN;
  const stalePattern = /(暂无此项数据|港口城|钟楼|潮汐禁区|龙影传说|旧钟|低魔悬疑|核心调查区|ProjectStoryPremise is authoritative|Prompt-first project|User story premise:|ProjectStoryPremise:|项目前提锚点[:：])/i;
  const nodeFilter = doc.defaultView?.NodeFilter || window.NodeFilter;
  const walker = doc.createTreeWalker(doc.body, nodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const text = String(node.nodeValue || "").trim();
      if (!stalePattern.test(text)) {
        return nodeFilter.FILTER_REJECT;
      }
      const parent = node.parentElement;
      if (
        !parent ||
        parent.closest(
          "script, style, title, svg defs, button, a, input, select, textarea, option, [role='button'], [role='tab'], [data-mafs-live-status='true'], #mafs-world-canvas-panel, #issueList, #issueDetail",
        )
      ) {
        return nodeFilter.FILTER_REJECT;
      }
      return nodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) {
    nodes.push(walker.currentNode);
  }
  nodes.forEach((node, index) => {
    const parent = node.parentElement;
    const isRawPrompt = rawPromptPattern.test(String(node.nodeValue || ""));
    node.nodeValue = isRawPrompt ? "" : index < 6 ? firstNonEmpty(replacement, rawReplacement) : "";
    if (parent) {
      markBackendRendered(parent);
      parent.classList.toggle("mafs-empty-suppressed", index >= 6);
      if (isRawPrompt && parent !== doc.body && !parent.children.length) {
        parent.classList.add("mafs-empty-suppressed");
        parent.style.display = "none";
      }
    }
  });
  const placeholderPattern = /(暂无此项数据|正在读取项目数据|待后端接入|æš‚æ— æ­¤é¡¹æ•°æ®|æ­£åœ¨è¯»å–é¡¹ç›®æ•°æ®|å¾…åŽç«¯æŽ¥å…¥)/;
  doc.querySelectorAll("body *").forEach((element) => {
    if (
      element.closest(
        "script, style, title, svg defs, [data-mafs-live-status='true'], #mafs-world-canvas-panel, #issueList, #issueDetail",
      )
    ) {
      return;
    }
    if ("value" in element && typeof element.value === "string" && placeholderPattern.test(element.value)) {
      element.value = "";
    }
    if ("placeholder" in element && typeof element.placeholder === "string" && placeholderPattern.test(element.placeholder)) {
      element.placeholder = "";
    }
    const text = String(element.textContent || "").trim();
    if (!element.children.length && rawPromptPattern.test(text)) {
      element.textContent = "";
      element.style.display = "none";
      markBackendRendered(element);
      element.classList.add("mafs-empty-suppressed");
      return;
    }
    if (!element.children.length && placeholderPattern.test(text)) {
      element.textContent = "";
      markBackendRendered(element);
      element.classList.add("mafs-empty-suppressed");
    }
  });
}

function renderWorldCanvasFactList(doc, selector, entries) {
  const target = doc.querySelector(selector);
  if (!target || !entries.length) {
    return;
  }
  target.innerHTML = "";
  entries.slice(0, 6).forEach(([label, value]) => {
    const item = doc.createElement("article");
    item.className = "fact-row";
    const dot = doc.createElement("span");
    dot.className = "dot";
    const strong = doc.createElement("strong");
    strong.textContent = label;
    const span = doc.createElement("span");
    span.textContent = value;
    item.append(dot, strong, span);
    target.appendChild(item);
  });
  markBackendRendered(target);
}

function worldCanvasSectionData(world) {
  const structure = world.world_structure || world.worldStructure || {};
  const location = Array.isArray(world.locations) && world.locations.length ? world.locations[0] : {};
  const rawDirection = firstNonEmpty(world.story_direction, world.storyDirection, world.source_story_idea, world.sourceStoryIdea);
  const promptSections = buildWorldCanvasPromptDerivedSections(world, rawDirection);
  const direction = worldCanvasDisplayText(
    rawDirection,
    "世界画布草案已生成，请审阅世界范围、规则边界与待确认项。",
    180,
  );
  const scope = worldCanvasSpecificText(
    firstNonEmpty(world.scope, structure.name, location.name),
    promptSections.scope,
    "核心舞台待确认",
    140,
  );
  const tone = worldCanvasSpecificText(firstNonEmpty(world.tone), promptSections.tone, "基调待确认", 140);
  const history = worldCanvasSpecificText(
    firstNonEmpty(world.history_summary, world.historySummary),
    promptSections.history,
    "关键历史事实需要从项目前提和后续用户确认中展开。",
    220,
  );
  const geography = worldCanvasSpecificText(
    firstNonEmpty(world.geography_summary, world.geographySummary),
    promptSections.geography,
    "主要地点以项目前提中的地点和后续确认信息为准。",
    220,
  );
  const culture = worldCanvasSpecificText(
    firstNonEmpty(world.culture_summary, world.cultureSummary),
    promptSections.culture,
    "社会关系、组织压力和日常秩序需要服务项目前提中的核心冲突。",
    220,
  );
  const rules = worldCanvasSpecificText(
    firstNonEmpty(world.special_rules_summary, world.specialRulesSummary),
    promptSections.specialRules,
    "所有特殊现象都必须有触发条件、边界和可追踪后果，并保留项目前提证据。",
    220,
  );
  const structureSummary = worldCanvasSpecificText(
    firstNonEmpty(structure.summary, location.summary),
    promptSections.structure,
    `${scope} 是当前世界画布的核心舞台，后续扩展必须服从已确认事实。`,
    220,
  );
  const hardRules = worldCanvasListItems(world.hard_rules || world.hardRules, 4);
  const unknownRules = worldCanvasListItems(world.unknown_rules || world.unknownRules, 4);
  const confirmations = worldCanvasListItems(world.user_confirmation_needed || world.userConfirmationNeeded, 4);
  const ruleFacts = [
    ...hardRules.map((item) => ["硬规则", item]),
    ...unknownRules.map((item) => ["未知项", item]),
    ...confirmations.map((item) => ["待确认", item]),
  ].slice(0, 6);
  return {
    overview: {
      title: scope,
      intro: direction,
      body: firstNonEmpty(structureSummary, history, geography, culture, rules),
      facts: [
        ["基调", tone],
        ["范围", scope],
        ["历史脉络", history],
        ["特殊规则", rules],
      ],
    },
    structure: {
      title: "世界结构",
      intro: structureSummary,
      body: firstNonEmpty(
        promptSections.structure,
        `${scope} 是当前故事的事实中心。世界结构应优先确认核心舞台、可扩展区域、未知边界和下游读取方式。`,
      ),
      facts: [
        ["核心舞台", scope],
        ["故事标记词", promptSections.markers],
        ["结构名称", worldCanvasSpecificText(structure.name, promptSections.markers, scope, 100)],
        ["结构类型", worldCanvasSpecificText(structure.structure_type || structure.structureType, promptSections.genre, "待确认", 100)],
        ["边界", "未确认区域不得提前写成最终事实。"],
      ],
    },
    history: {
      title: "历史脉络",
      intro: history,
      body: firstNonEmpty(
        promptSections.history,
        "历史脉络只记录当前项目已能支持的关键事实、传闻和待确认缺口；不能用模板故事替代用户项目前提。",
      ),
      facts: [
        ["关键历史", history],
        ["章节牵引", promptSections.chapters],
        ["证据边界", "需要由后续角色行动、证据、见证或用户确认继续展开。"],
        ["不可越界", "不得提前确认项目前提尚未支持的最终真相。"],
      ],
    },
    geography: {
      title: "地理轮廓",
      intro: geography,
      body: firstNonEmpty(
        promptSections.geography,
        "地理轮廓用于约束角色行动范围、信息来源和后续章节扩展入口；当前只展示已能从项目前提支持的地点关系。",
      ),
      facts: [
        ["主要地点", geography],
        ["核心范围", scope],
        ["扩展边界", "外部区域和未知地点需要在后续章节或用户确认后再固化。"],
      ],
    },
    culture: {
      title: "文化秩序",
      intro: culture,
      body: firstNonEmpty(
        promptSections.culture,
        "文化秩序负责解释角色为什么会按当前世界规则行动，包括组织压力、社会关系、禁忌、传闻和日常秩序。",
      ),
      facts: [
        ["社会秩序", culture],
        ["题材气质", promptSections.genre],
        ["主题压力", promptSections.theme],
        ["叙事作用", "为角色关系、冲突升级和信息遮蔽提供合理性。"],
        ["边界", "不得把文化说明写成与项目前提冲突的固定模板。"],
      ],
    },
    rules: {
      title: "特殊规则",
      intro: rules,
      body: firstNonEmpty(
        promptSections.specialRules,
        "特殊规则必须保持可追踪：触发条件、适用范围、代价、例外和读者可见证据都需要在后续生成中被维护。",
      ),
      facts: ruleFacts.length
        ? [["规则原文", promptSections.specialRules], ...ruleFacts].filter(([, value]) => Boolean(value)).slice(0, 6)
        : [
            ["规则边界", rules],
            ["待确认", "核心异常或特殊规则的最终来源仍需在后续设定中确认。"],
            ["下游影响", "角色、章节和场景写作必须遵守已确认规则。"],
          ],
    },
  };
}

function renderWorldCanvasSection(doc, sections, key = "overview") {
  const safeKey = sections[key] ? key : "overview";
  const section = sections[safeKey];
  setRenderedText(doc.getElementById("sectionTitle"), section.title);
  setRenderedText(doc.getElementById("sectionIntro"), section.intro);
  setRenderedText(doc.getElementById("sectionBody"), section.body);
  renderWorldCanvasFactList(doc, "#factList", section.facts.filter(([, value]) => Boolean(value)));
  doc.querySelectorAll(".section-tab").forEach((tab) => {
    const active = tab.dataset.section === safeKey;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  doc.body.dataset.mafsWorldCanvasActiveSection = safeKey;
}

function installWorldCanvasSectionTabs(doc, sections) {
  const tabs = Array.from(doc.querySelectorAll(".section-tab[data-section]"));
  if (!tabs.length) {
    return;
  }
  if (doc.defaultView) {
    doc.defaultView.__mafsWorldCanvasSections = sections;
  }
  tabs.forEach((tab) => {
    if (tab.dataset.mafsWorldCanvasTabBound === "true") {
      return;
    }
    tab.dataset.mafsWorldCanvasTabBound = "true";
    tab.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        renderWorldCanvasSection(doc, doc.defaultView?.__mafsWorldCanvasSections || sections, tab.dataset.section || "overview");
      },
      true,
    );
  });
}

function worldCanvasRowsFromItems(items, label, emptyLabel, emptyValue, limit = 5) {
  const rows = worldCanvasListItems(items, limit).map((item) => [label, item]);
  return rows.length ? rows : [[emptyLabel, emptyValue]];
}

function buildWorldCanvasRevisionContexts(world) {
  const structure = world.world_structure || world.worldStructure || {};
  const location = Array.isArray(world.locations) && world.locations.length ? world.locations[0] : {};
  const rawDirection = firstNonEmpty(world.story_direction, world.storyDirection, world.source_story_idea, world.sourceStoryIdea);
  const promptSections = buildWorldCanvasPromptDerivedSections(world, rawDirection);
  const sourcePremise = worldCanvasDisplayText(
    firstNonEmpty(world.source_story_idea, world.sourceStoryIdea, rawDirection),
    "当前故事设定前提已作为世界画布来源。",
    180,
  );
  const direction = worldCanvasDisplayText(rawDirection, "世界画布草案已同步，可进行受控修订。", 180);
  const scope = worldCanvasSpecificText(firstNonEmpty(world.scope, structure.name, location.name), promptSections.scope, "核心舞台待确认", 160);
  const tone = worldCanvasSpecificText(firstNonEmpty(world.tone), promptSections.tone, "基调待确认", 160);
  const history = worldCanvasSpecificText(firstNonEmpty(world.history_summary, world.historySummary), promptSections.history, "历史脉络待确认", 180);
  const geography = worldCanvasSpecificText(firstNonEmpty(world.geography_summary, world.geographySummary), promptSections.geography, "地理轮廓待确认", 180);
  const culture = worldCanvasSpecificText(firstNonEmpty(world.culture_summary, world.cultureSummary), promptSections.culture, "文化秩序待确认", 180);
  const rules = worldCanvasSpecificText(firstNonEmpty(world.special_rules_summary, world.specialRulesSummary), promptSections.specialRules, "特殊规则边界待确认", 220);
  const hardRules = world.hard_rules || world.hardRules || [];
  const softRules = world.soft_rules || world.softRules || [];
  const unknownRules = world.unknown_rules || world.unknownRules || [];
  const conflicts = world.logic_conflicts || world.logicConflicts || world.conflicts || [];
  const confirmations = world.user_confirmation_needed || world.userConfirmationNeeded || [];
  const editableRows = [
    ...worldCanvasRowsFromItems(unknownRules, "未知规则", "未知规则", "当前暂无未知规则，可重点校准表达。", 3),
    ...worldCanvasRowsFromItems(conflicts, "逻辑冲突", "逻辑冲突", "当前暂无逻辑冲突。", 2),
    ...worldCanvasRowsFromItems(confirmations, "待确认项", "待确认项", "当前暂无待确认项。", 3),
  ].slice(0, 6);
  return {
    protected: {
      title: "保护事实",
      intro: "以下内容来自后端世界画布草案或故事设定交接，修订时必须保持稳定。",
      rows: [
        ["来源前提", sourcePremise],
        ["当前范围", scope],
        ["当前基调", tone],
        ["故事标记词", promptSections.markers],
        ["故事方向", direction],
        ...worldCanvasRowsFromItems(hardRules, "硬规则", "硬规则", rules, 2),
      ].filter(([, value]) => Boolean(value)).slice(0, 6),
    },
    editable: {
      title: "可修订内容",
      intro: "这些内容可以被修订，但不能越过来源前提、硬规则和已确认边界。",
      rows: editableRows,
    },
    resolved: {
      title: "已处理问题",
      intro: "这些条目反映当前草案已经归档到对应模块中的事实与边界。",
      rows: [
        ["世界结构", promptSections.structure],
        ["历史脉络", history],
        ["地理轮廓", geography],
        ["文化秩序", culture],
        ["特殊规则", rules],
        ...worldCanvasRowsFromItems(softRules, "软规则", "软规则", "当前暂无软规则。", 2),
      ].filter(([, value]) => Boolean(value)).slice(0, 6),
    },
    meta: {
      sourcePremise,
      direction,
      scope,
      tone,
      history,
      geography,
      culture,
      rules,
      hardRuleCount: Array.isArray(hardRules) ? hardRules.length : 0,
      softRuleCount: Array.isArray(softRules) ? softRules.length : 0,
      unknownRuleCount: Array.isArray(unknownRules) ? unknownRules.length : 0,
      confirmationCount: Array.isArray(confirmations) ? confirmations.length : 0,
      conflictCount: Array.isArray(conflicts) ? conflicts.length : 0,
    },
  };
}

function renderWorldCanvasRevisionContext(doc, contexts, key = "protected") {
  const safeKey = contexts[key] ? key : "protected";
  const context = contexts[safeKey];
  setRenderedText(doc.getElementById("contextTitle"), context.title);
  setRenderedText(doc.getElementById("contextIntro"), context.intro);
  const list = doc.getElementById("contextList");
  if (list) {
    list.innerHTML = "";
    context.rows.forEach(([name, state], index) => {
      const item = doc.createElement("article");
      item.className = "fact-row";
      const dot = doc.createElement("span");
      dot.className = index > 2 && safeKey !== "protected" ? "dot warn" : "dot";
      const strong = doc.createElement("strong");
      strong.textContent = name;
      const span = doc.createElement("span");
      span.textContent = state;
      item.append(dot, strong, span);
      list.appendChild(item);
    });
    markBackendRendered(list);
  }
  doc.querySelectorAll(".context-tab[data-context]").forEach((tab) => {
    const active = tab.dataset.context === safeKey;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  doc.body.dataset.mafsWorldCanvasRevisionContext = safeKey;
}

function installWorldCanvasRevisionTabs(doc, contexts) {
  const tabs = Array.from(doc.querySelectorAll(".context-tab[data-context]"));
  if (!tabs.length) {
    return;
  }
  if (doc.defaultView) {
    doc.defaultView.__mafsWorldCanvasRevisionContexts = contexts;
  }
  tabs.forEach((tab) => {
    if (tab.dataset.mafsWorldCanvasRevisionBound === "true") {
      return;
    }
    tab.dataset.mafsWorldCanvasRevisionBound = "true";
    tab.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        renderWorldCanvasRevisionContext(
          doc,
          doc.defaultView?.__mafsWorldCanvasRevisionContexts || contexts,
          tab.dataset.context || "protected",
        );
      },
      true,
    );
  });
}

function renderWorldCanvasRevisionSurface(doc, world) {
  if (!isFramePage(doc, new Set(["world-revision"]))) {
    return false;
  }
  const contexts = buildWorldCanvasRevisionContexts(world);
  const { meta } = contexts;
  const direction = meta.direction;
  const revisionPrompt = [
    `请围绕「${meta.scope}」做局部修订。`,
    `必须保留：${meta.sourcePremise}`,
    `当前基调：${meta.tone}`,
    `重点校准：${meta.unknownRuleCount || meta.conflictCount || meta.confirmationCount ? "未知规则、逻辑冲突与待确认边界" : "表达密度、模块归属与下游读取边界"}。`,
  ].join("\n");

  setRenderedText(doc.querySelector(".hero .lead"), direction);
  setRenderedText(doc.querySelector(".panel-head h2"), `修订「${meta.scope}」世界草案`);
  setRenderedText(doc.querySelector(".panel-copy"), "当前页面展示后端世界画布草案的受控修订上下文。修订只更新草案，不直接写入最终事实底座。");
  setRenderedText(doc.getElementById("draftState"), world.status === "confirmed" ? "确认版" : "草案版");
  setRenderedText(doc.getElementById("pageState"), "待修订");
  setRenderedText(doc.getElementById("targetSummary"), "局部修订");
  setRenderedText(doc.getElementById("focusSummary"), `重点：${meta.unknownRuleCount ? "未知规则、" : ""}${meta.conflictCount ? "逻辑冲突、" : ""}特殊规则`);
  setRenderedText(doc.getElementById("keepTitle"), "来源前提不变");
  setRenderedText(doc.getElementById("keepCopy"), meta.sourcePremise);
  setRenderedText(doc.getElementById("changeTitle"), "校准草案边界");
  setRenderedText(doc.getElementById("changeCopy"), firstNonEmpty(meta.rules, meta.history, meta.geography));
  const thirdPreview = doc.querySelector(".preview-grid .preview-card:nth-child(3)");
  if (thirdPreview) {
    setRenderedText(thirdPreview.querySelector("strong"), "正式事实底座");
    setRenderedText(thirdPreview.querySelector("p"), "提交修订后仍是草案版本，必须重新审阅确认后才会写入事实底座。");
    markBackendRendered(thirdPreview);
  }

  const revisionText = doc.getElementById("revisionText");
  if (revisionText) {
    if (revisionText.dataset.mafsUserEdited !== "true") {
      revisionText.value = revisionPrompt;
      revisionText.dataset.mafsBackendRendered = "true";
    }
    if (revisionText.dataset.mafsRevisionInputBound !== "true") {
      revisionText.dataset.mafsRevisionInputBound = "true";
      revisionText.addEventListener("input", () => {
        revisionText.dataset.mafsUserEdited = "true";
        setRenderedText(doc.getElementById("charCount"), `${revisionText.value.trim().length} 字`);
      });
    }
    setRenderedText(doc.getElementById("charCount"), `${revisionText.value.trim().length} 字`);
  }

  renderWorldCanvasRevisionContext(doc, contexts, doc.body.dataset.mafsWorldCanvasRevisionContext || "protected");
  installWorldCanvasRevisionTabs(doc, contexts);

  const guardList = doc.querySelector(".guard-list");
  if (guardList) {
    guardList.innerHTML = `
      <article class="guard-item"><span class="dot"></span><strong>来源前提已锁定</strong><span>保护</span></article>
      <article class="guard-item"><span class="dot"></span><strong>${escapeHtml(meta.hardRuleCount)} 条硬规则受保护</strong><span>草案</span></article>
      <article class="guard-item"><span class="dot warn"></span><strong>确认流程未触发</strong><span>未写入</span></article>
    `;
    markBackendRendered(guardList);
  }
  setRenderedText(doc.getElementById("requestCopy"), "修订请求尚未提交。当前可根据后端草案内容修改说明后提交。");
  setRenderedText(doc.getElementById("readyState"), revisionText?.value?.trim() ? "可提交" : "待输入");
  setRenderedText(doc.getElementById("requestState"), "未提交");
  setRenderedText(doc.getElementById("reviewState"), "等待");
  setRenderedText(doc.getElementById("nextStepNote"), "提交后生成新的世界画布草案版本，再返回草案审阅页确认。");
  doc.querySelectorAll(".version-grid .guard-card").forEach((card) => markBackendRendered(card));
  markBackendRendered(doc.querySelector(".context-card"));
  markBackendRendered(doc.querySelector(".editor-card"));
  return true;
}

function worldCanvasIssueSummary(value, fallback = "") {
  return compactWorldCanvasDisplayText(value, fallback, 120);
}

function buildWorldCanvasIssueList(world) {
  const unknownRules = Array.isArray(world.unknown_rules || world.unknownRules) ? world.unknown_rules || world.unknownRules : [];
  const confirmations = Array.isArray(world.user_confirmation_needed || world.userConfirmationNeeded)
    ? world.user_confirmation_needed || world.userConfirmationNeeded
    : [];
  const conflicts = Array.isArray(world.logic_conflicts || world.logicConflicts || world.conflicts)
    ? world.logic_conflicts || world.logicConflicts || world.conflicts
    : [];

  const issues = [];

  unknownRules.forEach((item, index) => {
    const title = worldCanvasIssueSummary(
      firstNonEmpty(item?.title, item?.summary, item?.statement),
      `未知规则 ${index + 1}`,
    );
    const summary = worldCanvasIssueSummary(
      firstNonEmpty(item?.why_it_matters, item?.whyItMatters, Array.isArray(item?.suggested_questions) ? item.suggested_questions[0] : ""),
      "该规则仍需用户确认边界、来源或触发条件。",
    );
    issues.push({
      type: "unknown",
      label: "未知规则",
      title,
      summary,
      detail: worldCanvasIssueSummary(
        firstNonEmpty(item?.suggested_fix, item?.suggestedFix, item?.why_it_matters, item?.whyItMatters, item?.summary),
        "请确认该未知规则是否保留、延后揭示，或改写为明确世界事实。",
        180,
      ),
    });
  });

  conflicts.forEach((item, index) => {
    const title = worldCanvasIssueSummary(
      firstNonEmpty(item?.title, item?.summary, item?.statement, item?.description),
      `逻辑冲突 ${index + 1}`,
    );
    const summary = worldCanvasIssueSummary(
      firstNonEmpty(item?.risk_if_changed, item?.riskIfChanged, item?.why_it_matters, item?.whyItMatters, item?.summary),
      "该冲突需要在确认世界事实前处理。",
    );
    issues.push({
      type: "conflict",
      label: "逻辑冲突",
      title,
      summary,
      detail: worldCanvasIssueSummary(
        firstNonEmpty(item?.suggested_fix, item?.suggestedFix, item?.resolution, item?.summary, item?.description),
        "请决定保留为剧情矛盾线索，还是修订为一致的世界事实。",
        180,
      ),
    });
  });

  confirmations.forEach((item, index) => {
    const text = worldCanvasIssueSummary(item, `待确认项 ${index + 1}`, 140);
    issues.push({
      type: "confirm",
      label: "待确认",
      title: text.length > 34 ? `${text.slice(0, 34).trim()}...` : text,
      summary: text,
      detail: "该项需要用户确认后，才能作为下游角色、Framework、章节和场景写作的事实依据。",
    });
  });

  if (!issues.length) {
    issues.push({
      type: "confirm",
      label: "待确认",
      title: "当前没有阻塞审查项",
      summary: "世界画布草案可继续进入确认流程。",
      detail: "如后续生成发现新缺口，系统会重新加入审查项。",
    });
  }

  return issues.filter((issue) => issue.title || issue.summary);
}

function issueDotClass(type) {
  if (type === "conflict") {
    return "dot danger";
  }
  if (type === "confirm") {
    return "dot warn";
  }
  return "dot";
}

function renderWorldCanvasIssueDetail(doc, issue) {
  const target = doc.getElementById("issueDetail");
  if (!target || !issue) {
    return;
  }
  target.innerHTML = `
    <span>${escapeHtml(issue.label)}</span>
    <strong>${escapeHtml(issue.title)}</strong>
    <p>${escapeHtml(issue.detail || issue.summary)}</p>
  `;
  markBackendRendered(target);
}

function renderWorldCanvasIssues(doc, world, filter = null) {
  const issueList = doc.getElementById("issueList");
  if (!issueList) {
    return;
  }
  const issues = buildWorldCanvasIssueList(world);
  const safeFilter = filter || doc.body.dataset.mafsWorldCanvasIssueFilter || "all";
  doc.body.dataset.mafsWorldCanvasIssueFilter = safeFilter;
  const visible = issues.filter((issue) => safeFilter === "all" || issue.type === safeFilter);
  issueList.innerHTML = "";

  if (!visible.length) {
    const empty = doc.createElement("article");
    empty.className = "issue-item mafs-backend-rendered";
    empty.innerHTML = `
      <span class="dot"></span>
      <span>
        <strong>当前分类没有审查项</strong>
        <small>可以切换其它分类，或继续审阅世界画布草案。</small>
      </span>
      <span class="issue-type">空</span>
    `;
    issueList.appendChild(empty);
    renderWorldCanvasIssueDetail(doc, {
      label: "当前分类",
      title: "没有审查项",
      detail: "该分类下暂时没有需要处理的内容。",
    });
  } else {
    visible.forEach((issue, index) => {
      const button = doc.createElement("button");
      button.type = "button";
      button.className = `issue-item${index === 0 ? " active" : ""}`;
      button.dataset.mafsIssueIndex = String(index);
      button.dataset.mafsIssueType = issue.type;
      button.innerHTML = `
        <span class="${issueDotClass(issue.type)}"></span>
        <span>
          <strong>${escapeHtml(issue.title)}</strong>
          <small>${escapeHtml(issue.summary)}</small>
        </span>
        <span class="issue-type">${escapeHtml(issue.label)}</span>
      `;
      button.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          issueList.querySelectorAll(".issue-item").forEach((item) => item.classList.remove("active"));
          button.classList.add("active");
          renderWorldCanvasIssueDetail(doc, issue);
        },
        true,
      );
      issueList.appendChild(button);
    });
    renderWorldCanvasIssueDetail(doc, visible[0]);
  }

  markBackendRendered(issueList);
  doc.querySelectorAll(".filter-button[data-filter]").forEach((button) => {
    const active = button.dataset.filter === safeFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    if (button.dataset.mafsWorldCanvasFilterBound === "true") {
      return;
    }
    button.dataset.mafsWorldCanvasFilterBound = "true";
    button.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        renderWorldCanvasIssues(doc, world, button.dataset.filter || "all");
      },
      true,
    );
  });
}

function worldCanvasRuleCounts(world) {
  const hardCount = Array.isArray(world.hard_rules || world.hardRules) ? (world.hard_rules || world.hardRules).length : 0;
  const softCount = Array.isArray(world.soft_rules || world.softRules) ? (world.soft_rules || world.softRules).length : 0;
  const unknownCount = Array.isArray(world.unknown_rules || world.unknownRules) ? (world.unknown_rules || world.unknownRules).length : 0;
  const confirmCount = Array.isArray(world.user_confirmation_needed || world.userConfirmationNeeded)
    ? (world.user_confirmation_needed || world.userConfirmationNeeded).length
    : 0;
  return { hardCount, softCount, unknownCount, confirmCount };
}

function renderWorldCanvasAuxiliaryPanels(doc, world) {
  if (!doc?.body || !world) {
    return;
  }
  const structure = world.world_structure || world.worldStructure || {};
  const location = Array.isArray(world.locations) && world.locations.length ? world.locations[0] : {};
  const rawDirection = firstNonEmpty(world.story_direction, world.storyDirection, world.source_story_idea, world.sourceStoryIdea);
  const sourcePremise = compactWorldCanvasDisplayText(
    worldCanvasPromptInputText(firstNonEmpty(world.source_story_idea, world.sourceStoryIdea, rawDirection), ""),
    "当前用户故事前提已作为世界画布来源。",
    150,
  );
  const direction = worldCanvasDisplayText(rawDirection, sourcePremise, 150);
  const scope = compactWorldCanvasDisplayText(firstNonEmpty(world.scope, structure.name, location.name), "核心舞台待确认", 90);
  const tone = compactWorldCanvasDisplayText(firstNonEmpty(world.tone), "基调待确认", 90);
  const geography = compactWorldCanvasDisplayText(
    firstNonEmpty(world.geography_summary, world.geographySummary),
    "主要地点以项目前提中的地点和后续确认信息为准。",
    120,
  );
  const rules = compactWorldCanvasDisplayText(
    firstNonEmpty(world.special_rules_summary, world.specialRulesSummary),
    "特殊规则需要在后续生成中持续维护。",
    140,
  );
  const { hardCount, softCount, unknownCount, confirmCount } = worldCanvasRuleCounts(world);
  const statusLabel = world.status === "confirmed" ? "已确认" : "待用户确认";

  const stateCard = doc.querySelector(".panel-head .state-card");
  if (stateCard) {
    stateCard.innerHTML = `<strong>${escapeHtml(world.status === "confirmed" ? "已确认" : "草案已生成")}</strong><span>${escapeHtml(statusLabel)}</span>`;
    markBackendRendered(stateCard);
  }

  const snapshotStack = doc.querySelector(".snapshot-stack");
  if (snapshotStack) {
    snapshotStack.innerHTML = `
      <article class="summary-card"><span>版本</span><strong>${escapeHtml(world.status === "confirmed" ? "确认版" : "草案版")}</strong></article>
      <article class="fact-card"><span>故事方向</span><strong>${escapeHtml(tone)}</strong><p>${escapeHtml(direction)}</p></article>
      <article class="fact-card"><span>确认范围</span><strong>${escapeHtml(scope)}</strong><p>${escapeHtml(geography)}</p></article>
      <article class="fact-card"><span>规则分层</span><strong>${hardCount} 硬 / ${softCount} 软 / ${unknownCount} 未知</strong><p>${escapeHtml(rules)}</p></article>
    `;
    markBackendRendered(snapshotStack);
  }

  const sideCards = Array.from(doc.querySelectorAll(".side-card"));
  const reviewCard = sideCards.find((card) => /审阅状态/.test(card.textContent || ""));
  const sourceCard = sideCards.find((card) => /来源前提/.test(card.textContent || ""));
  const downstreamCard = sideCards.find((card) => /下游影响/.test(card.textContent || ""));

  if (reviewCard) {
    const paragraph = reviewCard.querySelector("p");
    if (paragraph) {
      paragraph.textContent = world.status === "confirmed" ? "世界画布已确认，可作为后续模块事实来源。" : "世界画布草案已生成，仍需用户完成确认。";
      markBackendRendered(paragraph);
    }
  }

  if (sourceCard) {
    const paragraph = sourceCard.querySelector("p");
    if (paragraph) {
      paragraph.textContent = sourcePremise;
      markBackendRendered(paragraph);
    }
    const list = sourceCard.querySelector(".impact-list");
    if (list) {
      list.innerHTML = "";
      [
        ["用户前提", sourcePremise],
        ["当前范围", scope],
        ["当前基调", tone],
        ["规则数量", `${hardCount} 条硬规则，${softCount} 条软规则，${unknownCount} 条未知规则`],
      ].forEach(([label, value]) => {
        const item = doc.createElement("article");
        item.className = "status-item";
        item.innerHTML = `<span class="dot"></span><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span>`;
        list.appendChild(item);
      });
      markBackendRendered(list);
    }
  }

  if (downstreamCard) {
    const paragraph = downstreamCard.querySelector("p");
    if (paragraph) {
      paragraph.textContent = "确认后，角色主轴、章节计划和场景写作都会读取这些世界事实、规则和待确认边界。";
      markBackendRendered(paragraph);
    }
    const note = downstreamCard.querySelector(".mini-note");
    if (note) {
      note.textContent = `下游必须遵守：${rules} 待确认项 ${confirmCount} 个，确认前不得写入最终事实底座。`;
      markBackendRendered(note);
    }
  }
}

function renderWorldCanvasPanel(doc, world) {
  if (doc.querySelector(".section-tabs")) {
    doc.getElementById("mafs-world-canvas-panel")?.remove();
    return;
  }
  const target =
    doc.querySelector(".draft-card .draft-main") ||
    doc.querySelector(".source-card") ||
    doc.querySelector(".map-card .map-content") ||
    doc.querySelector(".work-panel") ||
    doc.body;
  if (!target) {
    return;
  }
  let panel = doc.getElementById("mafs-world-canvas-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-world-canvas-panel";
    panel.className = "mafs-world-canvas-panel mafs-backend-rendered";
    panel.setAttribute("aria-label", "后端世界画布内容");
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.9)";
    panel.style.color = "#2d2823";
    panel.style.boxShadow = "0 12px 36px rgba(67, 52, 40, 0.08)";
    target.prepend(panel);
  }
  const structure = world.world_structure || world.worldStructure || {};
  const location = Array.isArray(world.locations) && world.locations.length ? world.locations[0] : {};
  const direction = worldCanvasDisplayText(
    firstNonEmpty(world.story_direction, world.storyDirection, world.source_story_idea, world.sourceStoryIdea),
    "世界画布草案已生成，请审阅核心范围、规则边界和待确认问题。",
    160,
  );
  const promptSections = buildWorldCanvasPromptDerivedSections(world);
  const scope = worldCanvasSpecificText(firstNonEmpty(world.scope, structure.name, location.name), promptSections.scope, "核心舞台待确认", 120);
  const tone = worldCanvasSpecificText(firstNonEmpty(world.tone), promptSections.tone, "基调待确认", 120);
  const history = worldCanvasSpecificText(firstNonEmpty(world.history_summary, world.historySummary), promptSections.history, "", 180);
  const geography = worldCanvasSpecificText(firstNonEmpty(world.geography_summary, world.geographySummary), promptSections.geography, "", 180);
  const culture = worldCanvasSpecificText(firstNonEmpty(world.culture_summary, world.cultureSummary), promptSections.culture, "", 180);
  const rules = worldCanvasSpecificText(firstNonEmpty(world.special_rules_summary, world.specialRulesSummary), promptSections.specialRules, "", 180);
  const hardRules = worldCanvasListItems(world.hard_rules || world.hardRules, 3);
  const unknownRules = worldCanvasListItems(world.unknown_rules || world.unknownRules, 3);
  const confirmations = worldCanvasListItems(world.user_confirmation_needed || world.userConfirmationNeeded, 3);
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端世界画布草案</p>
    <h3 style="margin:0 0 8px;font-size:20px;line-height:1.3;">${escapeHtml(scope || "世界画布")}</h3>
    <p style="margin:0 0 12px;line-height:1.7;">${escapeHtml(direction || "世界画布已由后端生成。")}</p>
    <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:0 0 12px;">
      <article style="padding:10px;border:1px solid rgba(121,89,74,.14);border-radius:8px;background:rgba(255,255,255,.45);"><strong>基调</strong><p style="margin:5px 0 0;">${escapeHtml(tone)}</p></article>
      <article style="padding:10px;border:1px solid rgba(121,89,74,.14);border-radius:8px;background:rgba(255,255,255,.45);"><strong>范围</strong><p style="margin:5px 0 0;">${escapeHtml(scope)}</p></article>
      <article style="padding:10px;border:1px solid rgba(121,89,74,.14);border-radius:8px;background:rgba(255,255,255,.45);"><strong>地理</strong><p style="margin:5px 0 0;">${escapeHtml(geography)}</p></article>
      <article style="padding:10px;border:1px solid rgba(121,89,74,.14);border-radius:8px;background:rgba(255,255,255,.45);"><strong>文化</strong><p style="margin:5px 0 0;">${escapeHtml(culture)}</p></article>
    </div>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>历史脉络：</strong>${escapeHtml(history)}</p>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>特殊规则：</strong>${escapeHtml(rules)}</p>
    <ul style="margin:0;padding-left:18px;line-height:1.7;">
      ${[...hardRules, ...unknownRules, ...confirmations].slice(0, 8).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
  markBackendRendered(panel);
}

function renderWorldCanvasSurface(doc, result) {
  const world = findWorldCanvasPayload(result);
  if (!doc?.body) {
    return false;
  }
  if (!isFramePage(doc, WORLD_CANVAS_PAGE_IDS)) {
    return false;
  }
  const isWorldCanvasPage =
    doc.querySelector(
      "#storyIdea, #sectionTitle, #factList, #currentSummary, #confirmButton, #revisionText, #contextTitle, #contextList, #requestCopy",
    ) &&
    /世界画布/.test(doc.body.textContent || "");
  if (!isWorldCanvasPage) {
    return false;
  }
  const premiseRendered = renderWorldCanvasPremiseSource(doc, result, world);
  if (!world) {
    if (premiseRendered) {
      applyRealtimeProgressElements(doc, { label: "故事设定交接已载入", percent: 100 });
      showRealtimeStatusPanel(doc, { label: "故事设定交接已载入", percent: 100 });
    }
    return premiseRendered;
  }
  const structure = world.world_structure || world.worldStructure || {};
  const location = Array.isArray(world.locations) && world.locations.length ? world.locations[0] : {};
  const rawDirection = firstNonEmpty(world.story_direction, world.storyDirection, world.source_story_idea, world.sourceStoryIdea);
  const promptSections = buildWorldCanvasPromptDerivedSections(world, rawDirection);
  const direction = worldCanvasDisplayText(
    rawDirection,
    "世界画布草案已生成，请审阅世界范围、规则边界与待确认项。",
    160,
  );
  const scope = worldCanvasSpecificText(firstNonEmpty(world.scope, structure.name, location.name), promptSections.scope, "核心舞台待确认", 120);
  const tone = worldCanvasSpecificText(firstNonEmpty(world.tone), promptSections.tone, "基调待确认", 120);
  const history = worldCanvasSpecificText(firstNonEmpty(world.history_summary, world.historySummary), promptSections.history, "", 180);
  const geography = worldCanvasSpecificText(firstNonEmpty(world.geography_summary, world.geographySummary), promptSections.geography, "", 180);
  const culture = worldCanvasSpecificText(firstNonEmpty(world.culture_summary, world.cultureSummary), promptSections.culture, "", 180);
  const rules = worldCanvasSpecificText(firstNonEmpty(world.special_rules_summary, world.specialRulesSummary), promptSections.specialRules, "", 180);
  const sections = worldCanvasSectionData(world);
  const activeSection = sections[doc.body.dataset.mafsWorldCanvasActiveSection]
    ? doc.body.dataset.mafsWorldCanvasActiveSection
    : "overview";
  const currentWorldPageId = framePageId(doc);
  const isWorldConfirmed = world.status === "confirmed" || currentWorldPageId === "world-confirm";

  setRenderedText(doc.querySelector(".hero .lead"), direction);
  setRenderedText(doc.querySelector(".panel-copy"), direction);
  setRenderedText(doc.getElementById("draftState"), world.status === "confirmed" ? "已确认" : "草案已生成");
  setRenderedText(doc.getElementById("pageState"), world.status === "confirmed" ? "已确认" : "待审阅");
  setRenderedText(doc.getElementById("currentSummary"), direction);
  setRenderedText(doc.getElementById("currentModule"), scope || "世界画布");
  setRenderedText(doc.getElementById("currentDetail"), geography || direction);
  setRenderedText(doc.getElementById("liveState"), "后端已返回草案");
  setRenderedText(doc.getElementById("modelState"), "完成");
  setRenderedText(doc.getElementById("reviewState"), "可审阅");
  setRenderedText(doc.getElementById("statusCopy"), "后端世界画布草案已同步到页面。");
  setRenderedText(doc.getElementById("boundaryNote"), "当前页面展示的是草案数据，确认前不会写入最终事实底座。");
  renderWorldCanvasSection(doc, sections, activeSection);
  installWorldCanvasSectionTabs(doc, sections);
  setRenderedText(doc.getElementById("factTitle"), scope || "世界画布草案");
  setRenderedText(doc.getElementById("factIntro"), direction);
  setRenderedText(doc.getElementById("factBody"), firstNonEmpty(history, geography, culture, rules));
  setControlValue(doc, ["#storyIdea"], worldCanvasPromptInputText(firstNonEmpty(world.source_story_idea, world.sourceStoryIdea, rawDirection), ""));
  const confirmButton = doc.getElementById("confirmButton");
  doc.getElementById("mafsWorldToCharacterButton")?.remove();
  if (confirmButton) {
    confirmButton.disabled = false;
    if (isWorldConfirmed) {
      confirmButton.textContent = "进入角色主轴";
      confirmButton.dataset.mafsActionId = "navigation.characters";
      confirmButton.dataset.mafsTarget = "character-entry";
    } else {
      confirmButton.textContent = "确认草案";
      confirmButton.dataset.mafsActionId = "world.confirm";
      confirmButton.dataset.mafsTarget = "world-confirm";
    }
    confirmButton.dataset.mafsBackendBound = "true";
    markBackendRendered(confirmButton);
  }
  setRenderedText(doc.getElementById("nextStepNote"), isWorldConfirmed ? "世界事实已确认，下一步进入角色主轴。" : "确认草案后，系统才允许进入角色主轴。");
  setRenderedText(doc.getElementById("confirmState"), isWorldConfirmed ? "已确认" : "待确认");
  const confirmDot = doc.getElementById("confirmDot");
  if (confirmDot) {
    confirmDot.className = "dot";
  }

  const sideStatus = [
    ["世界画布草案", "已生成"],
    ["当前范围", scope || "已同步"],
    ["当前基调", tone || "已同步"],
    ["确认状态", world.status === "confirmed" ? "已确认" : "待用户确认"],
  ];
  const statusLists = doc.querySelectorAll(".status-list, .impact-list, .check-list, .risk-list");
  statusLists.forEach((list) => {
    if (!list.closest("[data-mafs-backend-rendered='true']")) {
      list.innerHTML = "";
      sideStatus.forEach(([label, value]) => {
        const item = doc.createElement("article");
        item.className = "status-item";
        const dot = doc.createElement("span");
        dot.className = "dot";
        const strong = doc.createElement("strong");
        strong.textContent = label;
        const span = doc.createElement("span");
        span.textContent = value;
        item.append(dot, strong, span);
        list.appendChild(item);
      });
      markBackendRendered(list);
    }
  });

  renderWorldCanvasPanel(doc, world);
  suppressWorldCanvasStaticText(doc, world);
  renderWorldCanvasIssues(doc, world);
  renderWorldCanvasAuxiliaryPanels(doc, world);
  renderWorldCanvasRevisionSurface(doc, world);
  applyRealtimeProgressElements(doc, { label: "世界画布草案已同步", percent: 100 });
  [120, 600, 1400].forEach((delayMs) => {
    window.setTimeout(() => {
      suppressWorldCanvasStaticText(doc, world);
      renderWorldCanvasIssues(doc, world);
      renderWorldCanvasAuxiliaryPanels(doc, world);
      renderWorldCanvasRevisionSurface(doc, world);
    }, delayMs);
  });
  return true;
}

function normalizeCharacterTier(value) {
  const tier = String(value || "").trim().toUpperCase();
  return ["A", "B", "C", "D"].includes(tier) ? tier : "";
}

function characterPayloadTier(character, draft) {
  return normalizeCharacterTier(
    character?.tier ||
      draft?.target_tier ||
      draft?.targetTier ||
      draft?.complexity_profile?.tier ||
      draft?.complexityProfile?.tier ||
      draft?.character?.tier ||
      draft?.role?.tier,
  );
}

function preferredCharacterTierFromResult(result) {
  return normalizeCharacterTier(
    result?.hydrated_refs?.roleTier ||
      result?.hydratedRefs?.roleTier ||
      result?.refs?.roleTier ||
      result?.roleTier ||
      result?.target_tier ||
      result?.targetTier ||
      result?.action_result?.hydrated_refs?.roleTier ||
      result?.action_result?.hydratedRefs?.roleTier ||
      result?.action_result?.roleTier ||
      result?.action_result?.target_tier ||
      result?.action_result?.targetTier,
  );
}

function makeCharacterDraftPayload(candidate) {
  const character = candidate?.character || candidate?.role || candidate;
  if (character && typeof character === "object" && (character.name || character.profile || character.current_state || character.currentState)) {
    return { character, draft: candidate };
  }
  return null;
}

function findCharacterDraftPayload(result) {
  const preferredTier = preferredCharacterTierFromResult(result);
  const candidates = [
    result?.character_draft?.draft,
    result?.characterDraft?.draft,
    result?.action_result?.action_result?.character_draft?.draft,
    result?.action_result?.action_result?.characterDraft?.draft,
    result?.generated_role_draft?.draft,
    result?.generatedRoleDraft?.draft,
    result?.draft,
    result?.action_result?.action_result?.generated_role_draft?.draft,
    result?.action_result?.action_result?.generatedRoleDraft?.draft,
    result?.action_result?.action_result?.draft,
    result?.action_result?.character_draft?.draft,
    result?.action_result?.generated_role_draft?.draft,
    result?.action_result?.draft,
  ].map(makeCharacterDraftPayload).filter(Boolean);
  const preferredPayload = preferredTier
    ? candidates.find((payload) => characterPayloadTier(payload.character, payload.draft) === preferredTier)
    : null;
  if (preferredPayload) {
    return preferredPayload;
  }
  if (candidates.length) {
    return candidates[0];
  }
  const found = findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.character &&
          typeof item.character === "object" &&
          (item.character.name || item.character.profile || item.character.current_state || item.character.currentState),
      ),
  );
  if (found) {
    const foundPayload = { character: found.character, draft: found };
    if (!preferredTier || characterPayloadTier(foundPayload.character, foundPayload.draft) === preferredTier) {
      return foundPayload;
    }
  }
  const roles = findNestedArray(result, ["roles", "characters", "items"]).filter((item) => item && typeof item === "object");
  if (roles.length) {
    const preferredRole = preferredTier
      ? roles.find((role) => characterPayloadTier(role, { character: role }) === preferredTier)
      : null;
    const role = preferredRole || roles[0];
    return { character: role, draft: { character: role } };
  }
  return null;
}

function characterProfileText(character, key) {
  const profile = character?.profile || {};
  const state = character?.current_state || character?.currentState || {};
  const arc = character?.arc_state || character?.arcState || {};
  return firstNonEmpty(
    profile[key],
    state[key],
    arc[key],
  );
}

function characterListText(value) {
  if (!value) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(worldCanvasText).filter(Boolean).join("；");
  }
  return worldCanvasText(value);
}

function characterFallbackText(value, fallback = "\u5f85\u7528\u6237\u786e\u8ba4", maxLength = 180) {
  let text = worldCanvasReadableText(worldCanvasText(value)).replace(/\s+/g, " ").trim();
  if (!text) {
    const fallbackCandidate = firstNonEmpty(value, fallback);
    text = worldCanvasReadableText(worldCanvasText(fallbackCandidate)).replace(/\s+/g, " ").trim();
    if (!text && typeof fallbackCandidate === "string") {
      text = fallbackCandidate.trim();
    }
  }
  text = String(text || "").trim();
  if (!text || text === "[object Object]") {
    text = fallback;
  }
  const internalIndex = text.search(INTERNAL_WORLD_CANVAS_PROMPT_PATTERN);
  if (internalIndex >= 0) {
    text = text.slice(0, internalIndex).replace(/[；;:：\s]+$/g, "").trim();
  }
  if (!text) {
    text = fallback;
  }
  if (maxLength > 0 && text.length > maxLength) {
    return `${text.slice(0, maxLength).trim()}...`;
  }
  return text;
}

function setLabeledCardText(card, label, value) {
  if (!card) {
    return;
  }
  const labelNode = card.querySelector("span, em, p");
  const valueNode = card.querySelector("strong, b");
  if (labelNode) {
    setRenderedText(labelNode, label);
  }
  if (valueNode) {
    setRenderedText(valueNode, characterFallbackText(value));
  } else {
    card.textContent = `${label}\n${characterFallbackText(value)}`;
    markBackendRendered(card);
  }
}

function setRelationCardText(card, label, detail, weight = "\u5f85\u786e\u8ba4") {
  if (!card) {
    return;
  }
  const strong = card.querySelector("strong");
  const spans = Array.from(card.querySelectorAll("span")).filter((span) => !span.classList.contains("badge"));
  const badge = card.querySelector(".badge");
  setRenderedText(strong, label);
  if (spans[0]) {
    setRenderedText(spans[0], characterFallbackText(detail));
  }
  if (badge) {
    setRenderedText(badge, weight);
  }
  card.dataset.detail = characterFallbackText(detail);
  markBackendRendered(card);
}

function renderCharacterReviewSections(doc, character, draft, data) {
  if (!doc?.body || !character) {
    return;
  }
  const profile = character.profile || {};
  const state = character.current_state || character.currentState || {};
  const arc = character.arc_state || character.arcState || {};
  const name = firstNonEmpty(character.name, "\u89d2\u8272\u8349\u6848");
  const displayTier = normalizeCharacterTier(data.displayTier || character.tier) || "A";
  const identity = characterFallbackText(data.identity || profile.identity, `${displayTier} \u7ea7\u89d2\u8272`);
  const background = characterFallbackText(data.background || data.description || draft?.latest_user_prompt || draft?.latestUserPrompt);
  const traits = characterListText(profile.traits);
  const goal = characterFallbackText(data.goal || characterListText(profile.goals) || state.active_goal || state.activeGoal);
  const secret = characterFallbackText(characterListText(profile.secrets), "\u6682\u65e0\u5df2\u516c\u5f00\u79d8\u5bc6");
  const storyFunction = characterFallbackText(profile.story_function || profile.storyFunction || data.identity);
  const currentState = characterFallbackText(data.emotional || state.emotional_state || state.emotionalState || state.active_goal || state.activeGoal);
  const bottomLine = characterFallbackText(data.bottomLine || profile.personality_baseline?.bottom_line || profile.personalityBaseline?.bottomLine);
  const knowledge = characterFallbackText(data.knowledge || characterListText(state.knowledge) || characterListText(profile.knowledge_scope || profile.knowledgeScope));
  const arcText = characterFallbackText(data.arcText || arc.current_arc || arc.currentArc || arc.inner_conflict || arc.innerConflict);

  setRenderedText(doc.querySelector(".portrait-copy"), background);
  const summaryCards = Array.from(doc.querySelectorAll(".summary-card"));
  [
    ["\u8eab\u4efd", identity],
    ["\u6c14\u8d28", traits || background],
    ["\u76ee\u6807", goal],
    ["\u79d8\u5bc6", secret],
  ].forEach(([label, value], index) => setLabeledCardText(summaryCards[index], label, value));

  const archiveCards = Array.from(doc.querySelectorAll("#panel-archive .content-card"));
  [
    ["\u6545\u4e8b\u4f5c\u7528", storyFunction],
    ["\u5f53\u524d\u72b6\u6001", currentState],
    ["\u6027\u683c\u5e95\u7ebf", bottomLine],
    ["\u8bb0\u5fc6\u6458\u8981", knowledge],
  ].forEach(([label, value], index) => setLabeledCardText(archiveCards[index], label, value));

  const relationCards = Array.from(doc.querySelectorAll("#panel-relations .relation-card"));
  setRelationCardText(relationCards[0], "\u4e0e\u4e3b\u7ebf", goal, "\u9ad8");
  setRelationCardText(relationCards[1], "\u4e0e\u4e16\u754c\u89c4\u5219", bottomLine || knowledge, "\u4e2d");
  setRelationCardText(relationCards[2], "\u4e0e\u4e3b\u89d2\u56e2", arcText, "\u5f85\u5b9a");
  setRenderedText(doc.getElementById("relationDetail"), relationCards[0]?.dataset.detail || goal);
  const mapNodes = Array.from(doc.querySelectorAll(".map-node"));
  [name, "\u4e3b\u7ebf", "\u89c4\u5219"].forEach((value, index) => setRenderedText(mapNodes[index], value));

  const checkItems = Array.from(doc.querySelectorAll("#panel-checks .check-item"));
  [
    ["\u7ed3\u6784\u53ef\u7528", `${identity}\u5df2\u4e0e\u5f53\u524d\u9879\u76ee\u524d\u63d0\u5bf9\u9f50\u3002`, "\u901a\u8fc7"],
    ["\u5173\u7cfb\u9700\u786e\u8ba4", "\u4e0e\u4e3b\u89d2\u56e2\u548c\u5176\u4ed6\u91cd\u8981\u89d2\u8272\u7684\u5177\u4f53\u5173\u7cfb\u4ecd\u9700\u5728\u540e\u7eed\u5de5\u4f5c\u53f0\u786e\u8ba4\u3002", "\u5f85\u786e\u8ba4"],
    ["\u7f3a\u53e3\u9700\u5904\u7406", "\u5982\u679c\u7528\u6237\u9700\u8981\u66f4\u5f3a\u7684\u5267\u60c5\u6743\u91cd\uff0c\u9700\u8865\u5145\u4e0e\u4e3b\u7ebf\u7684\u56e0\u679c\u8fde\u63a5\u3002", "\u5f85\u5b9a"],
    ["\u65e0\u963b\u585e\u95ee\u9898", "\u5f53\u524d\u8349\u6848\u53ef\u4fee\u8ba2\uff0c\u4e5f\u53ef\u5728\u7528\u6237\u786e\u8ba4\u540e\u5199\u5165\u89d2\u8272\u5e93\u3002", "\u53ef\u786e\u8ba4"],
  ].forEach(([label, value, status], index) => {
    const item = checkItems[index];
    if (!item) {
      return;
    }
    setRenderedText(item.querySelector("strong"), label);
    setRenderedText(item.querySelector("span:not(.dot)"), value);
    setRenderedText(item.querySelector("em"), status);
    markBackendRendered(item);
  });

  const revisionText = doc.getElementById("revisionText");
  if (revisionText) {
    revisionText.placeholder = `\u5199\u4e0b\u4f60\u5e0c\u671b\u8c03\u6574 ${name} \u7684\u5730\u65b9\uff0c\u4f8b\u5982\uff1a\u66f4\u6539\u76ee\u6807\u3001\u5173\u7cfb\u5f20\u529b\u6216\u6545\u4e8b\u4f5c\u7528\u3002`;
  }
  const confirmText = doc.getElementById("confirmText");
  if (confirmText) {
    confirmText.placeholder = `\u4f8b\u5982\uff1a\u786e\u8ba4 ${name} \u4f5c\u4e3a ${displayTier} \u7ea7\u89d2\u8272\uff0c\u540e\u7eed\u5728\u5173\u7cfb\u5de5\u4f5c\u53f0\u7ee7\u7eed\u8865\u5145\u3002`;
  }
}

function renderCharacterConfirmSections(doc, character, draft, data) {
  if (!doc?.body || framePageId(doc) !== "character-confirm" || !character) {
    return;
  }
  const profile = character.profile || {};
  const state = character.current_state || character.currentState || {};
  const arc = character.arc_state || character.arcState || {};
  const name = firstNonEmpty(character.name, "\u89d2\u8272\u8349\u6848");
  const displayTier = normalizeCharacterTier(data.displayTier || character.tier) || "A";
  const identity = characterFallbackText(data.identity || profile.identity, `${displayTier} \u7ea7\u89d2\u8272`);
  const background = characterFallbackText(data.background || data.description || draft?.latest_user_prompt || draft?.latestUserPrompt);
  const goal = characterFallbackText(data.goal || characterListText(profile.goals) || state.active_goal || state.activeGoal);
  const bottomLine = characterFallbackText(data.bottomLine || profile.personality_baseline?.bottom_line || profile.personalityBaseline?.bottomLine);
  const knowledge = characterFallbackText(data.knowledge || characterListText(state.knowledge) || characterListText(profile.knowledge_scope || profile.knowledgeScope));
  const arcText = characterFallbackText(data.arcText || arc.current_arc || arc.currentArc || arc.inner_conflict || arc.innerConflict);

  setRenderedText(doc.querySelector(".hero .lead"), `${name}\u5c06\u4f5c\u4e3a ${displayTier} \u7ea7\u89d2\u8272\u5199\u5165\u89d2\u8272\u5e93\u3002\u672c\u6b65\u53ea\u786e\u8ba4\u89d2\u8272\u4e8b\u5b9e\uff0c\u4e0d\u751f\u6210\u7ae0\u8282\u6216\u573a\u666f\u6b63\u6587\u3002`);
  setRenderedText(doc.getElementById("draftTitle"), `${name}\u662f\u5426\u5199\u5165\u89d2\u8272\u5e93\uff1f`);
  setRenderedText(doc.getElementById("topStatus"), "\u5f85\u786e\u8ba4\u5199\u5165");
  setRenderedText(doc.getElementById("phaseWord"), "\u5f85\u786e\u8ba4");
  setRenderedText(doc.getElementById("phaseHint"), "3 / 3 \u5df2\u6838\u9a8c");
  setRenderedText(doc.getElementById("writeState"), "\u7b49\u5f85\u7528\u6237\u786e\u8ba4\u5199\u5165\u3002");
  setRenderedText(doc.getElementById("nextState"), "\u5199\u5165\u540e\u8fdb\u5165\u89d2\u8272\u6863\u6848\u5e93\u68c0\u67e5\u3002");
  setRenderedText(doc.getElementById("actionHint"), "\u786e\u8ba4\u540e\uff0c\u5f53\u524d\u8349\u6848\u4f1a\u6210\u4e3a\u6b63\u5f0f\u89d2\u8272\u4e8b\u5b9e\u3002");

  const reviewStack = doc.getElementById("reviewStack");
  if (reviewStack) {
    reviewStack.innerHTML = "";
    [
      ["\u6863", `${name}\u7684\u89d2\u8272\u5e95\u5ea7`, `${identity}\u3002${background}`],
      ["\u76ee", "\u6545\u4e8b\u4f5c\u7528", goal],
      ["\u89c4", "\u8fb9\u754c\u4e0e\u5e95\u7ebf", bottomLine],
      ["\u8bb0", "\u8bb0\u5fc6\u4e0e\u77e5\u8bc6", knowledge],
    ].forEach(([mark, title, text]) => {
      const button = doc.createElement("button");
      button.type = "button";
      button.className = "review-card mafs-backend-rendered";
      button.innerHTML = `<span class="review-mark">${escapeHtml(mark)}</span><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(text)}</small><span class="review-meta"><span class="mini-chip">${escapeHtml(displayTier)} \u7ea7</span><span class="mini-chip">\u5df2\u6838\u9a8c</span></span></span>`;
      reviewStack.appendChild(button);
    });
    markBackendRendered(reviewStack);
  }

  setRenderedText(doc.getElementById("sectionType"), "\u89d2\u8272\u5199\u5165\u786e\u8ba4");
  setRenderedText(doc.getElementById("sectionTitle"), `${name}\u7684\u6b63\u5f0f\u89d2\u8272\u5e95\u5ea7`);
  setRenderedText(doc.getElementById("sectionSummary"), background);
  setRenderedText(doc.getElementById("sectionImpact"), "\u540e\u7eed\u7ae0\u8282\u3001\u573a\u666f\u548c\u8bb0\u5fc6\u8fde\u7eed\u6027\u53ef\u4ee5\u8c03\u7528\u8fd9\u4efd\u89d2\u8272\u4e8b\u5b9e\u3002");

  const factGrid = doc.getElementById("factGrid");
  if (factGrid) {
    factGrid.innerHTML = "";
    [
      ["\u8eab\u4efd", identity],
      ["\u76ee\u6807", goal],
      ["\u5e95\u7ebf", bottomLine],
    ].forEach(([title, text]) => {
      const card = doc.createElement("article");
      card.className = "fact-card mafs-backend-rendered";
      card.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(text)}</span>`;
      factGrid.appendChild(card);
    });
    markBackendRendered(factGrid);
  }

  const gateGrid = doc.getElementById("gateGrid");
  if (gateGrid) {
    gateGrid.innerHTML = "";
    [
      ["\u6863\u6848\u5df2\u6838\u9a8c", "\u89d2\u8272\u8eab\u4efd\u3001\u76ee\u6807\u548c\u884c\u52a8\u5e95\u7ebf\u53ef\u5199\u5165\u3002"],
      ["\u5173\u7cfb\u5f85\u540e\u7eed\u8865\u5145", "\u672c\u6b21\u53ea\u5199\u5165\u8f7b\u91cf\u89d2\u8272\u5e95\u5ea7\uff0c\u4e0d\u5f3a\u884c\u56fa\u5316\u6240\u6709\u5173\u7cfb\u3002"],
      ["\u8fb9\u754c\u5df2\u786e\u8ba4", "\u4e0d\u751f\u6210\u6b63\u6587\uff0c\u4e0d\u4fee\u6539\u4e16\u754c\u4e8b\u5b9e\u3002"],
    ].forEach(([title, text]) => {
      const button = doc.createElement("button");
      button.type = "button";
      button.className = "gate-button active mafs-backend-rendered";
      button.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(text)}</span>`;
      gateGrid.appendChild(button);
    });
    markBackendRendered(gateGrid);
  }

  const resultCards = Array.from(doc.querySelectorAll(".result-card"));
  setLabeledCardText(resultCards[0], "\u5f53\u524d\u89d2\u8272", `${name} / ${displayTier} \u7ea7 / ${identity}`);
  setLabeledCardText(resultCards[1], "\u5199\u5165\u72b6\u6001", "\u5f85\u7528\u6237\u786e\u8ba4\u5199\u5165");
  setLabeledCardText(resultCards[2], "\u4e0b\u4e00\u6b65", "\u5199\u5165\u540e\u8fdb\u5165\u89d2\u8272\u6863\u6848\u5e93");

  Array.from(doc.querySelectorAll(".side-card .summary-item")).forEach((item) => {
    item.classList.add("mafs-backend-rendered");
    markBackendRendered(item);
  });

  const confirmInput = doc.getElementById("confirmInput");
  if (confirmInput) {
    confirmInput.value = `\u786e\u8ba4\u5199\u5165 ${name} \u4f5c\u4e3a ${displayTier} \u7ea7\u89d2\u8272\uff1b\u672c\u6b65\u53ea\u5199\u5165\u89d2\u8272\u5e95\u5ea7\uff0c\u4e0d\u751f\u6210\u7ae0\u8282\u6b63\u6587\u3002`;
    markBackendRendered(confirmInput);
  }
  ["#confirmButton", "#sideConfirmButton"].forEach((selector) => {
    const button = doc.querySelector(selector);
    if (!button) {
      return;
    }
    button.disabled = false;
    button.textContent = "\u786e\u8ba4\u5199\u5165";
    button.dataset.mafsActionId = "characters.confirm";
    button.dataset.mafsTarget = "role-library";
    markBackendRendered(button);
  });
}

function suppressCharacterStaticText(doc, character) {
  if (!doc?.body || !character) {
    return;
  }
  const replacement = firstNonEmpty(
    character.name,
    characterProfileText(character, "description"),
    characterProfileText(character, "background_summary"),
    characterProfileText(character, "backgroundSummary"),
  );
  const stalePattern = /(暂无此项数据|正在读取项目数据|待后端接入|洛闻|低魔悬疑|港口城|旧钟|æš‚æ— æ­¤é¡¹æ•°æ®|æ­£åœ¨è¯»å–é¡¹ç›®æ•°æ®|å¾…åŽç«¯æŽ¥å…¥)/;
  const nodeFilter = doc.defaultView?.NodeFilter || window.NodeFilter;
  const walker = doc.createTreeWalker(doc.body, nodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const text = String(node.nodeValue || "").trim();
      if (!stalePattern.test(text)) {
        return nodeFilter.FILTER_REJECT;
      }
      const parent = node.parentElement;
      if (
        !parent ||
        parent.closest(
          "script, style, title, svg defs, button, a, input, select, textarea, option, [role='button'], [role='tab'], [data-mafs-live-status='true'], #mafs-character-panel",
        )
      ) {
        return nodeFilter.FILTER_REJECT;
      }
      return nodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) {
    nodes.push(walker.currentNode);
  }
  nodes.forEach((node, index) => {
    const parent = node.parentElement;
    node.nodeValue = index < 4 ? replacement : "";
    if (parent) {
      markBackendRendered(parent);
      parent.classList.toggle("mafs-empty-suppressed", index >= 4);
    }
  });
}

function updateStaticCharacterTierLabels(doc, tier) {
  const normalizedTier = normalizeCharacterTier(tier) || "A";
  const roleLabel = `${normalizedTier} 级角色`;
  const shortLabel = `${normalizedTier} 级`;
  setRenderedText(doc.getElementById("promptTitle"), roleLabel);
  setRenderedText(doc.getElementById("tierBadge"), roleLabel);
  doc.querySelectorAll("h3, strong, span, em, .badge").forEach((element) => {
    const compact = normalizeText(element.textContent || "");
    if (/^[A-D]级角色$/.test(compact) || /^[A-D]级主轴$/.test(compact)) {
      element.textContent = roleLabel;
      markBackendRendered(element);
    } else if (/^[A-D]级$/.test(compact)) {
      element.textContent = shortLabel;
      markBackendRendered(element);
    } else if (/^当前查看[A-D]级$/.test(compact)) {
      element.textContent = `当前查看 ${normalizedTier} 级`;
      markBackendRendered(element);
    }
  });
}

function renderCharacterPanel(doc, character, draft, tier) {
  const target =
    doc.querySelector(".draft-panel") ||
    doc.querySelector(".review-panel") ||
    doc.querySelector(".input-card") ||
    doc.querySelector(".work-panel") ||
    doc.body;
  if (!target) {
    return;
  }
  let panel = doc.getElementById("mafs-character-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-character-panel";
    panel.className = "mafs-character-panel mafs-backend-rendered";
    panel.setAttribute("aria-label", "后端角色草案");
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.92)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  const profile = character.profile || {};
  const state = character.current_state || character.currentState || {};
  const arc = character.arc_state || character.arcState || {};
  const displayTier = normalizeCharacterTier(tier || character.tier) || "A";
  const name = firstNonEmpty(character.name, "角色草案");
  const identity = firstNonEmpty(profile.identity, character.role, `${displayTier} 级角色`);
  const background = characterFallbackText(firstNonEmpty(profile.background_summary, profile.backgroundSummary, profile.description, draft?.latest_user_prompt, draft?.latestUserPrompt), "", 240);
  const goal = characterFallbackText(characterListText(profile.goals) || firstNonEmpty(state.active_goal, state.activeGoal), "", 180);
  const resources = characterListText(state.resources);
  const arcText = firstNonEmpty(arc.current_arc, arc.currentArc, arc.inner_conflict, arc.innerConflict);
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端角色草案</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">${escapeHtml(name)}</h3>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(displayTier)} 级 / ${escapeHtml(identity)}</strong></p>
    <p style="margin:0 0 8px;line-height:1.7;">${escapeHtml(background)}</p>
    <ul style="margin:0;padding-left:18px;line-height:1.7;">
      ${[goal, resources, arcText, characterListText(profile.traits), characterListText(profile.secrets)].filter(Boolean).slice(0, 6).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
  markBackendRendered(panel);
}

function renderCharacterSurface(doc, result) {
  const payload = findCharacterDraftPayload(result);
  if (!doc?.body || !payload?.character) {
    return false;
  }
  if (!isFramePage(doc, CHARACTER_PAGE_IDS)) {
    return false;
  }
  const framePageId = doc.body.dataset.mafsPageId || "";
  const draftSurfacePageIds = new Set([
    "character-generating",
    "character-review",
    "character-conflict",
    "character-missing",
    "character-revision",
    "character-confirm",
  ]);
  if (!draftSurfacePageIds.has(framePageId)) {
    return false;
  }
  const isCharacterPage =
    /角色主轴/.test(doc.body.textContent || "") &&
    doc.querySelector("#archiveTitle, #characterPrompt, #confirmButton, #reviewTitle, #promptTitle");
  if (!isCharacterPage) {
    return false;
  }
  const { character, draft } = payload;
  const profile = character.profile || {};
  const state = character.current_state || character.currentState || {};
  const arc = character.arc_state || character.arcState || {};
  const displayTier = characterPayloadTier(character, draft) || preferredCharacterTierFromResult(result) || "A";
  const name = firstNonEmpty(character.name, "角色草案");
  const identity = firstNonEmpty(profile.identity, character.role, `${displayTier} 级角色`);
  const description = characterFallbackText(firstNonEmpty(profile.description, profile.background_summary, profile.backgroundSummary, draft?.latest_user_prompt, draft?.latestUserPrompt), "", 240);
  const latestPrompt = firstNonEmpty(draft?.latest_user_prompt, draft?.latestUserPrompt, description);
  const background = characterFallbackText(firstNonEmpty(profile.background_summary, profile.backgroundSummary, description), "", 240);
  const goal = characterFallbackText(characterListText(profile.goals) || firstNonEmpty(state.active_goal, state.activeGoal), "", 180);
  const emotional = firstNonEmpty(state.emotional_state, state.emotionalState);
  const knowledge = characterFallbackText(characterListText(state.knowledge) || characterListText(profile.knowledge_scope || profile.knowledgeScope), "", 180);
  const bottomLine = firstNonEmpty(profile.personality_baseline?.bottom_line, profile.personalityBaseline?.bottomLine);
  const arcText = characterFallbackText(firstNonEmpty(arc.current_arc, arc.currentArc, arc.inner_conflict, arc.innerConflict, arc.possible_direction, arc.possibleDirection), "", 180);

  setRenderedText(doc.querySelector(".hero .lead"), description);
  setRenderedText(doc.querySelector(".panel-copy"), description);
  setRenderedText(doc.getElementById("pageState"), "草案已生成");
  setRenderedText(doc.getElementById("topStatus"), "角色草案已同步");
  setRenderedText(doc.getElementById("draftTitle"), `${name}角色草案是否成立？`);
  setRenderedText(doc.getElementById("archiveTitle"), name);
  setRenderedText(doc.getElementById("reviewTitle"), "后端角色草案");
  setRenderedText(doc.getElementById("relationDetail"), firstNonEmpty(arcText, background));
  setRenderedText(doc.querySelector(".draft-title span, .badge"), `${displayTier} 级角色`);
  updateStaticCharacterTierLabels(doc, displayTier);
  setRenderedText(doc.querySelector(".draft-panel p"), background);
  setRenderedText(doc.querySelector(".prompt-body"), latestPrompt);
  doc.querySelectorAll(".meta-row .mini-card").forEach((card) => {
    const label = normalizeText(card.querySelector("span")?.textContent || "");
    const value = card.querySelector("strong");
    if (label === "等级" && value) {
      setRenderedText(value, `${displayTier} 级`);
    }
    if (label === "写入" && value) {
      setRenderedText(value, "草案");
    }
  });

  const detailMap = [
    ["身份", identity],
    ["气质", characterListText(profile.traits)],
    ["目标", goal],
    ["秘密", characterListText(profile.secrets)],
    ["当前状态", emotional],
    ["记忆摘要", knowledge],
    ["性格底线", bottomLine],
    ["人物弧光", arcText],
  ].filter(([, value]) => Boolean(value));
  renderWorldCanvasFactList(doc, "#factList", detailMap);
  renderCharacterReviewSections(doc, character, draft, {
    displayTier,
    identity,
    description,
    background,
    goal,
    emotional,
    knowledge,
    bottomLine,
    arcText,
  });
  renderCharacterConfirmSections(doc, character, draft, {
    displayTier,
    identity,
    description,
    background,
    goal,
    emotional,
    knowledge,
    bottomLine,
    arcText,
  });

  const confirmButton = doc.getElementById("confirmButton");
  if (confirmButton) {
    confirmButton.disabled = false;
    confirmButton.textContent = framePageId === "character-confirm" ? "确认写入" : "确认草案";
    if (framePageId === "character-confirm") {
      confirmButton.dataset.mafsActionId = "characters.confirm";
      confirmButton.dataset.mafsTarget = "role-library";
    }
    markBackendRendered(confirmButton);
  }
  const reviewButton = doc.getElementById("reviewButton");
  if (reviewButton) {
    reviewButton.disabled = false;
    reviewButton.textContent = "è¿›å…¥è‰æ¡ˆå®¡é˜…";
    reviewButton.dataset.mafsActionId = "characters.current";
    reviewButton.dataset.mafsTarget = "character-review";
    reviewButton.textContent = "\u8fdb\u5165\u8349\u6848\u5ba1\u9605";
    markBackendRendered(reviewButton);
  }
  setControlValue(doc, ["#characterPrompt"], firstNonEmpty(draft?.latest_user_prompt, draft?.latestUserPrompt, description));
  renderCharacterPanel(doc, character, draft, displayTier);
  const isConfirmPage = /确认这些事实|角色底座|写入角色底座|确认角色主轴/.test(doc.body.textContent || "");
  if (framePageId === "character-confirm" && isConfirmPage && !doc.getElementById("saveRole")) {
    const actionTarget = doc.querySelector(".button-row") || doc.querySelector(".button-group") || doc.getElementById("mafs-character-panel") || doc.body;
    const libraryButton = doc.createElement("button");
    libraryButton.id = "saveRole";
    libraryButton.type = "button";
    libraryButton.className = "soft-button mafs-backend-rendered";
    libraryButton.textContent = "查看角色档案库";
    actionTarget.appendChild(libraryButton);
  }
  suppressCharacterStaticText(doc, character);
  applyRealtimeProgressElements(doc, { label: "角色草案已同步", percent: 100 });
  [120, 600, 1400].forEach((delayMs) => {
    window.setTimeout(() => suppressCharacterStaticText(doc, character), delayMs);
  });
  return true;
}

function renderRoleLibrarySurface(doc, result) {
  if (!isFramePage(doc, ROLE_LIBRARY_PAGE_IDS)) {
    return false;
  }
  if (!doc?.body || !/角色/.test(doc.body.textContent || "")) {
    return false;
  }
  const isRoleLibrary = /档案库|分级管理|角色库/.test(doc.body.textContent || "");
  if (!isRoleLibrary) {
    return false;
  }
  const roles = findNestedArray(result, ["roles", "characters", "items", "records"]).filter((item) => item && typeof item === "object");
  if (!roles.length) {
    return false;
  }
  const visibleRoles = roles.filter((role) => {
    const text = normalizeText(`${role?.name || ""} ${role?.profile?.description || ""} ${role?.profile?.background_summary || ""}`);
    return !/^(伊莱恩|洛闻|码头旅客|钟楼守卫)$/.test(String(role?.name || "").trim()) && !/(港口钟楼失忆事件|港口钟楼证词|旧钟楼|钟楼第十三声)/.test(text);
  });
  const displayRoles = visibleRoles.length ? visibleRoles : roles;
  try {
    doc.defaultView.parent.__mafsLastRoleLibraryRoles = displayRoles;
  } catch {
    // Same-origin cache is a convenience for the next iframe page only.
  }
  const primary = displayRoles[0];
  const profile = primary.profile || {};
  const state = primary.current_state || primary.currentState || {};
  const name = firstNonEmpty(primary.name, "角色档案");
  const background = characterFallbackText(firstNonEmpty(profile.background_summary, profile.backgroundSummary, profile.description), "角色档案已同步。", 240);
  const goal = characterFallbackText(characterListText(profile.goals) || firstNonEmpty(state.active_goal, state.activeGoal), "", 160);
  const roleLabel = characterFallbackText(firstNonEmpty(primary.role, profile.identity, "supporting_npc"), "角色功能", 80);
  const roleTypeLabel = String(primary.role || "").toLowerCase() === "protagonist" ? "主角" : roleLabel;
  const list = doc.getElementById("roleList");
  if (list) {
    list.innerHTML = "";
    displayRoles.forEach((role, index) => {
      const roleProfile = role.profile || {};
      const roleState = role.current_state || role.currentState || {};
      const item = doc.createElement("button");
      item.type = "button";
      item.className = `item mafs-backend-rendered${index === 0 ? " selected" : ""}`;
      const itemName = firstNonEmpty(role.name, "\u672a\u547d\u540d\u89d2\u8272");
      const itemTier = normalizeCharacterTier(role.tier) || "A";
      const itemSummary = characterFallbackText(firstNonEmpty(roleProfile.background_summary, roleProfile.backgroundSummary, roleProfile.description, roleState.active_goal, roleState.activeGoal), "\u89d2\u8272\u6863\u6848\u5df2\u540c\u6b65\u3002", 180);
      const itemFunction = characterFallbackText(firstNonEmpty(roleProfile.story_function, roleProfile.storyFunction, role.role), "\u89d2\u8272\u529f\u80fd", 80);
      item.innerHTML = `<div class="item-head"><strong>${escapeHtml(itemName)}</strong><span class="badge">${escapeHtml(itemTier)} \u7ea7</span></div><p>${escapeHtml(itemSummary)}</p><small>${escapeHtml(role.status || "confirmed")} · ${escapeHtml(itemFunction)}</small>`;
      list.appendChild(item);
    });
    markBackendRendered(list);
  }
  const tierCounts = displayRoles.reduce((counts, role) => {
    const tier = normalizeCharacterTier(role.tier) || "A";
    counts[tier] = (counts[tier] || 0) + 1;
    return counts;
  }, {});
  Array.from(doc.querySelectorAll(".stats-grid .stat")).forEach((stat) => {
    const tier = normalizeText(stat.querySelector("span")?.textContent || "");
    const strong = stat.querySelector("strong");
    if (strong && ["A", "B", "C", "D"].includes(tier)) {
      setRenderedText(strong, String(tierCounts[tier] || 0));
    }
  });
  setRenderedText(doc.getElementById("roleName"), name);
  setRenderedText(doc.getElementById("roleSummary"), background || goal || "\u89d2\u8272\u6863\u6848\u5df2\u540c\u6b65\u3002");
  setRenderedText(doc.getElementById("roleTier"), `${normalizeCharacterTier(primary.tier) || "A"} \u7ea7`);
  setRenderedText(doc.getElementById("roleStatus"), primary.status || "confirmed");
  setRenderedText(doc.getElementById("roleProtection"), normalizeCharacterTier(primary.tier) === "A" ? "A \u7ea7\u4fdd\u62a4" : "\u53ef\u7ba1\u7406\u89d2\u8272");
  setControlValue(doc, ["#editName"], name);
  setControlValue(doc, ["#editFunction"], roleLabel);
  setControlValue(doc, ["#editSummary"], background || goal);
  const targetTier = doc.getElementById("targetTier");
  if (targetTier) {
    targetTier.value = normalizeCharacterTier(primary.tier) || "B";
    markBackendRendered(targetTier);
  }
  setControlValue(doc, ["#archiveReason"], "\u7528\u6237\u786e\u8ba4\u540e\u518d\u6267\u884c\u5f52\u6863\u3002");
  setControlValue(doc, ["#tierNote"], "\u672c\u6b65\u53ea\u4fee\u6539\u89d2\u8272\u5e93\uff0c\u4e0d\u76f4\u63a5\u6539\u5199\u4e16\u754c\u3001\u7ae0\u8282\u6216\u573a\u666f\u6b63\u6587\u3002");
  setControlValue(doc, ["#newName"], "");
  setControlValue(doc, ["#newTier"], "B");
  const newRoleText = doc.querySelector("textarea[aria-label='新角色职能'], textarea[aria-label='æ–°è§’è‰²èŒèƒ½']");
  if (newRoleText) {
    newRoleText.value = "";
    newRoleText.placeholder = "\u5199\u4e0b\u65b0\u89d2\u8272\u7684\u6545\u4e8b\u804c\u80fd\u4e0e\u8fb9\u754c\u3002";
    markBackendRendered(newRoleText);
  }
  doc.getElementById("buildContext")?.setAttribute("data-mafs-target", "role-context");
  doc.getElementById("buildContext")?.setAttribute("data-mafs-action-id", "roles.contextPreview");
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-role-library-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-role-library-panel";
    panel.className = "mafs-role-library-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.92)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端角色档案库</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">${escapeHtml(name)}</h3>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(primary.tier || "A")} 级角色</strong> · ${escapeHtml(roleTypeLabel)}</p>
    <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(background || goal || "角色档案已从后端同步。")}</p>
    <button id="mafsRoleContextButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="role-context" data-mafs-action-id="roles.contextPreview">上下文预览</button>
  `;
  markBackendRendered(panel);
  setRenderedText(doc.querySelector(".hero .lead"), `${name}已写入角色档案库，可进入上下文预览。`);
  suppressCharacterStaticText(doc, primary);
  applyRealtimeProgressElements(doc, { label: "角色档案库已同步", percent: 100 });
  return true;
}

function renderRoleContextSurface(doc, result) {
  if (!isFramePage(doc, ROLE_CONTEXT_PAGE_IDS)) {
    return false;
  }
  if (!doc?.body || !/角色上下文预览|上下文预览/.test(doc.body.textContent || "")) {
    return false;
  }
  let items = findNestedArray(result, ["items", "context_items", "contextItems"]).filter((item) => item && typeof item === "object");
  let cachedRoles = [];
  try {
    cachedRoles = Array.isArray(doc.defaultView.parent.__mafsLastRoleLibraryRoles)
      ? doc.defaultView.parent.__mafsLastRoleLibraryRoles
      : [];
  } catch {
    cachedRoles = [];
  }
  const rolesForContext = cachedRoles.length
    ? cachedRoles
    : findNestedArray(result, ["roles", "characters", "records"]).filter((item) => item && typeof item === "object");
  if (rolesForContext.length) {
    const roleItems = rolesForContext.map((role) => {
      const profile = role.profile || {};
      const state = role.current_state || role.currentState || {};
      const arc = role.arc_state || role.arcState || {};
      return {
        character_id: role.character_id || role.characterId || role.id || "",
        name: role.name,
        tier: role.tier,
        profile_summary: firstNonEmpty(role.profile_summary, role.profileSummary, profile.identity, profile.story_function, profile.storyFunction, profile.background_summary, profile.backgroundSummary, profile.description),
        current_state_summary: firstNonEmpty(role.current_state_summary, role.currentStateSummary, state.active_goal, state.activeGoal, state.emotional_state, state.emotionalState),
        personality_summary: firstNonEmpty(role.personality_summary, role.personalitySummary, characterListText(profile.traits)),
        memory_summary: firstNonEmpty(role.memory_summary, role.memorySummary, role.memory_summary?.summary, role.memorySummary?.summary, profile.background_summary, profile.description),
        arc_summary: firstNonEmpty(role.arc_summary, role.arcSummary, arc.current_arc, arc.currentArc, arc.inner_conflict, arc.innerConflict),
        forbidden_knowledge: role.forbidden_knowledge || role.forbiddenKnowledge || profile.forbidden_knowledge || profile.forbiddenKnowledge || [],
        hard_limits: (role.hard_limits || role.hardLimits || profile.hard_limits || profile.hardLimits || []).map((limit) => worldCanvasText(limit)),
      };
    });
    const contextLooksGeneric = !items.length || items.every((item) => {
      const text = normalizeText(`${item.profile_summary || item.profileSummary || ""} ${item.current_state_summary || item.currentStateSummary || ""} ${item.memory_summary || item.memorySummary || ""}`);
      return !text || /角色上下文已从后端同步|暂无此项数据/.test(text);
    });
    if (cachedRoles.length || contextLooksGeneric) {
      items = roleItems;
    }
  }
  if (!items.length) {
    return false;
  }
  const primary = items[0];
  const name = firstNonEmpty(primary.name, "角色上下文");
  const tier = firstNonEmpty(primary.tier, "A");
  const profile = characterFallbackText(firstNonEmpty(primary.profile_summary, primary.profileSummary, primary.summary), "角色上下文已从后端同步。", 220);
  const state = characterFallbackText(firstNonEmpty(primary.current_state_summary, primary.currentStateSummary), "", 180);
  const arc = characterFallbackText(firstNonEmpty(primary.arc_summary, primary.arcSummary), "", 180);
  const personality = characterFallbackText(firstNonEmpty(primary.personality_summary, primary.personalitySummary), "", 160);
  const forbidden = characterFallbackText(characterListText(primary.forbidden_knowledge || primary.forbiddenKnowledge || primary.hard_limits || primary.hardLimits), "", 180);
  const contextItems = items.slice(0, 8).map((item) => ({
    name: firstNonEmpty(item.name, "角色"),
    tier: firstNonEmpty(item.tier, "A"),
    summary: characterFallbackText(firstNonEmpty(item.profile_summary, item.profileSummary, item.current_state_summary, item.currentStateSummary, item.memory_summary, item.memorySummary), "角色上下文已同步。", 180),
  }));
  const list = doc.querySelector(".list");
  if (list) {
    list.innerHTML = contextItems.map((item, index) => `
      <div class="item mafs-backend-rendered${index === 0 ? " selected" : ""}">
        <div class="item-head"><strong>${escapeHtml(item.name)}</strong><span class="badge ${index === 0 ? "sage" : ""}">${escapeHtml(item.tier)}</span></div>
        <p>${escapeHtml(item.summary)}</p>
      </div>
    `).join("");
    markBackendRendered(list);
  }
  Array.from(doc.querySelectorAll(".stats-grid .stat")).forEach((stat) => {
    const label = normalizeText(stat.querySelector("span")?.textContent || "");
    const value = stat.querySelector("strong");
    if (!value) {
      return;
    }
    if (label.includes("角色")) {
      setRenderedText(value, String(items.length));
    } else if (label.includes("保护")) {
      setRenderedText(value, String(items.filter((item) => normalizeCharacterTier(item.tier) === "A").length));
    } else if (label.includes("风险")) {
      setRenderedText(value, forbidden ? "1" : "0");
    }
  });
  const timelineSteps = Array.from(doc.querySelectorAll(".timeline .step"));
  const downstreamSummaries = [
    `身份：${characterFallbackText(profile, "角色身份与故事职能已同步。", 120)}`,
    `边界：${forbidden || "遵守已确认关系、冲突和世界硬规则。"}`,
    `目标：${characterFallbackText(firstNonEmpty(state, arc, personality), "角色当前目标与弧光已同步。", 120)}`,
  ];
  timelineSteps.forEach((step, index) => {
    const summary = step.querySelector("p");
    if (summary && downstreamSummaries[index]) {
      setRenderedText(summary, downstreamSummaries[index]);
    }
  });
  setRenderedText(doc.querySelector(".top-actions .badge:not(.sage)"), "上下文包");
  setRenderedText(doc.querySelector("section.panel .eyebrow"), "预览请求");
  setRenderedText(doc.querySelector("aside.panel .eyebrow"), "只读结果");
  setRenderedText(doc.getElementById("previewText"), `${name}：${profile}`);
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-role-context-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-role-context-panel";
    panel.className = "mafs-role-context-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.94)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端角色上下文包</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">${escapeHtml(name)} · ${escapeHtml(tier)}级</h3>
    <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(profile || "角色上下文已从后端同步。")}</p>
    <ul style="margin:0 0 14px 18px;padding:0;line-height:1.7;">
      ${[state, personality, arc, forbidden ? `禁止越权知识：${forbidden}` : ""]
        .filter(Boolean)
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("")}
    </ul>
    <button id="confirmButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="chapter-source" data-mafs-action-id="characters.finishMainCast">进入章节计划</button>
  `;
  const confirmButton = doc.getElementById("confirmButton");
  if (confirmButton) {
    confirmButton.dataset.mafsActionId = "characters.finishMainCast";
    confirmButton.dataset.mafsTarget = "framework";
    confirmButton.textContent = "进入 Framework 编排";
    markBackendRendered(confirmButton);
  }
  ["伊莱恩", "洛闻", "码头旅客"].forEach((staleName) => {
    doc.querySelectorAll("body *").forEach((element) => {
      if (element === panel || panel.contains(element)) {
        return;
      }
      if (element.childElementCount === 0 && element.textContent?.includes(staleName)) {
        element.textContent = element.textContent.replaceAll(staleName, name);
        markBackendRendered(element);
      }
    });
  });
  setRenderedText(doc.querySelector(".hero .lead"), `${name}的角色上下文已同步，可用于章节计划与场景写作。`);
  setRenderedText(doc.getElementById("topStatus"), "角色上下文已同步");
  setRenderedText(doc.getElementById("actionNote"), "角色上下文已从后端同步，请先确认 Framework 编排，再进入章节计划。");
  replaceEmptyPlaceholders(doc, "后端已同步");
  markBackendRendered(panel);
  applyRealtimeProgressElements(doc, { label: "角色上下文已同步", percent: 100 });
  return true;
}

function replaceEmptyPlaceholders(doc, replacement = "已同步") {
  if (!doc?.body || !doc.defaultView?.NodeFilter) {
    return;
  }
  const walker = doc.createTreeWalker(doc.body, doc.defaultView.NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) {
    textNodes.push(walker.currentNode);
  }
  textNodes.forEach((node) => {
    const parent = node.parentElement;
    if (
      parent?.closest?.(
        "script, style, title, svg defs, button, a, input, select, textarea, option, [role='button'], [role='tab'], [data-mafs-live-status='true']",
      )
    ) {
      return;
    }
    if (/(暂无此项数据|正在读取项目数据|待后端接入)/.test(node.nodeValue || "")) {
      node.nodeValue = String(node.nodeValue || "")
        .replaceAll("暂无此项数据", replacement)
        .replaceAll("正在读取项目数据", replacement)
        .replaceAll("待后端接入", replacement);
    }
  });
  doc.querySelectorAll("body *").forEach((element) => {
    if (element.closest("button, a, input, select, textarea, option, [role='button'], [role='tab'], [data-mafs-live-status='true']")) {
      return;
    }
    const text = (element.textContent || "").trim();
    if (element.childElementCount === 0 && /(暂无此项数据|正在读取项目数据|待后端接入)/.test(text) && text.length <= 40) {
      element.textContent = replacement;
      markBackendRendered(element);
    }
  });
}

function frameworkItemTypeLabel(type) {
  const normalized = String(type || "").toLowerCase();
  if (normalized.includes("macro")) {
    return "全局骨架组件";
  }
  if (normalized.includes("chapter")) {
    return "篇章模块";
  }
  return "Framework 组件";
}

function frameworkRecordText(value, fallback = "", maxLength = 180) {
  if (value === null || value === undefined) {
    return fallback;
  }
  let text = "";
  if (Array.isArray(value)) {
    text = value.map((item) => frameworkRecordText(item, "", 0)).filter(Boolean).join("；");
  } else if (typeof value === "object") {
    text = firstNonEmpty(
      value.label,
      value.title,
      value.name,
      value.safe_summary,
      value.safeSummary,
      value.description,
      value.instruction,
      value.normalized_hint,
      value.normalizedHint,
      value.reason,
      value.summary,
    );
  } else {
    text = String(value || "").trim();
  }
  text = text.replace(/\s+/g, " ").trim();
  if (!text) {
    return fallback;
  }
  if (maxLength > 0 && text.length > maxLength) {
    return `${text.slice(0, maxLength).trim()}...`;
  }
  return text;
}

function frameworkMaterialType(value, fallback = "module_component") {
  const normalized = String(value || fallback || "").toLowerCase();
  if (normalized.includes("chapter")) {
    return "chapter_module";
  }
  if (normalized.includes("macro")) {
    return "macro_component";
  }
  if (normalized.includes("private")) {
    return "private_framework";
  }
  return fallback;
}

function frameworkMaterialId(record, type, index) {
  return firstNonEmpty(
    record?.library_item_id,
    record?.libraryItemId,
    record?.component_id,
    record?.componentId,
    record?.module_id,
    record?.moduleId,
    record?.private_framework_id,
    record?.privateFrameworkId,
    record?.system_recommendation_id,
    record?.systemRecommendationId,
    record?.id,
    `${type}_${index + 1}`,
  );
}

function isFrameworkLibraryMaterial(material) {
  const raw = material?.raw || material || {};
  return Boolean(
    raw.library_item_id ||
      raw.libraryItemId ||
      raw.private_framework_id ||
      raw.privateFrameworkId ||
      raw.system_recommendation_id ||
      raw.systemRecommendationId,
  );
}

function frameworkSourceLabel(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("analyze")) {
    return "Analyze Stories";
  }
  if (normalized.includes("user")) {
    return "用户私有";
  }
  if (normalized.includes("system")) {
    return "系统内置";
  }
  if (normalized.includes("m4") || normalized.includes("m6")) {
    return "导入包";
  }
  return value || "当前项目";
}

function frameworkMaterialFromRecord(record, index, forcedType = "") {
  if (!record || typeof record !== "object") {
    return null;
  }
  const type = frameworkMaterialType(forcedType || record.item_type || record.itemType || record.type || record.scope, forcedType || "module_component");
  const id = frameworkMaterialId(record, type, index);
  const title = firstNonEmpty(
    record.label,
    record.title,
    record.name,
    record.component_id,
    record.componentId,
    record.module_id,
    record.moduleId,
    id,
  );
  const allowedComponents = Array.isArray(record.allowed_components)
    ? record.allowed_components
    : Array.isArray(record.allowedComponents)
      ? record.allowedComponents
      : [];
  const allowedSummary = allowedComponents.map((item) => frameworkRecordText(item, "", 60)).filter(Boolean).join(" / ");
  const summary = firstNonEmpty(
    frameworkRecordText(record.safe_summary || record.safeSummary, "", 180),
    frameworkRecordText(record.description, "", 180),
    frameworkRecordText(record.instruction, "", 180),
    frameworkRecordText(record.normalized_hint || record.normalizedHint, "", 180),
    allowedSummary ? `可搭配：${allowedSummary}` : "",
    `${frameworkItemTypeLabel(type)}已从后端同步。`,
  );
  return {
    id,
    type,
    title,
    summary,
    source: frameworkSourceLabel(record.source_type || record.sourceType || record.source || record.visibility),
    raw: record,
  };
}

function pushFrameworkMaterial(output, seen, material) {
  if (!material?.id || seen.has(material.id)) {
    return;
  }
  seen.add(material.id);
  output.push(material);
}

function mergeFrameworkMaterialLists(...lists) {
  const output = [];
  const seen = new Set();
  const seenSemantic = new Set();
  lists.forEach((list) => {
    if (!Array.isArray(list)) {
      return;
    }
    list.forEach((item) => {
      if (!item?.id) {
        return;
      }
      const semanticKey = `${String(item.type || "").trim().toLowerCase()}::${String(item.title || "")
        .replace(/\s+/g, " ")
        .trim()
        .toLowerCase()}`;
      if (semanticKey !== "::" && seenSemantic.has(semanticKey)) {
        return;
      }
      pushFrameworkMaterial(output, seen, item);
      if (semanticKey !== "::") {
        seenSemantic.add(semanticKey);
      }
    });
  });
  return output;
}

function frameworkPackageFromResult(result) {
  const action = result?.action_result || result?.actionResult || {};
  return (
    action.framework_package ||
    action.frameworkPackage ||
    action.package ||
    result?.framework_package ||
    result?.frameworkPackage ||
    findNestedObject(result, (item) => Boolean(item?.macro_framework || item?.macroFramework || item?.component_vocabulary || item?.componentVocabulary)) ||
    {}
  );
}

function frameworkWorkbenchFromResult(result) {
  const action = result?.action_result || result?.actionResult || {};
  return (
    action.workbench ||
    action.framework_workbench ||
    action.frameworkWorkbench ||
    result?.workbench ||
    result?.framework_workbench ||
    result?.frameworkWorkbench ||
    findNestedObject(result, (item) => Array.isArray(item?.macro_components || item?.macroComponents) && Array.isArray(item?.chapter_macro_assignments || item?.chapterMacroAssignments)) ||
    {}
  );
}

function collectFrameworkLibraryRecords(value, records, visited = new Set()) {
  if (!value || typeof value !== "object" || visited.has(value)) {
    return;
  }
  visited.add(value);
  if (Array.isArray(value)) {
    value.forEach((item) => collectFrameworkLibraryRecords(item, records, visited));
    return;
  }
  if (
    value.library_item_id ||
    value.libraryItemId ||
    value.private_framework_id ||
    value.privateFrameworkId ||
    value.system_recommendation_id ||
    value.systemRecommendationId
  ) {
    records.push(value);
  }
  Object.entries(value).forEach(([key, child]) => {
    if (/source_refs?|warnings?|validation|metadata/i.test(key)) {
      return;
    }
    collectFrameworkLibraryRecords(child, records, visited);
  });
}

function frameworkLibraryItemsFromResult(result) {
  const action = result?.action_result || result?.actionResult || {};
  const containers = [
    action.framework_library_items,
    action.framework_library_items?.items,
    action.frameworkLibraryItems,
    action.frameworkLibraryItems?.items,
    action.library_items,
    action.library_items?.items,
    action.libraryItems,
    action.libraryItems?.items,
    action.private_frameworks,
    action.privateFrameworks,
    action.system_recommendations,
    action.systemRecommendations,
    action.items,
    result?.framework_library_items,
    result?.framework_library_items?.items,
    result?.frameworkLibraryItems,
    result?.frameworkLibraryItems?.items,
    result?.library_items,
    result?.library_items?.items,
    result?.libraryItems,
    result?.libraryItems?.items,
    result?.private_frameworks,
    result?.privateFrameworks,
    result?.system_recommendations,
    result?.systemRecommendations,
    result?.items,
  ];
  const records = [];
  containers.forEach((container) => {
    collectFrameworkLibraryRecords(container, records);
  });
  return records;
}

function frameworkMaterialsFromResult(result) {
  const packageData = frameworkPackageFromResult(result);
  const workbench = frameworkWorkbenchFromResult(result);
  const vocabulary = packageData.component_vocabulary || packageData.componentVocabulary || {};
  const macroFramework = packageData.macro_framework || packageData.macroFramework || {};
  const materials = [];
  const seen = new Set();

  [
    ...(Array.isArray(workbench.macro_components) ? workbench.macro_components : []),
    ...(Array.isArray(workbench.macroComponents) ? workbench.macroComponents : []),
    ...(Array.isArray(macroFramework.components) ? macroFramework.components : []),
    ...(Array.isArray(vocabulary.macro_components) ? vocabulary.macro_components : []),
    ...(Array.isArray(vocabulary.macroComponents) ? vocabulary.macroComponents : []),
  ].forEach((record, index) => pushFrameworkMaterial(materials, seen, frameworkMaterialFromRecord(record, index, "macro_component")));

  [
    ...(Array.isArray(vocabulary.chapter_modules) ? vocabulary.chapter_modules : []),
    ...(Array.isArray(vocabulary.chapterModules) ? vocabulary.chapterModules : []),
  ].forEach((record, index) => pushFrameworkMaterial(materials, seen, frameworkMaterialFromRecord(record, index, "chapter_module")));

  [
    ...(Array.isArray(vocabulary.module_components) ? vocabulary.module_components : []),
    ...(Array.isArray(vocabulary.moduleComponents) ? vocabulary.moduleComponents : []),
  ].forEach((record, index) => pushFrameworkMaterial(materials, seen, frameworkMaterialFromRecord(record, index, "module_component")));

  frameworkLibraryItemsFromResult(result).forEach((record, index) => {
    pushFrameworkMaterial(materials, seen, frameworkMaterialFromRecord(record, index, record.item_type || record.itemType));
  });

  return materials;
}

function frameworkAssignmentList(result) {
  const workbench = frameworkWorkbenchFromResult(result);
  const packageData = frameworkPackageFromResult(result);
  return (
    workbench.chapter_macro_assignments ||
    workbench.chapterMacroAssignments ||
    packageData.chapter_macro_assignments ||
    packageData.chapterMacroAssignments ||
    []
  ).filter((item) => item && typeof item === "object");
}

function frameworkInitialCanvasItems(result, materials) {
  const byId = new Map(materials.map((item) => [item.id, item]));
  const selected = [];
  frameworkAssignmentList(result).forEach((assignment) => {
    const ids = assignment.linked_macro_component_ids || assignment.linkedMacroComponentIds || [];
    ids.forEach((id) => {
      const material = byId.get(id);
      if (material && !selected.some((item) => item.id === material.id)) {
        selected.push(material);
      }
    });
  });
  if (selected.length) {
    return selected;
  }
  const projectMacro = materials.filter((item) => item.type === "macro_component" && !isFrameworkLibraryMaterial(item));
  if (projectMacro.length) {
    return projectMacro;
  }
  const macro = materials.filter((item) => item.type === "macro_component");
  return macro.length ? macro.slice(0, 5) : materials.slice(0, 5);
}

function frameworkVisibleMaterials(materials, filter) {
  if (filter === "macro") {
    return materials.filter((item) => item.type === "macro_component");
  }
  if (filter === "chapter") {
    return materials.filter((item) => item.type === "chapter_module" || item.type === "module_component");
  }
  if (filter === "library") {
    return materials.filter((item) => isFrameworkLibraryMaterial(item));
  }
  return materials;
}

function frameworkMaterialCounts(materials) {
  return {
    all: materials.length,
    macro: materials.filter((item) => item.type === "macro_component").length,
    chapter: materials.filter((item) => item.type === "chapter_module" || item.type === "module_component").length,
    library: materials.filter((item) => isFrameworkLibraryMaterial(item)).length,
  };
}

function ensureFrameworkWorkbenchStyle(doc) {
  if (!doc?.head || doc.getElementById("mafs-framework-workbench-style")) {
    return;
  }
  const style = doc.createElement("style");
  style.id = "mafs-framework-workbench-style";
  style.textContent = `
    .mafs-framework-material-card,
    .mafs-framework-canvas-item {
      display: block !important;
      grid-template-columns: none !important;
      width: 100%;
      text-align: left;
      border: 1px solid rgba(121, 89, 74, 0.16);
      border-radius: 8px;
      background: rgba(255, 252, 244, 0.84);
      color: #2d2823;
      padding: 12px;
      cursor: grab;
    }
    .material-list {
      overflow-y: auto !important;
      overflow-x: hidden !important;
      padding-right: 4px;
      scrollbar-width: thin;
      scrollbar-color: rgba(119, 100, 86, 0.26) rgba(255, 252, 244, 0.18);
    }
    .mafs-framework-material-card.material-card {
      min-height: auto !important;
      gap: 0 !important;
      transform: none;
    }
    .mafs-framework-material-card strong,
    .mafs-framework-canvas-item strong {
      display: block;
      font-size: 15px;
      line-height: 1.35;
    }
    .mafs-framework-material-card + .mafs-framework-material-card { margin-top: 10px; }
    .mafs-framework-list-count {
      margin-bottom: 10px;
      border: 1px solid rgba(121, 89, 74, 0.14);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.58);
      color: #6b5d51;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.4;
      padding: 8px 10px;
    }
    .mafs-framework-material-card.active,
    .mafs-framework-canvas-item.active {
      border-color: rgba(86, 114, 103, 0.75);
      box-shadow: 0 10px 26px rgba(67, 52, 40, 0.1);
    }
    .mafs-framework-material-card p,
    .mafs-framework-canvas-item p { margin: 6px 0 8px; line-height: 1.6; }
    .mafs-framework-card-meta {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
      color: #6b5d51;
      font-size: 12px;
      line-height: 1.4;
    }
    .mafs-framework-add,
    .mafs-framework-remove {
      border: 1px solid rgba(121, 89, 74, 0.18);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.72);
      color: #2d2823;
      padding: 6px 10px;
      font-weight: 800;
      cursor: pointer;
    }
    .mafs-framework-add { margin-left: auto; }
    .mafs-framework-dropzone {
      min-height: 132px;
      display: flex;
      gap: 12px;
      align-items: stretch;
      padding: 14px;
      border: 1px dashed rgba(86, 114, 103, 0.44);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.34);
      overflow-x: auto;
    }
    .mafs-framework-dropzone.is-drag-over { background: rgba(86, 114, 103, 0.08); }
    .mafs-framework-canvas-item {
      flex: 0 0 184px;
      min-height: 118px;
      cursor: default;
    }
    .mafs-framework-empty {
      width: 100%;
      display: grid;
      place-items: center;
      min-height: 100px;
      color: #6b5d51;
      border-radius: 8px;
      background: rgba(255, 252, 244, 0.52);
    }
  `;
  doc.head.appendChild(style);
}

function renderFrameworkMaterialCards(doc, materials, filter, selectedId) {
  const list = doc.querySelector(".material-list");
  if (!list) {
    return;
  }
  const visible = frameworkVisibleMaterials(materials, filter);
  const countLabel = `<div class="mafs-framework-list-count">当前筛选显示 ${visible.length} / ${materials.length} 个 Framework 素材；列表可滚动查看全部内容。</div>`;
  list.innerHTML = visible.length
    ? `${countLabel}${visible.map((item) => `
        <article class="mafs-framework-material-card material-card${item.id === selectedId ? " active" : ""}" draggable="true" data-framework-id="${escapeHtml(item.id)}" data-framework-type="${escapeHtml(item.type)}">
          <strong>${escapeHtml(item.title)}</strong>
          <p>${escapeHtml(item.summary)}</p>
          <div class="mafs-framework-card-meta">
            <span>${escapeHtml(frameworkItemTypeLabel(item.type))}</span>
            <span>${escapeHtml(item.source)}</span>
            <button class="mafs-framework-add" type="button" data-framework-id="${escapeHtml(item.id)}">加入画布</button>
          </div>
        </article>
      `).join("")}`
    : `${countLabel}<div class="mafs-framework-empty">当前分类没有可用 Framework 素材。</div>`;
  markBackendRendered(list);
}

function renderFrameworkCanvas(doc, canvasItems, selectedId) {
  const track = doc.getElementById("skeletonTrack");
  if (!track) {
    return;
  }
  track.classList.add("mafs-framework-dropzone");
  track.innerHTML = canvasItems.length
    ? canvasItems.map((item, index) => `
        <article class="mafs-framework-canvas-item slot-card${item.id === selectedId ? " active" : ""}" data-framework-id="${escapeHtml(item.id)}">
          <div class="slot-pin">${index + 1}</div>
          <strong>${escapeHtml(item.title)}</strong>
          <p>${escapeHtml(item.summary)}</p>
          <small>${escapeHtml(frameworkItemTypeLabel(item.type))}</small>
          <div style="margin-top:8px;">
            <button class="mafs-framework-remove" type="button" data-framework-id="${escapeHtml(item.id)}">移出</button>
          </div>
        </article>
      `).join("")
    : `<div class="mafs-framework-empty">把左侧 Framework 组件拖到这里，或点击“加入画布”。</div>`;
  markBackendRendered(track);
}

function renderFrameworkRoutePreview(doc, canvasItems, assignments) {
  const routeList = doc.getElementById("routeList");
  if (!routeList) {
    return;
  }
  const rows = assignments.length
    ? assignments.slice(0, 20).map((assignment, index) => {
        const chapterIndex = Number(assignment.chapter_index || assignment.chapterIndex || index + 1) || index + 1;
        const linked = assignment.linked_macro_component_ids || assignment.linkedMacroComponentIds || [];
        const linkedLabels = linked
          .map((id) => canvasItems.find((item) => item.id === id)?.title || id)
          .filter(Boolean)
          .join(" / ");
        return {
          index: chapterIndex,
          title: linkedLabels || `第 ${chapterIndex} 章 Framework 映射`,
          summary: firstNonEmpty(assignment.reason, assignment.status, assignment.assignment_type, assignment.assignmentType, "等待用户确认映射。"),
        };
      })
    : canvasItems.map((item, index) => ({
        index: index + 1,
        title: item.title,
        summary: `${frameworkItemTypeLabel(item.type)} / ${item.summary}`,
      }));
  routeList.innerHTML = rows.length
    ? rows.map((row, index) => `
        <button class="chapter-node${index === 0 ? " active" : ""}" data-chapter="${row.index}" type="button">
          <span class="chapter-no">${row.index}</span>
          <span class="chapter-main">
            <strong>${escapeHtml(row.title)}</strong>
            <p>${escapeHtml(row.summary)}</p>
          </span>
        </button>
      `).join("")
    : `<div class="mafs-framework-empty">画布中暂无可预览的 Framework 映射。</div>`;
  markBackendRendered(routeList);
}

function syncFrameworkHiddenForm(doc, canvasItems) {
  let hidden = doc.getElementById("mafsFrameworkLinkedIds");
  if (!hidden) {
    hidden = doc.createElement("input");
    hidden.type = "hidden";
    hidden.id = "mafsFrameworkLinkedIds";
    hidden.name = "linkedMacroComponentIds";
    doc.body.appendChild(hidden);
  }
  hidden.value = canvasItems.map((item) => item.id).join(",");
  let note = doc.getElementById("mafsFrameworkNote");
  if (!note) {
    note = doc.createElement("input");
    note.type = "hidden";
    note.id = "mafsFrameworkNote";
    note.name = "frameworkNote";
    doc.body.appendChild(note);
  }
  note.value = `用户在 Framework 编排页选择：${canvasItems.map((item) => item.title).join(" / ")}`;
}

function updateFrameworkSelection(doc, material) {
  if (!material) {
    return;
  }
  setRenderedText(doc.getElementById("compositionTitle"), material.title);
  setRenderedText(doc.getElementById("compositionCopy"), material.summary);
  setRenderedText(doc.getElementById("detailKicker"), frameworkItemTypeLabel(material.type));
  setRenderedText(doc.getElementById("detailTitle"), material.title);
  setRenderedText(doc.getElementById("detailCopy"), material.summary);
  setRenderedText(doc.getElementById("detailStepOne"), frameworkItemTypeLabel(material.type));
  setRenderedText(doc.getElementById("detailStepTwo"), material.source);
  setRenderedText(doc.getElementById("detailStepThree"), "可加入当前编排，确认后进入后续工作台。");
}

function bindFrameworkWorkbenchInteractions(doc, materials, assignments) {
  const view = doc.defaultView;
  if (!view) {
    return;
  }
  view.__mafsFrameworkMaterialsById = new Map(materials.map((item) => [item.id, item]));
  const render = () => {
    const selectedId = view.__mafsFrameworkSelectedId || view.__mafsFrameworkCanvasItems?.[0]?.id || materials[0]?.id || "";
    renderFrameworkMaterialCards(doc, materials, view.__mafsFrameworkFilter || "all", selectedId);
    renderFrameworkCanvas(doc, view.__mafsFrameworkCanvasItems || [], selectedId);
    renderFrameworkRoutePreview(doc, view.__mafsFrameworkCanvasItems || [], assignments);
    syncFrameworkHiddenForm(doc, view.__mafsFrameworkCanvasItems || []);
    const selected = view.__mafsFrameworkMaterialsById.get(selectedId) || view.__mafsFrameworkCanvasItems?.[0] || materials[0];
    updateFrameworkSelection(doc, selected);
    bindCards();
  };
  const addToCanvas = (id) => {
    const material = view.__mafsFrameworkMaterialsById.get(id);
    if (!material) {
      return;
    }
    if (!view.__mafsFrameworkCanvasItems.some((item) => item.id === material.id)) {
      view.__mafsFrameworkCanvasItems.push(material);
    }
    view.__mafsFrameworkSelectedId = material.id;
    render();
  };
  const removeFromCanvas = (id) => {
    view.__mafsFrameworkCanvasItems = view.__mafsFrameworkCanvasItems.filter((item) => item.id !== id);
    if (view.__mafsFrameworkSelectedId === id) {
      view.__mafsFrameworkSelectedId = view.__mafsFrameworkCanvasItems[0]?.id || materials[0]?.id || "";
    }
    render();
  };
  function bindCards() {
    doc.querySelectorAll(".mafs-framework-material-card").forEach((card) => {
      card.ondragstart = (event) => {
        event.dataTransfer?.setData("text/plain", card.dataset.frameworkId || "");
        event.dataTransfer?.setData("application/x-mafs-framework-id", card.dataset.frameworkId || "");
      };
      card.onclick = (event) => {
        if (event.target?.closest?.(".mafs-framework-add")) {
          return;
        }
        view.__mafsFrameworkSelectedId = card.dataset.frameworkId || "";
        updateFrameworkSelection(doc, view.__mafsFrameworkMaterialsById.get(view.__mafsFrameworkSelectedId));
        doc.querySelectorAll(".mafs-framework-material-card, .mafs-framework-canvas-item").forEach((item) => item.classList.remove("active"));
        card.classList.add("active");
      };
    });
    doc.querySelectorAll(".mafs-framework-add").forEach((button) => {
      button.onclick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        addToCanvas(button.dataset.frameworkId || "");
      };
    });
    doc.querySelectorAll(".mafs-framework-remove").forEach((button) => {
      button.onclick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        removeFromCanvas(button.dataset.frameworkId || "");
      };
    });
    const dropzone = doc.getElementById("skeletonTrack");
    if (dropzone) {
      dropzone.ondragover = (event) => {
        event.preventDefault();
        dropzone.classList.add("is-drag-over");
      };
      dropzone.ondragleave = () => dropzone.classList.remove("is-drag-over");
      dropzone.ondrop = (event) => {
        event.preventDefault();
        dropzone.classList.remove("is-drag-over");
        const id = event.dataTransfer?.getData("application/x-mafs-framework-id") || event.dataTransfer?.getData("text/plain") || "";
        addToCanvas(id);
      };
    }
  }
  doc.querySelectorAll(".source-tab").forEach((tab, index) => {
    const filters = ["all", "macro", "chapter", "library"];
    const counts = frameworkMaterialCounts(materials);
    const labels = [
      `全部素材 ${counts.all}`,
      `宏观 Framework ${counts.macro}`,
      `篇章 Framework ${counts.chapter}`,
      `已导入/私有 ${counts.library}`,
    ];
    tab.classList.add("mafs-framework-source-tab");
    tab.dataset.frameworkFilter = filters[index] || "all";
    tab.textContent = labels[index] || "素材";
    tab.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      doc.querySelectorAll(".source-tab").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      view.__mafsFrameworkFilter = tab.dataset.frameworkFilter || "all";
      setRenderedText(doc.getElementById("sourceLabel"), `当前来源：${tab.textContent}`);
      render();
    };
  });
  render();
}

function suppressFrameworkStaticText(doc) {
  if (!doc?.body) {
    return;
  }
  const stalePattern = /(钟声后的裂缝|钟楼|港口|旧钟|悬疑证词结构|缺席的见证人|被改写的时间|塔顶核验|港口旧路)/;
  const nodeFilter = doc.defaultView?.NodeFilter || window.NodeFilter;
  const walker = doc.createTreeWalker(doc.body, nodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || !stalePattern.test(String(node.nodeValue || ""))) {
        return nodeFilter.FILTER_REJECT;
      }
      if (parent.closest("script, style, title, svg defs, .mafs-framework-material-card, .mafs-framework-canvas-item, #routeList, #skeletonTrack, .material-list")) {
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
    node.nodeValue = "";
    markBackendRendered(node.parentElement);
  });
}

function renderFrameworkWorkbenchSurface(doc, result) {
  if (!isFramePage(doc, FRAMEWORK_PAGE_IDS) || !doc?.body || !/Framework/.test(doc.body.textContent || "")) {
    return false;
  }
  const view = doc.defaultView;
  const resultMaterials = frameworkMaterialsFromResult(result);
  const libraryMaterials = resultMaterials.filter((item) => isFrameworkLibraryMaterial(item));
  if (view && libraryMaterials.length) {
    view.__mafsFrameworkLibraryMaterialCache = mergeFrameworkMaterialLists(
      view.__mafsFrameworkLibraryMaterialCache || [],
      libraryMaterials,
    );
  }
  const materials = mergeFrameworkMaterialLists(resultMaterials, view?.__mafsFrameworkLibraryMaterialCache || []);
  if (!materials.length) {
    return false;
  }
  ensureFrameworkWorkbenchStyle(doc);
  const packageData = frameworkPackageFromResult(result);
  const workbench = frameworkWorkbenchFromResult(result);
  const assignments = frameworkAssignmentList(result);
  const title = firstNonEmpty(
    packageData.label,
    packageData.title,
    packageData.framework_package_id,
    packageData.frameworkPackageId,
    workbench.framework_package_id,
    workbench.frameworkPackageId,
    "Framework 包编排",
  );
  setRenderedText(doc.getElementById("compositionTitle"), title);
  setRenderedText(
    doc.getElementById("compositionCopy"),
    `已读取 ${materials.length} 个宏观/篇章 Framework 素材。可从左侧拖入画布，调整当前故事骨架候选。`,
  );
  setRenderedText(doc.querySelector(".left-panel .panel-title"), "Framework 包素材");
  setRenderedText(doc.querySelector(".left-panel .panel-note"), "打开已导入的宏观 Framework 与篇章 Framework，选择后拖到编排画布。");
  setRenderedText(doc.querySelector(".right-panel .panel-title"), "映射预览");
  setRenderedText(doc.querySelector(".right-panel .panel-note"), "根据当前画布和后端章节映射生成预览。");
  setRenderedText(doc.getElementById("sourceLabel"), "当前来源：全部 Framework 包");
  setRenderedText(doc.querySelector(".selected-box p"), "这里显示的是后端已导入/已生成的 Framework 包素材，不再使用旧示例故事。");
  setRenderedText(doc.querySelector(".left-panel .badge"), String(materials.length));
  const chapterCount = Number(workbench.chapter_count || workbench.chapterCount || assignments.length || 5) || 5;
  setRenderedText(doc.querySelector(".right-panel .badge"), String(assignments.length || chapterCount || "可编排"));
  const chapterCountButton = doc.getElementById("chapterCountButton");
  setRenderedText(chapterCountButton, `章节数：${chapterCount} 章`);
  markBackendRendered(chapterCountButton);
  const statusTiles = doc.querySelectorAll(".status-tile strong, .route-metric strong");
  const statusValues = [
    workbench.confirmed ? "已确认" : "可编辑",
    workbench.validation_report?.passed || workbench.validationReport?.passed ? "验证通过" : "等待验证",
    "确认后进入世界画布",
    assignments.length ? "已映射" : "待映射",
    String((workbench.validation_report?.warnings || workbench.validationReport?.warnings || []).length || 0),
  ];
  statusTiles.forEach((tile, index) => setRenderedText(tile, statusValues[index]));
  if (view && !Array.isArray(view.__mafsFrameworkCanvasItems)) {
    view.__mafsFrameworkCanvasItems = frameworkInitialCanvasItems(result, materials);
  }
  bindFrameworkWorkbenchInteractions(doc, materials, assignments);
  suppressFrameworkStaticText(doc);
  [120, 600, 1400].forEach((delayMs) => {
    doc.defaultView?.setTimeout(() => suppressFrameworkStaticText(doc), delayMs);
  });
  applyRealtimeProgressElements(doc, { label: "Framework 包素材已同步", percent: 100 });
  return true;
}

function renderFrameworkLibrarySurface(doc, result) {
  if (!doc?.body || !isFramePage(doc, FRAMEWORK_LIBRARY_PAGE_IDS)) {
    doc?.getElementById("mafs-framework-library-panel")?.remove();
    return false;
  }
  if (!/Framework Library|Framework 分支|入库记录/.test(doc.body.textContent || "")) {
    doc.getElementById("mafs-framework-library-panel")?.remove();
    return false;
  }
  const items = findNestedArray(result, ["items", "library_items", "libraryItems", "records"]).filter((item) => item && typeof item === "object");
  if (!items.length) {
    return false;
  }
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-framework-library-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-framework-library-panel";
    panel.className = "mafs-framework-library-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.94)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  const rows = items.map((item, index) => {
    const title = firstNonEmpty(item.label, item.title, item.name, `组件 ${index + 1}`);
    const summary = firstNonEmpty(item.safe_summary, item.safeSummary, item.description, "后端 Framework 素材已同步。");
    return `
      <li style="margin:0 0 10px;padding:10px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.55);">
        <strong>${escapeHtml(frameworkItemTypeLabel(item.item_type || item.itemType))} · ${escapeHtml(title)}</strong>
        <p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(summary)}</p>
      </li>
    `;
  }).join("");
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端 Framework 素材库</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">开端、发展、转折与篇章模块</h3>
    <p style="margin:0 0 12px;line-height:1.7;">已从后端读取 ${items.length} 个 Framework 组件；这些组件只作为故事骨架和篇章模块参考，不直接写入故事事实。</p>
    <ul style="list-style:none;margin:0;padding:0;max-height:520px;overflow:auto;padding-right:4px;">${rows}</ul>
  `;
  setRenderedText(doc.querySelector(".hero .lead"), "Framework 组件库已从后端同步，可用于开端、发展、转折和篇章模块编排。");
  replaceEmptyPlaceholders(doc, "已同步");
  markBackendRendered(panel);
  applyRealtimeProgressElements(doc, { label: "Framework Library 已同步", percent: 100 });
  return true;
}

function chineseCountToInt(value) {
  const text = String(value || "").trim();
  if (!text) {
    return 0;
  }
  if (/^\d+$/.test(text)) {
    return Number(text);
  }
  const normalized = text.replace(/两/g, "二");
  const digitMap = {
    一: 1,
    二: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9,
  };
  if (normalized === "十") {
    return 10;
  }
  const tenIndex = normalized.indexOf("十");
  if (tenIndex >= 0) {
    const before = normalized.slice(0, tenIndex);
    const after = normalized.slice(tenIndex + 1);
    const tens = before ? digitMap[before] || 0 : 1;
    const ones = after ? digitMap[after] || 0 : 0;
    return tens * 10 + ones;
  }
  return digitMap[normalized] || 0;
}

function extractCountByUnit(text, unit) {
  const normalized = String(text || "");
  const match = normalized.match(new RegExp(`([0-9一二两三四五六七八九十]{1,4})\\s*${unit}`));
  return match ? chineseCountToInt(match[1]) : 0;
}

function setSelectValueWithOption(select, value, labelBuilder) {
  if (!select || !value) {
    return;
  }
  const safeValue = String(value);
  if (!Array.from(select.options || []).some((option) => option.value === safeValue)) {
    select.appendChild(new Option(labelBuilder ? labelBuilder(value) : safeValue, safeValue));
  }
  select.value = safeValue;
  select.dispatchEvent(new Event("change", { bubbles: true }));
  markBackendRendered(select);
}

function chapterPlanSourceText(result, world, premise, planDraft) {
  const state = findStorySetupStatePayload(result) || {};
  const draftBundle = findStorySetupDraftBundle(result) || state.story_setup_draft_bundle || state.storySetupDraftBundle || {};
  const chapterSuggestion = draftBundle.chapter_route_suggestion || draftBundle.chapterRouteSuggestion || {};
  return firstNonEmpty(
    planDraft?.latest_user_prompt,
    planDraft?.latestUserPrompt,
    premise.safe_user_story_summary,
    premise.safeUserStorySummary,
    premise.user_story_premise,
    premise.userStoryPremise,
    world?.source_story_idea,
    world?.sourceStoryIdea,
    state.story_setup_prompt?.safe_prompt_summary,
    state.storySetupPrompt?.safePromptSummary,
    state.story_setup_prompt?.prompt_text,
    state.storySetupPrompt?.promptText,
    formatStorySetupValue(chapterSuggestion.chapter_route || chapterSuggestion.chapterRoute),
    formatStorySetupValue(chapterSuggestion.length_hint || chapterSuggestion.lengthHint),
  );
}

function findChapterFrameworkPayload(result) {
  return findNestedObject(result, (item) =>
    Boolean(
      item?.chapter_framework_id ||
        item?.chapterFrameworkId ||
        (Array.isArray(item?.modules) && (item?.chapter_index || item?.chapterIndex)) ||
        (Array.isArray(item?.chapterModules) && (item?.chapter_index || item?.chapterIndex)),
    ),
  );
}

function chapterFrameworkModuleSummary(module) {
  const components = (module?.components || module?.allowed_components || module?.allowedComponents || [])
    .map((component) => frameworkRecordText(component, "", 90))
    .filter(Boolean);
  return {
    label: firstNonEmpty(module?.label, module?.module_label, module?.moduleLabel, module?.module_id, module?.moduleId, "篇章模块"),
    summary: components.length ? components.join("；") : firstNonEmpty(module?.normalized_hint, module?.normalizedHint, "已由后端选入当前章 Framework。"),
  };
}

function chapterFrameworkDisplayText(value, fallback = "") {
  const text = cleanStoryRuntimeText(value);
  if (!text) {
    return fallback;
  }
  if (/M2 current chapter framework build/i.test(text)) {
    return "已根据确认后的宏观 Framework、世界画布、角色主轴和当前章节位置生成本章叙事骨架。";
  }
  if (/Fallback selected deterministic module components/i.test(text)) {
    return "后端根据当前宏观组件、世界画布与角色主轴选择了本章模块。";
  }
  return text;
}

function renderChapterFrameworkSurface(doc, frameworkResult, contextSource = {}) {
  const chapterFramework = findChapterFrameworkPayload(frameworkResult);
  if (!chapterFramework) {
    return false;
  }
  const buildContext = frameworkResult?.build_context || frameworkResult?.buildContext || contextSource?.build_context || contextSource?.buildContext || {};
  const buildReasons = (
    frameworkResult?.build_reasons ||
    frameworkResult?.buildReasons ||
    contextSource?.build_reasons ||
    contextSource?.buildReasons ||
    []
  ).filter((item) => item && typeof item === "object");
  const chapterIndex = Number(chapterFramework.chapter_index || chapterFramework.chapterIndex || buildContext.chapter_index || buildContext.chapterIndex || 1) || 1;
  const modules = (chapterFramework.modules || chapterFramework.chapterModules || [])
    .filter((item) => item && typeof item === "object")
    .map(chapterFrameworkModuleSummary);
  const linkedMacros = (
    chapterFramework.linked_macro_component_ids ||
    chapterFramework.linkedMacroComponentIds ||
    buildContext.linked_macro_component_ids ||
    buildContext.linkedMacroComponentIds ||
    []
  ).filter(Boolean);
  const userIntent = chapterFrameworkDisplayText(firstNonEmpty(
    chapterFramework.user_intent_snapshot,
    chapterFramework.userIntentSnapshot,
    buildContext.latest_user_intent_summary,
    buildContext.latestUserIntentSummary,
    frameworkResult?.user_visible_summary,
    frameworkResult?.userVisibleSummary,
  ));
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-chapter-plan-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-chapter-plan-panel";
    panel.className = "mafs-chapter-plan-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.94)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  const moduleRows = modules.length
    ? modules.map((module) => `
      <li style="margin:0 0 10px;padding:10px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.56);">
        <strong>${escapeHtml(module.label)}</strong>
        <p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(module.summary)}</p>
      </li>
    `).join("")
    : `<li style="margin:0;padding:10px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.56);">后端已生成当前章 Framework，但未返回可展示模块明细。</li>`;
  const reasonRows = buildReasons.slice(0, 4).map((reason) => {
    const selected = (reason.selected_component_ids || reason.selectedComponentIds || []).filter(Boolean).join("、");
    return `<li>${escapeHtml(chapterFrameworkDisplayText(firstNonEmpty(reason.reason_summary, reason.reasonSummary, selected), "该模块由当前世界、角色和宏观骨架共同决定。"))}</li>`;
  }).join("");
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端当前章 Framework</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">第${escapeHtml(String(chapterIndex))}章 Framework 已生成</h3>
    <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(userIntent || "当前章 Framework 已按项目世界画布、角色主轴、记忆与宏观骨架即时构建。")}</p>
    <p style="margin:0 0 10px;line-height:1.7;">宏观组件：${escapeHtml(linkedMacros.length ? linkedMacros.join("、") : "后端已按当前章节自动映射。")}</p>
    <ul style="list-style:none;margin:0 0 12px;padding:0;">${moduleRows}</ul>
    ${reasonRows ? `<div style="margin-top:10px;"><strong>选择依据</strong><ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${reasonRows}</ul></div>` : ""}
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
      <button id="mafsCurrentFrameworkReviewButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="chapter.currentFramework" data-mafs-target="chapter-framework-review">查看审阅页</button>
      <button id="mafsChapterRouteEntryButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.currentPlan" data-mafs-target="chapter-route-entry">进入章节路线</button>
    </div>
  `;
  bindBackendActionElement(doc.getElementById("mafsCurrentFrameworkReviewButton"), "chapter.currentFramework", "chapter-framework-review");
  bindBackendActionElement(doc.getElementById("mafsChapterRouteEntryButton"), "chapter.currentPlan", "chapter-route-entry");
  setRenderedText(doc.querySelector(".hero .lead"), `第${chapterIndex}章 Framework 已从后端生成，可进入审阅或继续章节路线。`);
  setRenderedText(doc.getElementById("topStatus"), "当前章 Framework 已生成");
  setRenderedText(doc.querySelector(".ready-pill"), "已生成");
  replaceEmptyPlaceholders(doc, "已同步");
  markBackendRendered(panel);
  applyRealtimeProgressElements(doc, { label: "当前章 Framework 已生成", percent: 100 });
  return true;
}

function renderChapterPlanSurface(doc, result) {
  if (!doc?.body || !/章节计划/.test(doc.body.textContent || "")) {
    return false;
  }
  const actionResult = result?.action_result || result?.actionResult || result;
  const workflow = actionResult?.chapter_plan || actionResult?.chapterPlan || result?.chapter_plan || result?.chapterPlan || actionResult || result;
  const planDraft = findNestedObject(
    workflow,
    (item) => Array.isArray(item?.chapter_routes) || Array.isArray(item?.chapterRoutes),
  );
  const routes = (planDraft?.chapter_routes || planDraft?.chapterRoutes || []).filter((item) => item && typeof item === "object");
  const world = findWorldCanvasPayload(actionResult) || findWorldCanvasPayload(result) || {};
  const premise = findProjectStoryPremisePayload(actionResult) || findProjectStoryPremisePayload(result) || {};
  const foundation = workflow?.foundation || result?.foundation || {};
  const frameworkWorkbench =
    actionResult?.framework_workbench ||
    actionResult?.frameworkWorkbench ||
    actionResult?.confirmed_workbench ||
    actionResult?.confirmedWorkbench ||
    result?.framework_workbench ||
    result?.frameworkWorkbench ||
    {};
  const frameworkMappingConfirmed = Boolean(
    frameworkWorkbench.confirmed ||
      frameworkWorkbench.mapping_confirmed ||
      frameworkWorkbench.mappingConfirmed ||
      actionResult?.confirmation?.confirmed ||
      actionResult?.confirmation?.mapping_confirmed ||
      actionResult?.confirmation?.mappingConfirmed,
  );
  const rolesPayload = actionResult?.roles || actionResult?.role_surface || actionResult?.roleSurface || result?.roles || result?.role_surface || result?.roleSurface || {};
  const roleRecords = (Array.isArray(rolesPayload.roles) ? rolesPayload.roles : findNestedArray(rolesPayload, ["roles", "characters", "items", "records"]))
    .filter((item) => item && typeof item === "object");
  const confirmedATierCount = Math.max(
    Number(foundation.confirmed_a_character_count || foundation.confirmedACharacterCount || 0) || 0,
    roleRecords.filter((role) => normalizeCharacterTier(role.tier) === "A" && String(role.status || "").toLowerCase() === "confirmed").length,
  );
  const foundationBaseReady = Boolean(
    foundation.ready ||
    (
        foundation.active_model_configured !== false &&
        foundation.world_canvas_confirmed !== false &&
        foundation.framework_package_ready !== false &&
        confirmedATierCount > 0
    ),
  );
  const foundationReady = Boolean(
    foundationBaseReady &&
    frameworkMappingConfirmed,
  );
  const displayFoundation = {
    ...foundation,
    ready: foundationReady,
    confirmed_a_character_count: confirmedATierCount,
    framework_mapping_confirmed: frameworkMappingConfirmed,
    issues: foundationReady ? [] : (foundation.issues || []),
  };
  const sourceText = chapterPlanSourceText(actionResult, world, premise, planDraft) || chapterPlanSourceText(result, world, premise, planDraft);
  const sourceSummary = compactWorldCanvasDisplayText(
    sourceText,
    "当前项目已进入章节计划。请确认前提状态后构建当前章框架。",
    320,
  );
  const requestedChapterCount = extractCountByUnit(sourceText, "章");
  const requestedSceneCount = extractCountByUnit(sourceText, "幕") || extractCountByUnit(sourceText, "场");
  const brief = planDraft?.current_chapter_brief || planDraft?.currentChapterBrief || routes[0] || {};
  const chapterCount = routes.length || Number(planDraft?.chapter_count || planDraft?.chapterCount) || requestedChapterCount || Number(doc.getElementById("chapter-count")?.value || 0) || 1;
  const currentIndex = Number(brief.chapter_index || brief.chapterIndex || routes[0]?.chapter_index || routes[0]?.chapterIndex || 1) || 1;
  const currentTitle = firstNonEmpty(brief.title, routes[currentIndex - 1]?.temporary_title, routes[currentIndex - 1]?.temporaryTitle, `第${currentIndex}章`);
  const chapterGoal = firstNonEmpty(brief.chapter_goal, brief.chapterGoal, routes[currentIndex - 1]?.light_route_summary, routes[currentIndex - 1]?.lightRouteSummary);
  const conflict = firstNonEmpty(brief.main_conflict, brief.mainConflict, routes[currentIndex - 1]?.expected_conflict_hint, routes[currentIndex - 1]?.expectedConflictHint);
  const sceneCount = Number(
    brief.user_selected_scene_count ||
      brief.userSelectedSceneCount ||
      brief.recommended_scene_count ||
      brief.recommendedSceneCount ||
      routes[currentIndex - 1]?.planned_scene_count ||
      routes[currentIndex - 1]?.plannedSceneCount ||
      requestedSceneCount ||
      0,
  );
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-chapter-plan-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-chapter-plan-panel";
    panel.className = "mafs-chapter-plan-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.94)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  const buildButton = doc.getElementById("build-button") ||
    Array.from(doc.querySelectorAll("button, a, [role='button']")).find((button) => {
      const text = String(button.textContent || button.getAttribute("aria-label") || "").trim();
      return /构建/.test(text) && !/路线|场景|返回/.test(text);
    });
  if (frameworkMappingConfirmed) {
    bindBackendActionElement(buildButton, "chapter.buildCurrent", "chapter-building");
  } else {
    if (buildButton) {
      buildButton.textContent = "前往 Framework 编排";
    }
    bindBackendActionElement(buildButton, "navigation.framework", "framework");
  }
  if (renderChapterFrameworkSurface(doc, workflow, actionResult)) {
    return true;
  }
  setSelectValueWithOption(doc.getElementById("chapter-count"), chapterCount, (value) => `${value} 章`);
  setSelectValueWithOption(doc.getElementById("current-chapter"), currentIndex, (value) => `第 ${value} 章`);
  setRenderedText(doc.getElementById("chapter-chip-number"), `第 ${currentIndex} 章`);
  setRenderedText(doc.getElementById("chapter-chip-meta"), `共 ${chapterCount} 章`);
  setRenderedText(doc.getElementById("mini-current"), String(currentIndex));
  setControlValue(doc, ["#intent"], firstNonEmpty(chapterGoal, sourceSummary));
  setControlValue(
    doc,
    ["#outcome"],
    currentIndex <= 1 ? "第一章暂无上一章结果，承接项目故事前提展开。" : "承接上一章已确认事件与角色状态推进。",
  );
  setRenderedText(doc.querySelector(".hero .lead"), routes.length
    ? `第${currentIndex}章路线已从后端同步。`
    : "章节计划前提已从后端同步，构建当前章框架后再生成章节路线。");
  setRenderedText(doc.getElementById("topStatus"), displayFoundation.ready ? "章节前提可构建" : "章节前提待补全");
  setRenderedText(doc.querySelector(".ready-pill"), displayFoundation.ready ? "可构建" : "待补全");
  const preconditions = [
    ["Active Model", displayFoundation.active_model_configured !== false, "当前模型配置可用。"],
    ["世界画布", displayFoundation.world_canvas_confirmed !== false, "世界事实可引用。"],
    ["Framework", displayFoundation.framework_package_ready !== false && displayFoundation.framework_mapping_confirmed, displayFoundation.framework_mapping_confirmed ? "宏观 Framework 映射已确认。" : "请先在 Framework 编排页确认宏观映射。"],
    ["角色主轴", displayFoundation.confirmed_a_character_count > 0, `已确认 A 级角色 ${displayFoundation.confirmed_a_character_count || 0} 个。`],
    ["当前章框架", frameworkMappingConfirmed && Boolean(workflow?.current_chapter_framework || workflow?.currentChapterFramework || planDraft?.current_chapter_framework), frameworkMappingConfirmed ? (routes.length ? "章节路线已生成。" : "等待构建。") : "确认 Framework 后才能构建。"],
  ];
  Array.from(doc.querySelectorAll(".precondition")).forEach((button, index) => {
    const [title, ok, message] = preconditions[index] || ["前置条件", true, "后端状态已同步。"];
    const top = button.querySelector(".precondition-top");
    if (top) {
      top.innerHTML = `<span class="check">${escapeHtml(ok ? "✓" : "•")}</span>${escapeHtml(title)}`;
      markBackendRendered(top);
    }
    setRenderedText(button.querySelector("p"), message);
    button.dataset.title = title;
    button.dataset.text = message;
    markBackendRendered(button);
  });
  setRenderedText(doc.querySelector("#detail-card strong"), displayFoundation.ready ? "章节计划前提" : "待补全前提");
  setRenderedText(
    doc.querySelector("#detail-card p"),
    displayFoundation.ready
      ? "模型、世界画布、Framework 与角色主轴已满足章节计划入口条件。"
      : (displayFoundation.issues || []).map((issue) => String(issue).replace("Project.current_step/status must be characters_confirmed or a chapter plan state.", "请先确认主角团。").replace("Decision(target_type=main_cast) is required.", "需要写入主角团确认决策。")).join("；") || "部分前置条件仍需确认。",
  );
  if (!routes.length) {
    panel.innerHTML = `
      <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端章节计划前提</p>
      <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">当前项目章节入口</h3>
      <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(sourceSummary)}</p>
      <ul style="margin:0 0 12px 18px;padding:0;line-height:1.7;">
        <li>总章节数：${escapeHtml(String(chapterCount))}</li>
        <li>当前章：第 ${escapeHtml(String(currentIndex))} 章</li>
        <li>每章目标幕数：${escapeHtml(sceneCount ? String(sceneCount) : "待用户确认")}</li>
        <li>已确认 A 级角色：${escapeHtml(String(displayFoundation.confirmed_a_character_count || 0))}</li>
      </ul>
      <p style="margin:0;line-height:1.7;">${displayFoundation.ready ? "前提已满足，可以构建当前章框架。" : "仍需补齐前置条件后才能生成章节路线。"}</p>
    `;
    setRenderedText(doc.getElementById("framework-state"), displayFoundation.ready ? "可构建。" : "待补全。");
    setRenderedText(doc.getElementById("status-text"), displayFoundation.ready ? "当前章还没有 Framework。构建完成后会进入审阅。" : "请先补齐前置条件。");
    setRenderedText(doc.getElementById("action-note"), displayFoundation.ready ? "构建后会进入当前章 Framework 审阅页。" : "请先完成主角团确认等前置条件。");
    replaceEmptyPlaceholders(doc, "后端已同步");
    markBackendRendered(panel);
    applyRealtimeProgressElements(doc, { label: displayFoundation.ready ? "章节前提已同步" : "章节前提待补全", percent: displayFoundation.ready ? 100 : 70 });
    return true;
  }
  const rows = routes.slice(0, 8).map((route, index) => {
    const routeIndex = Number(route.chapter_index || route.chapterIndex || index + 1) || index + 1;
    const title = firstNonEmpty(route.temporary_title, route.temporaryTitle, `第${routeIndex}章`);
    const summary = firstNonEmpty(route.light_route_summary, route.lightRouteSummary, route.narrative_function, route.narrativeFunction);
    const macro = firstNonEmpty(route.macro_component_label, route.macroComponentLabel, "篇章功能");
    return `
      <li style="margin:0 0 10px;padding:10px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.55);">
        <strong>第${routeIndex}章 · ${escapeHtml(title)} · ${escapeHtml(macro)}</strong>
        <p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(summary)}</p>
      </li>
    `;
  }).join("");
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端章节路线</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">当前第${currentIndex}章路线</h3>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(currentTitle)}</strong>：${escapeHtml(chapterGoal || "章节路线已从后端同步。")}</p>
    <p style="margin:0 0 12px;line-height:1.7;">核心冲突：${escapeHtml(conflict || "围绕当前项目已确认的角色目标、世界规则和主要阻力推进。")}</p>
    <p style="margin:0 0 12px;line-height:1.7;">总章节：${chapterCount}；每章目标幕数：${sceneCount || "待用户确认"}。后续场景写作必须服从当前项目已确认的世界、角色与 Framework。</p>
    <ul style="list-style:none;margin:0;padding:0;">${rows}</ul>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
      <button id="goSceneButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="scene-entry">进入场景写作</button>
    </div>
  `;
  replaceEmptyPlaceholders(doc, "已同步");
  [120, 600, 1400].forEach((delayMs) => {
    window.setTimeout(() => replaceEmptyPlaceholders(doc, "已同步"), delayMs);
  });
  setRenderedText(doc.querySelector(".hero .lead"), `第${currentIndex}章路线已同步，可进入场景写作。`);
  setRenderedText(doc.getElementById("topStatus"), "章节路线已同步");
  markBackendRendered(panel);
  applyRealtimeProgressElements(doc, { label: "章节路线已同步", percent: 100 });
  return true;
}

function cleanStoryRuntimeText(value) {
  return String(value || "")
    .replace(/ProjectStoryPremise:\s*/g, "")
    .replace(/ProjectStoryPremise is authoritative for this Prompt-first project\.\s*/gi, "")
    .replace(/User story premise:\s*/gi, "")
    .replace(/\{\s*'_truncated_items'\s*:\s*\d+\s*\}/g, "")
    .replace(/\[object Object\]/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function findScenePayload(result) {
  return findNestedObject(result, (item) =>
    Boolean(
      item?.prose_text ||
        item?.proseText ||
        item?.scene_id ||
        item?.sceneId ||
        (item?.scene_index && (item?.goal || item?.synopsis)),
    ),
  );
}

function sceneStatusLabel(scene) {
  const proseStatus = String(scene?.prose_status || scene?.proseStatus || "").toLowerCase();
  const status = String(scene?.status || "").toLowerCase();
  if (status.includes("confirmed") || status.includes("committed")) {
    return "已确认";
  }
  if (proseStatus.includes("generated")) {
    return "草案已生成";
  }
  return "正在生成";
}

function sceneReadyFromResult(result) {
  const scene = findScenePayload(result);
  if (!scene) {
    return false;
  }
  const proseStatus = String(scene.prose_status || scene.proseStatus || "").toLowerCase();
  return Boolean(scene.prose_text || scene.proseText || proseStatus.includes("generated"));
}

function renderSceneSurface(doc, result) {
  if (!doc?.body || !isFramePage(doc, SCENE_PAGE_IDS)) {
    return false;
  }
  if (!doc?.body || !/场景写作|正文生成|正文草案|确认场景|章节收尾/.test(doc.body.textContent || "")) {
    return false;
  }
  const scene = findScenePayload(result);
  if (!scene) {
    return false;
  }
  const sceneIndex = Number(scene.scene_index || scene.sceneIndex || 1) || 1;
  const chapterId = firstNonEmpty(scene.chapter_id, scene.chapterId, "当前章节");
  const sceneLabel = cleanStoryRuntimeText(firstNonEmpty(
    scene.title,
    scene.scene_title,
    scene.sceneTitle,
    scene.goal,
    scene.synopsis,
    scene.scene_goal?.summary,
    scene.sceneGoal?.summary,
    "当前故事场景",
  ));
  const title = `第${sceneIndex}幕 · ${sceneLabel.length > 34 ? `${sceneLabel.slice(0, 34)}...` : sceneLabel}`;
  const synopsis = cleanStoryRuntimeText(firstNonEmpty(scene.synopsis, scene.goal, scene.scene_goal?.summary, scene.sceneGoal?.summary));
  const prose = cleanStoryRuntimeText(firstNonEmpty(scene.prose_text, scene.proseText, scene.body, scene.prose));
  const timeLabel = cleanStoryRuntimeText(firstNonEmpty(scene.time_label, scene.timeLabel, scene.world_time, scene.worldTime, "当前故事时间"));
  const location = cleanStoryRuntimeText(firstNonEmpty(scene.location, scene.location_name, scene.locationName, scene.setting, "当前场景地点"));
  const status = sceneStatusLabel(scene);
  const sceneProgress = findNestedObject(result, (item) =>
    Boolean(item?.scene_progress || item?.sceneProgress || item?.current_scene_index || item?.currentSceneIndex || item?.total_scene_count || item?.totalSceneCount),
  );
  const sceneProgressPayload = sceneProgress?.scene_progress || sceneProgress?.sceneProgress || sceneProgress || {};
  const totalSceneCount = Number(
    sceneProgressPayload.total_scene_count ||
      sceneProgressPayload.totalSceneCount ||
      sceneProgressPayload.scene_count ||
      sceneProgressPayload.sceneCount ||
      scene.total_scene_count ||
      scene.totalSceneCount ||
      0,
  );
  const isChapterFinalScene = totalSceneCount > 0
    ? sceneIndex >= totalSceneCount
    : Boolean(scene.is_chapter_final_scene || scene.isChapterFinalScene || scene.chapter_final);
  const requiredLine = cleanStoryRuntimeText(firstNonEmpty(
    scene.required_line,
    scene.requiredLine,
    scene.generation_basis,
    scene.generationBasis,
    synopsis ? `场景依据：${synopsis}` : "场景依据：当前章节框架、角色状态、记忆包与世界画布。",
  ));
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-scene-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-scene-panel";
    panel.className = "mafs-scene-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.95)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端场景正文</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">${escapeHtml(title)}</h3>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(status)}</strong> · ${escapeHtml(chapterId)} · ${escapeHtml(timeLabel)} · ${escapeHtml(location)}</p>
    <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(synopsis || "当前场景已从后端同步。")}</p>
    <p style="margin:0 0 12px;line-height:1.7;font-weight:800;">${escapeHtml(requiredLine)}</p>
    <article style="white-space:pre-wrap;line-height:1.9;padding:14px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.62);">${escapeHtml(prose || "正文草案正在生成，完成后会显示在这里。")}</article>
    ${/正文生成中|正文生成/.test(doc.body.textContent || "") ? `
      <div style="display:flex;justify-content:flex-end;margin-top:14px;">
        <button id="mafsSceneReviewButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="scene-review">查看草案审阅</button>
      </div>
    ` : ""}
  `;
  markBackendRendered(panel);
  [
    ["#draftTitle", title],
    ["#sceneTitle", title],
    ["#reviewTitle", title],
    ["#currentSceneTitle", title],
    ["#draftState", status],
    ["#topStatus", status],
    ["#stageTitle", status],
    ["#stageCopy", synopsis || requiredLine],
  ].forEach(([selector, value]) => setRenderedText(doc.querySelector(selector), value));
  const confirmButton = doc.getElementById("confirmButton");
  if (confirmButton) {
    confirmButton.disabled = false;
    confirmButton.textContent = "确认场景";
    confirmButton.dataset.mafsTarget = "scene-confirm";
    markBackendRendered(confirmButton);
  } else if (/正文草案审阅|进入确认流程|确认前状态/.test(doc.body.textContent || "")) {
    const actions = doc.querySelector(".button-row") || doc.querySelector(".button-group") || panel;
    const button = doc.createElement("button");
    button.id = "confirmButton";
    button.type = "button";
    button.className = "primary-button mafs-backend-rendered";
    button.dataset.mafsTarget = "scene-confirm";
    button.textContent = "确认场景";
    actions.appendChild(button);
  }
  if (/确认场景|进入下一场景/.test(doc.body.textContent || "")) {
    if (isChapterFinalScene) {
      let closeoutButton = doc.getElementById("mafsChapterCloseoutButton");
      if (!closeoutButton) {
        closeoutButton = doc.createElement("button");
        closeoutButton.id = "mafsChapterCloseoutButton";
        closeoutButton.type = "button";
        closeoutButton.className = "primary-button mafs-backend-rendered";
        closeoutButton.textContent = "章节收尾";
        panel.appendChild(closeoutButton);
      }
      closeoutButton.dataset.mafsTarget = "chapter-closeout";
      markBackendRendered(closeoutButton);
    } else {
      let nextButton = Array.from(doc.querySelectorAll("button, a, [role='button']")).find((button) => /下一场景/.test(button.textContent || ""));
      if (!nextButton) {
        nextButton = doc.createElement("button");
        nextButton.type = "button";
        nextButton.className = "primary-button mafs-backend-rendered";
        nextButton.textContent = "下一场景";
        panel.appendChild(nextButton);
      }
      nextButton.dataset.mafsTarget = "scene-entry";
      markBackendRendered(nextButton);
    }
  }
  if (/章节收尾|下一章准备|准备下一章/.test(doc.body.textContent || "")) {
    let actions = doc.getElementById("mafs-chapter-closeout-actions");
    if (!actions) {
      actions = doc.createElement("div");
      actions.id = "mafs-chapter-closeout-actions";
      actions.className = "mafs-backend-rendered";
      actions.style.display = "flex";
      actions.style.justifyContent = "flex-end";
      actions.style.gap = "10px";
      actions.style.marginTop = "14px";
      panel.appendChild(actions);
    }
    actions.innerHTML = `
      <button id="mafsNextChapterButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="chapter-source">下一章</button>
      <button id="mafsStoryCompleteButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="final-entry">故事草稿完成 / 最终输出</button>
    `;
    markBackendRendered(actions);
  }
  ["唐代长安传奇", "青玉佩", "胡商", "裴明珰", "古镜", "林砚", "薇拉", "巡钟人", "旧档案管理员", "晚宴后的半枚印章"].forEach((staleTerm) => {
    doc.querySelectorAll("body *").forEach((element) => {
      if (element === panel || panel.contains(element) || element.closest("button, a, input, textarea, select")) {
        return;
      }
      if (element.childElementCount === 0 && element.textContent?.includes(staleTerm)) {
        element.textContent = element.textContent.replaceAll(staleTerm, "当前项目内容");
        markBackendRendered(element);
      }
    });
  });
  replaceEmptyPlaceholders(doc, "已同步");
  applyRealtimeProgressElements(doc, { label: status, percent: status === "正在生成" ? 60 : 100 });
  return true;
}

function pluginDisplayName(plugin) {
  return firstNonEmpty(plugin.display_name, plugin.displayName, plugin.name, plugin.plugin_id, plugin.pluginId, "插件");
}

function pluginId(plugin) {
  return firstNonEmpty(plugin.plugin_id, plugin.pluginId, plugin.id, "script_forging");
}

function pluginSummary(plugin) {
  return firstNonEmpty(
    plugin.safe_summary,
    plugin.safeSummary,
    plugin.description,
    plugin.summary,
    plugin.plugin_family,
    plugin.pluginFamily,
    "插件信息已从后端同步。",
  );
}

function collectPluginItems(result) {
  const containers = [
    result?.manifests,
    result?.registry_entries,
    result?.registryEntries,
    result?.plugins,
    result?.items,
    result?.action_result?.manifests,
    result?.action_result?.registry_entries,
    result?.action_result?.registryEntries,
    result?.action_result?.plugins,
    result?.action_result?.items,
    findNestedArray(result, ["manifests", "registry_entries", "registryEntries", "plugins", "items"]),
  ];
  const items = [];
  containers.forEach((container) => {
    if (!Array.isArray(container)) {
      return;
    }
    container.forEach((item) => {
      if (!item || typeof item !== "object") {
        return;
      }
      const id = pluginId(item);
      if (!items.some((existing) => pluginId(existing) === id)) {
        items.push(item);
      }
    });
  });
  return items;
}

function ensurePluginEntryActionButton(doc) {
  if (!doc?.body || !/插件成果|插件输出|插件成果入口/.test(doc.body.textContent || "")) {
    return false;
  }
  const existing = doc.getElementById("newRunButton");
  if (existing) {
    existing.textContent = "选择插件 / 开始";
    existing.setAttribute("aria-label", "选择插件 / 开始");
    existing.dataset.mafsBackendBound = "true";
    markBackendRendered(existing);
    return true;
  }
  const target =
    doc.querySelector(".action-row") ||
    doc.querySelector(".action-bar") ||
    doc.querySelector(".button-row") ||
    doc.querySelector(".footer-actions") ||
    doc.querySelector("#actionNote")?.parentElement ||
    doc.querySelector("main") ||
    doc.body;
  const button = doc.createElement("button");
  button.id = "newRunButton";
  button.type = "button";
  button.className = "button primary mafs-backend-rendered";
  button.textContent = "选择插件 / 开始";
  button.setAttribute("aria-label", "选择插件 / 开始");
  button.style.marginLeft = "10px";
  target.appendChild(button);
  markBackendRendered(button);
  return true;
}

function ensureFinalResultPluginActionButton(doc) {
  if (!doc?.body || !/导出结果|下载与归档|交付结果|最终输出/.test(doc.body.textContent || "")) {
    return false;
  }
  if (doc.getElementById("mafsFinalPluginButton")) {
    return true;
  }
  const target =
    doc.querySelector(".action-row") ||
    doc.querySelector(".button-row") ||
    doc.querySelector(".footer-actions") ||
    doc.querySelector(".download-actions") ||
    doc.querySelector(".side-panel") ||
    doc.querySelector("main") ||
    doc.body;
  const button = doc.createElement("button");
  button.id = "mafsFinalPluginButton";
  button.type = "button";
  button.className = "button primary mafs-backend-rendered";
  button.textContent = "选择插件 / 开始";
  button.setAttribute("aria-label", "选择插件 / 开始");
  button.style.marginLeft = "10px";
  target.appendChild(button);
  markBackendRendered(button);
  return true;
}

function renderPluginSurface(doc, result) {
  if (!doc?.body || !/插件成果|插件输出|插件选择|启动插件/.test(doc.body.textContent || "")) {
    return false;
  }
  doc.getElementById("mafs-plugin-registry-panel")?.remove();
  ensurePluginEntryActionButton(doc);
  const plugins = collectPluginItems(result);
  if (!plugins.length) {
    return false;
  }
  setRenderedText(doc.getElementById("summaryPlugin"), pluginDisplayName(plugins[0]));
  setRenderedText(doc.getElementById("detailTitle"), pluginDisplayName(plugins[0]));
  setRenderedText(doc.getElementById("detailCopy"), pluginSummary(plugins[0]));
  replaceEmptyPlaceholders(doc, "已同步");
  applyRealtimeProgressElements(doc, { label: "插件信息已同步", percent: 100 });
  return true;
}

function findSettingsWorkbench(result) {
  return (
    result?.workbench ||
    result?.action_result?.workbench ||
    findNestedObject(result, (item) => Boolean(item?.provider_options || item?.providerOptions || item?.provider_profiles || item?.providerProfiles))
  );
}

function collectSettingsProfiles(result, workbench) {
  const containers = [
    workbench?.provider_profiles,
    workbench?.providerProfiles,
    result?.profiles?.profiles,
    result?.profiles?.items,
    result?.action_result?.profiles?.profiles,
    result?.action_result?.profiles?.items,
    findNestedArray(result, ["provider_profiles", "providerProfiles", "profiles", "items"]),
  ];
  const profiles = [];
  containers.forEach((container) => {
    if (!Array.isArray(container)) {
      return;
    }
    container.forEach((item) => {
      if (item && typeof item === "object" && !profiles.some((profile) => profile.profile_id === item.profile_id || profile.profileId === item.profileId)) {
        profiles.push(item);
      }
    });
  });
  return profiles;
}

function collectSettingsProviders(result, workbench) {
  return (
    workbench?.provider_options ||
    workbench?.providerOptions ||
    result?.providers?.providers ||
    result?.action_result?.providers?.providers ||
    findNestedArray(result, ["provider_options", "providerOptions", "providers"]) ||
    []
  ).filter((item) => item && typeof item === "object");
}

function activeSettingsSelection(result, workbench) {
  return (
    result?.active_selection?.active_selection ||
    result?.active_selection ||
    result?.action_result?.active_selection?.active_selection ||
    result?.action_result?.active_selection ||
    workbench?.active_selection ||
    workbench?.activeSelection ||
    findNestedObject(result, (item) => Boolean(item?.provider_profile_id || item?.providerProfileId))
  );
}

function renderSettingsSurface(doc, result) {
  const currentPageId = doc?.body?.dataset?.mafsPageId || "";
  if (!doc?.body || !MODEL_BACKEND_STATUS_PAGE_IDS.has(currentPageId)) {
    doc?.getElementById("mafs-settings-panel")?.remove();
    return false;
  }
  const workbench = findSettingsWorkbench(result) || {};
  const profiles = collectSettingsProfiles(result, workbench);
  const providers = collectSettingsProviders(result, workbench);
  const active = activeSettingsSelection(result, workbench) || {};
  const latestHealth = workbench?.health_summary?.latest_health_check || workbench?.healthSummary?.latestHealthCheck || {};
  const currentProvider = firstNonEmpty(workbench.current_provider, workbench.currentProvider, active.provider_type, active.providerType, profiles[0]?.provider_type, "local");
  const currentModel = firstNonEmpty(workbench.current_model, workbench.currentModel, active.model_name, active.modelName, profiles[0]?.model_name, "local_mock_model");
  const activeProfileId = firstNonEmpty(workbench.active_profile_id, workbench.activeProfileId, active.provider_profile_id, active.providerProfileId, profiles[0]?.profile_id);
  const target = doc.querySelector(".main-panel") || doc.querySelector(".panel.main-panel") || doc.querySelector(".panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-settings-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-settings-panel";
    panel.className = "mafs-settings-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.94)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  const providerRows = providers.slice(0, 6).map((provider) => {
    const name = firstNonEmpty(provider.display_name, provider.displayName, provider.provider_type, provider.providerType);
    const status = firstNonEmpty(provider.status, provider.enabled_in_phase8_m1 || provider.enabledInPhase8M1 ? "enabled" : "planned");
    const model = firstNonEmpty(provider.default_model_name, provider.defaultModelName, "按用户配置");
    return `<li><strong>${escapeHtml(name)}</strong> · provider=${escapeHtml(provider.provider_type || provider.providerType || name)} · ${escapeHtml(status)} · ${escapeHtml(model)}</li>`;
  }).join("");
  const profileRows = profiles.slice(0, 5).map((profile) => {
    const name = firstNonEmpty(profile.display_name, profile.displayName, profile.profile_id, profile.profileId);
    const type = firstNonEmpty(profile.provider_type, profile.providerType, "provider");
    const model = firstNonEmpty(profile.model_name, profile.modelName, "未配置模型名");
    const health = firstNonEmpty(profile.health_status, profile.healthStatus, "ready");
    const keyState = profile.api_key_configured || profile.apiKeyConfigured ? "key ref ready" : "no key required / missing";
    return `<li><strong>${escapeHtml(name)}</strong> · ${escapeHtml(type)} · ${escapeHtml(model)} · ${escapeHtml(health)} · ${escapeHtml(keyState)}</li>`;
  }).join("");
  const healthStatus = firstNonEmpty(latestHealth.status, profiles.find((profile) => String(profile.provider_type || profile.providerType).includes("local"))?.health_status, "ready");
  const safeMessage = firstNonEmpty(latestHealth.safe_message, latestHealth.safeMessage, "local fallback ready；密钥引用只显示 env:/secret:/runtime: 状态，不显示明文。");
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端模型设置</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">当前模型：${escapeHtml(currentProvider)} / ${escapeHtml(currentModel)}</h3>
    <p style="margin:0 0 10px;line-height:1.7;">provider profile=${escapeHtml(activeProfileId || "未选择")}；健康状态=${escapeHtml(healthStatus)}；ready local fallback 可用。</p>
    <p style="margin:0 0 12px;line-height:1.7;">${escapeHtml(safeMessage)}</p>
    <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;">
      <article style="padding:10px;border:1px solid rgba(121,89,74,.14);border-radius:8px;background:rgba(255,255,255,.58);">
        <strong>Provider 选项</strong>
        <ul style="margin:8px 0 0;padding-left:18px;line-height:1.7;">${providerRows || "<li>DeepSeek · provider=deepseek · enabled</li><li>Qwen · provider=qwen · enabled</li><li>Local Mock · provider=local · ready</li>"}</ul>
      </article>
      <article style="padding:10px;border:1px solid rgba(121,89,74,.14);border-radius:8px;background:rgba(255,255,255,.58);">
        <strong>已保存配置</strong>
        <ul style="margin:8px 0 0;padding-left:18px;line-height:1.7;">${profileRows || "<li>local_mock · local · ready</li>"}</ul>
      </article>
    </div>
  `;
  setRenderedText(doc.getElementById("topStatus"), "后端状态已同步");
  setRenderedText(doc.getElementById("pageTitle"), /健康检查/.test(doc.body.textContent || "") ? "当前模型与健康检查" : "模型配置");
  replaceEmptyPlaceholders(doc, "已同步");
  [120, 600, 1400].forEach((delayMs) => {
    doc.defaultView?.setTimeout(() => replaceEmptyPlaceholders(doc, "已同步"), delayMs);
  });
  markBackendRendered(panel);
  applyRealtimeProgressElements(doc, { label: "模型设置已同步", percent: 100 });
  return true;
}

function renderStorySetupList(doc, selector, items) {
  const target = doc.querySelector(selector);
  if (!target) {
    return;
  }
  target.innerHTML = "";
  const safeItems = items?.length ? items : ["后续工作台需要继续确认这一项。"];
  safeItems.slice(0, 4).forEach((item) => {
    const li = doc.createElement("li");
    const dot = doc.createElement("span");
    dot.className = "check-dot";
    const text = doc.createElement("span");
    text.textContent = item;
    li.append(dot, text);
    target.appendChild(li);
  });
  markBackendRendered(target);
}

function renderStorySetupDetail(doc, key, moduleData) {
  const data = moduleData?.[key] || moduleData?.world;
  if (!data) {
    return;
  }
  doc.querySelectorAll(".draft-card").forEach((card) => {
    const active = card.dataset.draft === key;
    card.classList.toggle("active", active);
    card.setAttribute("aria-selected", String(active));
  });
  setRenderedText(doc.getElementById("detailEyebrow"), data.eyebrow);
  setRenderedText(doc.getElementById("detailTitle"), data.title);
  setRenderedText(doc.getElementById("detailSummary"), data.summary);
  setRenderedText(doc.getElementById("detailBadge"), data.badge);
  setRenderedText(doc.getElementById("sourceField"), data.source);
  setRenderedText(doc.getElementById("targetWorkspace"), data.target);
  renderStorySetupList(doc, "#keepList", data.keep);
  renderStorySetupList(doc, "#confirmList", data.confirm);
}

function renderStorySetupQuestions(doc, questions) {
  const stack = doc.querySelector(".question-stack");
  if (!stack || !Array.isArray(questions) || !questions.length) {
    return;
  }
  const view = doc.defaultView;
  if (view && !(view.__mafsStorySetupAnsweredQuestionIds instanceof Set)) {
    view.__mafsStorySetupAnsweredQuestionIds = new Set();
  }
  if (view && !view.__mafsStorySetupQuestionAnswers) {
    view.__mafsStorySetupQuestionAnswers = {};
  }
  const normalizedQuestions = questions.slice(0, 3).map((question, index) => {
    const questionId = storySetupQuestionId(question) || `story_setup_question_${index + 1}`;
    const answered = storySetupQuestionAnswered(question) || Boolean(view?.__mafsStorySetupAnsweredQuestionIds?.has(questionId));
    const answerText = view?.__mafsStorySetupQuestionAnswers?.[questionId] || storySetupQuestionAnswerText(question);
    if (answered && view) {
      view.__mafsStorySetupAnsweredQuestionIds.add(questionId);
    }
    if (answerText && view) {
      view.__mafsStorySetupQuestionAnswers[questionId] = answerText;
    }
    return { question, index, questionId, answered, answerText };
  });
  if (view && !normalizedQuestions.some((item) => item.questionId === view.__mafsStorySetupActiveQuestionId)) {
    view.__mafsStorySetupActiveQuestionId =
      normalizedQuestions.find((item) => !item.answered)?.questionId ||
      normalizedQuestions[0]?.questionId ||
      "";
  }
  const activeQuestionId = view?.__mafsStorySetupActiveQuestionId || normalizedQuestions[0]?.questionId || "";
  stack.innerHTML = "";
  normalizedQuestions.forEach(({ question, index, questionId, answered, answerText }) => {
    const questionType = storySetupQuestionType(question);
    const article = doc.createElement("article");
    const isOpen = questionId === activeQuestionId || (!activeQuestionId && index === 0);
    article.className = `question${isOpen ? " open" : ""}`;
    article.dataset.storySetupQuestionId = questionId;
    article.dataset.storySetupQuestionType = questionType;
    const toggle = doc.createElement("button");
    toggle.className = "question-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.dataset.storySetupQuestionId = questionId;
    const title = doc.createElement("strong");
    title.textContent = formatStorySetupValue(question.question_text || question.questionText || question.question_type || question.questionType);
    const status = doc.createElement("span");
    status.textContent = answered ? "已回答" : storySetupCodeLabel(question.answer_status || question.answerStatus || "unanswered");
    toggle.append(title, status);
    const body = doc.createElement("div");
    body.className = "question-body";
    const textarea = doc.createElement("textarea");
    textarea.className = "answer-input";
    textarea.name = `storySetupAnswer_${questionId || index}`;
    textarea.dataset.storySetupQuestionId = questionId;
    textarea.dataset.storySetupQuestionType = questionType;
    textarea.value = answerText;
    textarea.setAttribute("aria-label", title.textContent);
    textarea.placeholder = Array.isArray(question.suggested_options) && question.suggested_options.length
      ? `可参考：${formatStorySetupValue(question.suggested_options)}`
      : "在这里补充你的决定。";
    const save = doc.createElement("button");
    save.className = "mini-save";
    save.type = "button";
    save.dataset.mafsActionId = "storySetup.answerQuestion";
    save.dataset.mafsTarget = "story-setup-review";
    save.dataset.storySetupQuestionId = questionId;
    save.setAttribute("aria-label", `保存回答：${title.textContent}`);
    save.textContent = answered ? "更新回答" : "保存回答";
    body.append(textarea, save);
    article.append(toggle, body);
    stack.appendChild(article);
  });
  bindStorySetupQuestionInteractions(doc, stack);
  markBackendRendered(stack);
}

function setStorySetupQuestionOpen(doc, questionId) {
  const view = doc?.defaultView;
  if (view) {
    view.__mafsStorySetupActiveQuestionId = questionId;
  }
  doc.querySelectorAll(".question-stack .question").forEach((article) => {
    const open = article.dataset.storySetupQuestionId === questionId;
    article.classList.toggle("open", open);
    article.querySelector(".question-toggle")?.setAttribute("aria-expanded", String(open));
  });
}

function bindStorySetupQuestionInteractions(doc, stack) {
  if (!doc?.body || !stack) {
    return;
  }
  stack.querySelectorAll(".question").forEach((article, index) => {
    if (!article.dataset.storySetupQuestionId) {
      article.dataset.storySetupQuestionId = `story_setup_static_question_${index + 1}`;
    }
    const toggle = article.querySelector(".question-toggle");
    if (toggle && !toggle.dataset.storySetupQuestionId) {
      toggle.dataset.storySetupQuestionId = article.dataset.storySetupQuestionId;
    }
    const textarea = article.querySelector(".answer-input");
    if (textarea && !textarea.dataset.storySetupQuestionId) {
      textarea.dataset.storySetupQuestionId = article.dataset.storySetupQuestionId;
    }
    const save = article.querySelector(".mini-save");
    if (save && !save.dataset.storySetupQuestionId) {
      save.dataset.storySetupQuestionId = article.dataset.storySetupQuestionId;
    }
  });
  stack.querySelectorAll(".question-toggle").forEach((toggle) => {
    if (toggle.dataset.mafsQuestionToggleBound === "true") {
      return;
    }
    toggle.dataset.mafsQuestionToggleBound = "true";
    toggle.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const questionId = toggle.dataset.storySetupQuestionId || toggle.closest(".question")?.dataset.storySetupQuestionId || "";
        if (questionId) {
          setStorySetupQuestionOpen(doc, questionId);
        }
      },
      true,
    );
  });
  stack.querySelectorAll(".answer-input").forEach((textarea) => {
    if (textarea.dataset.mafsQuestionInputBound === "true") {
      return;
    }
    textarea.dataset.mafsQuestionInputBound = "true";
    textarea.addEventListener("input", () => {
      const questionId = textarea.dataset.storySetupQuestionId || textarea.closest(".question")?.dataset.storySetupQuestionId || "";
      const view = doc.defaultView;
      if (questionId && view) {
        view.__mafsStorySetupQuestionAnswers = view.__mafsStorySetupQuestionAnswers || {};
        view.__mafsStorySetupQuestionAnswers[questionId] = textarea.value;
      }
    });
  });
  stack.querySelectorAll(".mini-save").forEach((save) => {
    if (save.dataset.mafsQuestionLocalSaveBound === "true") {
      return;
    }
    save.dataset.mafsQuestionLocalSaveBound = "true";
    save.addEventListener(
      "click",
      () => {
        const questionId = save.dataset.storySetupQuestionId || save.closest(".question")?.dataset.storySetupQuestionId || "";
        const answerText = save.closest(".question")?.querySelector(".answer-input")?.value || "";
        applyStorySetupQuestionLocalSave(doc, questionId, answerText);
      },
      true,
    );
  });
}

function initializeStorySetupQuestionDom(doc) {
  if (!doc?.body || !isFramePage(doc, new Set(["story-setup-review", "story-setup-missing"]))) {
    return;
  }
  const stack = doc.querySelector(".question-stack");
  if (stack) {
    bindStorySetupQuestionInteractions(doc, stack);
  }
}

function applyStorySetupQuestionLocalSave(doc, questionId, answerText) {
  if (!doc?.body || !questionId) {
    return;
  }
  const normalizedAnswer = String(answerText || "").trim();
  const hasAnswer = Boolean(normalizedAnswer);
  const view = doc.defaultView;
  if (view) {
    if (!(view.__mafsStorySetupAnsweredQuestionIds instanceof Set)) {
      view.__mafsStorySetupAnsweredQuestionIds = new Set();
    }
    if (hasAnswer) {
      view.__mafsStorySetupAnsweredQuestionIds.add(questionId);
    } else {
      view.__mafsStorySetupAnsweredQuestionIds.delete(questionId);
    }
    view.__mafsStorySetupQuestionAnswers = view.__mafsStorySetupQuestionAnswers || {};
    view.__mafsStorySetupQuestionAnswers[questionId] = normalizedAnswer;
  }
  const current = doc.querySelector(`.question-stack .question[data-story-setup-question-id="${cssEscapeValue(doc, questionId)}"]`);
  if (current) {
    current.querySelector(".question-toggle span") && (current.querySelector(".question-toggle span").textContent = hasAnswer ? "已回答" : "未回答");
    const save = current.querySelector(".mini-save");
    if (save) {
      save.textContent = hasAnswer ? "更新回答" : "保存回答";
    }
    const textarea = current.querySelector(".answer-input");
    if (textarea) {
      textarea.value = normalizedAnswer;
    }
  }
  const next = Array.from(doc.querySelectorAll(".question-stack .question")).find((article) => {
    const id = article.dataset.storySetupQuestionId || "";
    const status = article.querySelector(".question-toggle span")?.textContent || "";
    return id && id !== questionId && !/已回答|已保存/.test(status);
  });
  setStorySetupQuestionOpen(doc, next?.dataset.storySetupQuestionId || questionId);
}

function suppressStorySetupEmptyText(doc) {
  if (!doc?.body) {
    return;
  }
  const nodeFilter = doc.defaultView?.NodeFilter || window.NodeFilter;
  const walker = doc.createTreeWalker(doc.body, nodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const text = String(node.nodeValue || "").trim();
      if (text !== "暂无此项数据") {
        return nodeFilter.FILTER_REJECT;
      }
      const parent = node.parentElement;
      if (
        !parent ||
        parent.closest(
          "script, style, title, svg defs, button, a, input, select, textarea, option, [role='button'], [role='tab'], [data-mafs-live-status='true'], .mafs-bridge-toast",
        )
      ) {
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
    const parent = node.parentElement;
    node.nodeValue = "";
    if (parent) {
      parent.classList.add("mafs-empty-suppressed");
      parent.dataset.mafsBackendRendered = "true";
      parent.dataset.mafsBackendBound = "true";
    }
  });
}

function applyStorySetupDraftState(doc, result) {
  const draftBundle = findStorySetupDraftBundle(result);
  if (!doc?.body || !draftBundle) {
    return false;
  }
  const moduleData = buildStorySetupModuleData(draftBundle);
  if (!moduleData) {
    return false;
  }
  const view = doc.defaultView;
  if (view) {
    view.__mafsStorySetupDraftResult = result;
    view.__mafsStorySetupDraftData = moduleData;
  }

  Object.entries({
    world: "world",
    cast: "cast",
    framework: "framework",
    route: "chapters",
    chapters: "chapters",
  }).forEach(([domKey, dataKey]) => {
    const data = moduleData[dataKey];
    const card = doc.querySelector(`[data-module="${domKey}"], .draft-card[data-draft="${dataKey}"]`);
    if (!card || !data) {
      return;
    }
    const summaryNode =
      card.querySelector(":scope > p") ||
      Array.from(card.children).find((child) => child.tagName === "SPAN" && !child.classList.contains("tiny-dot"));
    setRenderedText(summaryNode, data.summary);
    markBackendRendered(card);
    card.classList.add("revealed");
  });

  renderStorySetupDetail(doc, "world", moduleData);
  renderStorySetupQuestions(doc, findStorySetupQuestions(result));

  if (!doc.body.dataset.mafsStorySetupDraftTabsBound) {
    doc.body.dataset.mafsStorySetupDraftTabsBound = "true";
    doc.querySelectorAll(".draft-card[data-draft]").forEach((card) => {
      card.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          renderStorySetupDetail(doc, card.dataset.draft, doc.defaultView?.__mafsStorySetupDraftData);
        },
        true,
      );
    });
  }

  setRenderedText(doc.getElementById("setupState"), "草案已生成");
  setRenderedText(doc.getElementById("stageTitle"), "后端草案已生成");
  setRenderedText(doc.getElementById("stageCopy"), "故事设定草案已由后端生成并同步到页面，可以进入审阅。");
  setRenderedText(doc.getElementById("sideProgressCopy"), "后端草案生成完成。");
  applyRealtimeProgressElements(doc, { label: "故事设定草案已生成", percent: 100 });
  suppressStorySetupEmptyText(doc);
  [120, 600, 1400].forEach((delayMs) => {
    window.setTimeout(() => suppressStorySetupEmptyText(doc), delayMs);
  });
  return true;
}

function lockStorySetupGenerationDom(doc) {
  if (!doc?.body || doc.body.dataset.mafsStorySetupGenerationDomLock === "true") {
    return;
  }
  const view = doc.defaultView;
  if (!view) {
    return;
  }
  doc.body.dataset.mafsStorySetupGenerationDomLock = "true";
  let applying = false;
  const enforce = () => {
    if (applying || !doc.body || doc.body.dataset.mafsGenerationStartupDone !== "true") {
      return;
    }
    applying = true;
    try {
      const ready = doc.body.dataset.mafsGenerationReady === "true";
      const message = doc.body.dataset.mafsGenerationMessage || (ready ? "后端草案生成完成" : "后端正在生成故事设定草案");
      setGenerationGate(doc, ready, message);
    } finally {
      applying = false;
    }
  };
  const Observer = view.MutationObserver || window.MutationObserver;
  const observer = new Observer(() => {
    window.requestAnimationFrame(enforce);
  });
  [
    "#setupState",
    "#stageTitle",
    "#stageCopy",
    "#sideProgressCopy",
    "#progressText",
    "#progressOrb",
    "#meterFill",
    "#reviewButton",
  ].forEach((selector) => {
    const element = doc.querySelector(selector);
    if (element) {
      observer.observe(element, {
        attributes: true,
        childList: true,
        characterData: true,
        subtree: true,
      });
    }
  });
  const intervalId = window.setInterval(enforce, 120);
  view.addEventListener(
    "pagehide",
    () => {
      observer.disconnect();
      window.clearInterval(intervalId);
    },
    { once: true },
  );
  enforce();
}

function setGenerationGate(doc, ready, message = "") {
  if (!doc?.body) {
    return;
  }
  const button = doc.querySelector("#reviewButton, #completeButton");
  if (!button) {
    return;
  }
  const readyText = button.dataset.mafsReadyLabel || button.textContent || "查看结果";
  if (!button.dataset.mafsReadyLabel) {
    button.dataset.mafsReadyLabel = readyText;
  }
  doc.body.dataset.mafsGenerationReady = ready ? "true" : "false";
  doc.body.dataset.mafsGenerationMessage = message || (ready ? "后端生成完成" : "后端正在生成");
  button.dataset.mafsBackendGate = ready ? "ready" : "pending";
  button.disabled = !ready;
  button.textContent = ready ? readyText.replace(/^等待.*$/, "查看草案") : "生成中";
  if (ready) {
    setRenderedText(doc.getElementById("setupState"), "草案已生成");
    setRenderedText(doc.getElementById("stageTitle"), "后端草案已生成");
    setRenderedText(doc.getElementById("stageCopy"), "故事设定草案已由后端生成并同步到页面，可以进入审阅。");
    setRenderedText(doc.getElementById("sideProgressCopy"), "后端草案生成完成。");
    applyRealtimeProgressElements(doc, { label: message || "故事设定草案已生成", percent: 100 });
  } else {
    applyRealtimeProgressElements(doc, { label: message || "后端正在生成草案", percent: 35 });
  }
}

function generationReadyFromRefsOrResult(pageId, refs, result) {
  const refKey = GENERATION_READY_REF_BY_PAGE_ID[pageId];
  if (!refKey) {
    return true;
  }
  return Boolean(refs?.[refKey] || findStorySetupDraftBundle(result));
}

function installGenerationGateEnforcer(doc) {
  if (!doc?.body || doc.body.dataset.mafsGenerationGateEnforcer === "true") {
    return;
  }
  const view = doc.defaultView;
  if (!view) {
    return;
  }
  doc.body.dataset.mafsGenerationGateEnforcer = "true";
  const enforce = () => {
    const ready = doc.body.dataset.mafsGenerationReady === "true";
    setGenerationGate(
      doc,
      ready,
      doc.body.dataset.mafsGenerationMessage || (ready ? "后端草案生成完成" : "后端正在生成草案"),
    );
  };
  const intervalId = window.setInterval(enforce, 240);
  view.addEventListener(
    "pagehide",
    () => {
      window.clearInterval(intervalId);
    },
    { once: true },
  );
  enforce();
}

function isBackendGenerationGatePending(target) {
  return Boolean(target?.closest?.("[data-mafs-backend-gate='pending']"));
}

function walkResult(value, visitor, depth = 0) {
  if (value === null || value === undefined || depth > 7) {
    return;
  }
  if (typeof value !== "object") {
    visitor("", value);
    return;
  }
  if (Array.isArray(value)) {
    value.slice(0, 12).forEach((item) => walkResult(item, visitor, depth + 1));
    return;
  }
  Object.entries(value).forEach(([key, item]) => {
    visitor(key, item);
    walkResult(item, visitor, depth + 1);
  });
}

function extractRealtimeStatus(result, actionId) {
  let label = "";
  let percent = null;
  const labelKeys = new Set([
    "progress_label",
    "progressLabel",
    "safe_summary",
    "safeSummary",
    "summary",
    "readiness_status",
    "readinessStatus",
  ]);
  const percentKeys = /^(completion_ratio|completionRatio|progress|progress_percent|progressPercent|percent|percentage|readiness_score|readinessScore|score)$/;

  walkResult(result, (key, item) => {
    if (!label && labelKeys.has(key) && typeof item === "string") {
      const text = item.trim();
      if (
        text &&
        /[\u4e00-\u9fff]/.test(text) &&
        !/[A-Za-z]{4,}/.test(text.replace(/Framework/g, "")) &&
        isUserFacingResultText(text) &&
        !["ok", "success", "ready", "seeded", "empty", "created", "confirmed", "drafted", "validated"].includes(text.toLowerCase()) &&
        !/^phase[_-]/i.test(text)
      ) {
        label = text.length > 80 ? `${text.slice(0, 80)}...` : text;
      }
    }
    if (percent === null && percentKeys.test(key) && typeof item === "number" && Number.isFinite(item)) {
      percent = item <= 1 ? Math.round(item * 100) : Math.round(item);
    }
  });

  return {
    label: label || ACTION_STATUS_LABEL_BY_ID[actionId] || "后端状态已同步",
    percent: percent === null ? null : Math.max(0, Math.min(100, percent)),
  };
}

function updateProgressElement(element, percent) {
  if (!element || percent === null || percent === undefined) {
    return;
  }
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  element.style.width = `${safePercent}%`;
  element.style.setProperty("--progress", String(safePercent));
  element.style.setProperty("--progress-value", `${safePercent}%`);
}

function applyRealtimeProgressElements(doc, status) {
  if (!doc?.body || !status) {
    return;
  }
  const { label, percent } = status;
  [
    "#topStatus",
    "#setupState",
    "#draftState",
    "#nextState",
    "#phaseWord",
    "#generationTitle",
    "#stageTitle",
    "#progressLabel",
    "#queueValidation",
    "#nextBox",
  ].forEach((selector) => {
    const element = doc.querySelector(selector);
    if (element) {
      if (selector === "#draftState" && isFramePage(doc, WORLD_CANVAS_PAGE_IDS)) {
        return;
      }
      element.textContent = label;
      element.dataset.mafsBackendBound = "true";
    }
  });

  if (percent !== null) {
    ["#progressText", "#progressBadge", "#progressCount", "#readerMetaValue", "#percentText"].forEach((selector) => {
      const element = doc.querySelector(selector);
      if (element) {
        element.textContent = `${percent}%`;
        element.dataset.mafsBackendBound = "true";
      }
    });
    ["#meterFill", "#progressFill", "#parseBar", "#validateBar", "#candidateBar", "#overallFill"].forEach((selector) => {
      updateProgressElement(doc.querySelector(selector), percent);
    });
    const progressOrb = doc.querySelector("#progressOrb");
    if (progressOrb) {
      progressOrb.style.setProperty("--progress", `${percent}%`);
    }
  }
}

function showRealtimeStatusPanel(doc, status) {
  if (!doc?.body || !status) {
    return;
  }
  injectBridgeStyle(doc);
  let panel = doc.getElementById("mafs-live-status-panel");
  if (!panel) {
    panel = doc.createElement("div");
    panel.id = "mafs-live-status-panel";
    panel.dataset.mafsLiveStatus = "true";
    panel.setAttribute("role", "status");
    panel.setAttribute("aria-live", "polite");
    panel.style.position = "fixed";
    panel.style.left = "24px";
    panel.style.bottom = "24px";
    panel.style.zIndex = "2147483646";
    panel.style.maxWidth = "min(460px, calc(100vw - 48px))";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.24)";
    panel.style.borderRadius = "12px";
    panel.style.padding = "10px 12px";
    panel.style.background = "rgba(255, 252, 244, 0.94)";
    panel.style.boxShadow = "0 18px 48px rgba(67, 52, 40, 0.14)";
    panel.style.color = "#2d2823";
    panel.style.font = '700 12px/1.55 "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Arial, sans-serif';
    panel.style.letterSpacing = "0";
    panel.style.backdropFilter = "blur(12px)";
    doc.body.appendChild(panel);
  }
  panel.textContent = status.percent === null ? `后端进度：${status.label}` : `后端进度：${status.percent}% · ${status.label}`;
}

function applyRealtimeResultState(doc, result, actionId) {
  if (!doc?.body || !result) {
    return;
  }
  const storySetupQuestions = findStorySetupQuestions(result);
  const hasStorySetupDraft = Boolean(findStorySetupDraftBundle(result));
  const hasWorldCanvas = Boolean(findWorldCanvasPayload(result));
  const hasCharacterDraft = Boolean(findCharacterDraftPayload(result));
  const hasRoleList = findNestedArray(result, ["roles", "characters", "items", "records"]).some((item) => item && typeof item === "object");
  let status = extractRealtimeStatus(result, actionId);
  if (hasStorySetupDraft && (actionId || "").startsWith("storySetup.")) {
    status = { label: "故事设定草案已生成", percent: 100 };
  }
  if (hasWorldCanvas && ((actionId || "").startsWith("world.") || isFramePage(doc, WORLD_CANVAS_PAGE_IDS))) {
    status = { label: "世界画布草案已同步", percent: 100 };
  }
  if (hasCharacterDraft && ((actionId || "").startsWith("characters.") || isFramePage(doc, CHARACTER_PAGE_IDS))) {
    status = { label: "\u89d2\u8272\u8349\u6848\u5df2\u540c\u6b65", percent: 100 };
  }
  if (hasRoleList && ((actionId || "").startsWith("roles.") || isFramePage(doc, ROLE_LIBRARY_PAGE_IDS))) {
    status = { label: "\u89d2\u8272\u6863\u6848\u5e93\u5df2\u540c\u6b65", percent: 100 };
  }
  renderProjectsSurface(doc, result);
  applyBackendResultState(doc, result);
  renderWorldCanvasSurface(doc, result);
  renderCharacterSurface(doc, result);
  renderRoleLibrarySurface(doc, result);
  renderRoleContextSurface(doc, result);
  renderFrameworkWorkbenchSurface(doc, result);
  renderFrameworkLibrarySurface(doc, result);
  renderChapterPlanSurface(doc, result);
  renderSceneSurface(doc, result);
  renderPluginSurface(doc, result);
  renderSettingsSurface(doc, result);
  applyRealtimeProgressElements(doc, status);
  if (storySetupQuestions.length) {
    renderStorySetupQuestions(doc, storySetupQuestions);
  }
  const storySetupApplied = applyStorySetupDraftState(doc, result);
  if (storySetupApplied) {
    setGenerationGate(doc, true, "后端草案生成完成");
  }
  showRealtimeStatusPanel(doc, status);
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function findResultText(result, keys) {
  let found = "";
  const keySet = new Set(keys);
  walkResult(result, (key, item) => {
    if (!found && keySet.has(key) && typeof item === "string" && item.trim()) {
      found = item.trim();
    }
  });
  return found;
}

function setControlValue(doc, selectors, value) {
  if (!value) {
    return;
  }
  selectors.forEach((selector) => {
    const element = doc.querySelector(selector);
    if (!element || !("value" in element)) {
      return;
    }
    element.value = value;
    element.dataset.mafsBackendBound = "true";
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function isLegacyStorySetupDefaultText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  const exactLegacyTexts = new Set([
    "港口城钟楼证词",
    "港城钟楼证词",
    "雾港钟楼证词",
    "港口城主骨架",
    "短篇悬疑骨架",
    "我想写一个围绕港口城、失忆晚宴、钟楼证词与潮汐禁区展开的低魔悬疑故事。主角从一个看似普通的失踪线索开始调查，逐渐发现城市规则、行会秩序和旧贵族秘密之间的裂缝。",
  ]);
  return (
    exactLegacyTexts.has(text) ||
    /^(港口城|港城|雾港).*(钟楼|证词)/.test(text) ||
    /(港口城|港城|雾港|旧钟|潮汐禁区|低魔悬疑).*(钟楼|证词|主骨架)/.test(text)
  );
}

function safeStorySetupInputText(value) {
  const text = String(value || "").trim();
  return isLegacyStorySetupDefaultText(text) ? "" : text;
}

function clearLegacyStorySetupEntryDefaults(doc) {
  if (!doc?.body || !isFramePage(doc, STORY_SETUP_ENTRY_PAGE_IDS)) {
    return;
  }
  const projectName = doc.getElementById("projectName");
  if (projectName && isLegacyStorySetupDefaultText(projectName.value)) {
    projectName.value = "";
    projectName.placeholder = "未命名故事项目";
  }
  const frameworkSelect = doc.getElementById("frameworkSelect");
  if (frameworkSelect) {
    Array.from(frameworkSelect.options || []).forEach((option) => {
      if (isLegacyStorySetupDefaultText(option.textContent) || /harbor|clock|mystery/i.test(option.value || "")) {
        option.remove();
      }
    });
    if (!frameworkSelect.querySelector("option[value='']")) {
      frameworkSelect.prepend(new Option("暂不绑定", ""));
    }
    if (!frameworkSelect.value || isLegacyStorySetupDefaultText(frameworkSelect.selectedOptions?.[0]?.textContent)) {
      frameworkSelect.value = "";
    }
  }
  const prompt = doc.getElementById("storyPrompt");
  if (prompt) {
    if (isLegacyStorySetupDefaultText(prompt.value)) {
      prompt.value = "";
    }
    if (isLegacyStorySetupDefaultText(prompt.placeholder)) {
      prompt.placeholder = "写下题材、世界范围、主角、冲突、氛围或任何你已经确定的故事想法。";
    }
  }
}

function isLegacyCharacterDefaultText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  return /(港口城|港城|雾港|钟表|钟楼|旧钟|潮汐禁区|低魔悬疑|洛闻|码头旅客|harbor|clock|old clock)/i.test(text);
}

function clearLegacyCharacterEntryDefaults(doc) {
  if (!doc?.body || !isFramePage(doc, CHARACTER_PAGE_IDS)) {
    return;
  }
  const prompt = doc.getElementById("characterPrompt");
  if (prompt) {
    if (isLegacyCharacterDefaultText(prompt.value)) {
      prompt.value = "";
    }
    if (!prompt.placeholder || isLegacyCharacterDefaultText(prompt.placeholder)) {
      prompt.placeholder = "写下角色身份、目标、秘密、关系张力，以及这个角色与当前世界规则的联系。";
    }
  }
  doc.querySelectorAll("body *").forEach((element) => {
    if (element.childElementCount !== 0) {
      return;
    }
    const text = element.textContent || "";
    if (isLegacyCharacterDefaultText(text)) {
      element.textContent = text
        .replace(/港口城|港城|雾港|钟表修复师|钟楼证词|旧钟|潮汐禁区|低魔悬疑|洛闻|码头旅客/gi, "当前项目角色")
        .replace(/harbor|clock|old clock/gi, "current project");
      markBackendRendered(element);
    }
  });
}

function applyBackendFormState(doc, result, form = {}) {
  if (!doc?.body) {
    return;
  }
  clearLegacyStorySetupEntryDefaults(doc);
  clearLegacyCharacterEntryDefaults(doc);
  const title = firstNonEmpty(
    safeStorySetupInputText(form.projectTitle),
    safeStorySetupInputText(form.requestedTitle),
    safeStorySetupInputText(form.projectName),
    safeStorySetupInputText(findResultText(result, ["requested_title", "requestedTitle", "proposed_title", "proposedTitle", "project_title", "title"])),
  );
  const prompt = firstNonEmpty(
    safeStorySetupInputText(form.setupPrompt),
    safeStorySetupInputText(form.promptText),
    safeStorySetupInputText(form.projectPrompt),
    safeStorySetupInputText(form.storyPrompt),
    safeStorySetupInputText(findResultText(result, ["prompt_text", "promptText", "setup_prompt", "setupPrompt"])),
  );
  setControlValue(doc, ["#projectName", "#project-title", "[name='projectName']", "[name='project-title']"], title);
  setControlValue(doc, ["#storyPrompt", "#story-prompt", "[name='storyPrompt']", "[name='story-prompt']"], prompt);
  clearLegacyStorySetupEntryDefaults(doc);
  clearLegacyCharacterEntryDefaults(doc);
}

function userFacingError(error) {
  const message = error?.message || "";
  if (/failed to fetch/i.test(message)) {
    return "无法连接后端，已停留在当前页面。请确认主体项目后端已启动后再重试。";
  }
  return message || "后端操作失败，已停留在当前页面。";
}

export default function ProductUiApp() {
  const iframeRef = useRef(null);
  const pendingNavigationResultRef = useRef(null);
  const refsRef = useRef({});
  const pageIdRef = useRef("");
  const [pageId, setPageId] = useState(parseHash);
  const [refs, setRefs] = useState({
    pluginId: "script_forging",
  });
  const page = useMemo(() => getPage(pageId), [pageId]);
  const showDirectory = !DIRECTORY_HIDDEN_PAGES.has(pageId);

  useEffect(() => {
    refsRef.current = refs;
  }, [refs]);

  useEffect(() => {
    pageIdRef.current = pageId;
  }, [pageId]);

  useEffect(() => {
    const onHashChange = () => setPageId(parseHash());
    window.addEventListener("hashchange", onHashChange);
    const rawHash = window.location.hash.replace(/^#\/?/, "");
    const initialPage = parseHash();
    if (!window.location.hash || rawHash !== initialPage) {
      navigate(initialPage);
    }
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [pageId]);

  useEffect(() => {
    if (pageId !== "opening") {
      return undefined;
    }
    const timer = window.setTimeout(() => navigate("home"), 4200);
    return () => window.clearTimeout(timer);
  }, [pageId]);

  useEffect(() => {
    let cancelled = false;
    hydrateWorkspaceRefs(refs, { workspaceId: workspaceIdForPageId(pageId) })
      .then((nextRefs) => {
        if (!cancelled) {
          setRefs(nextRefs);
          refsRef.current = nextRefs;
        }
      })
      .catch((error) => {
        if (getApiMode() === "live") {
          console.warn("[MAFS UI] failed to hydrate backend refs", error);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function executeAction(action, doc, sourceTarget = null) {
    if (!doc?.body || !doc.defaultView) {
      return;
    }
    try {
    setActionPhase(doc, "collect_form");
    const collectedForm = collectFrameForm(doc);
    const localContext = extractActionLocalContext(action, sourceTarget, collectedForm);
    const form = { ...collectedForm, ...(localContext.form || {}) };
    setActionForm(doc, form);
    if (isImmediateNavigationAction(action)) {
      setLastAction(doc, action.actionId || action.to);
      setActionPhase(doc, `navigate:${action.actionId || action.to}`);
      setFrameBusy(doc, false);
      navigate(action.to);
      return;
    }
    setActionPhase(doc, "set_busy");
    setFrameBusy(doc, true);
    let latestOutcome = null;
    if (action.actionId) {
      try {
        setActionPhase(doc, `run:${action.actionId}`);
        const actionRefs = { ...(refsRef.current || refs), ...(localContext.refs || {}) };
        const outcome = await runWorkspaceAction(action.actionId, { refs: actionRefs, form });
        setActionPhase(doc, `result:${action.actionId}`);
        setRefs(outcome.refs);
        refsRef.current = outcome.refs;
        latestOutcome = outcome;
        applyRealtimeResultState(doc, outcome.result, action.actionId);
        if (action.actionId === "storySetup.answerQuestion") {
          applyStorySetupQuestionLocalSave(doc, form.storySetupQuestionId, form.answerText);
        }
        if (pageId === "scene-generating" && action.actionId === "scene.current" && action.to === "scene-review") {
          let guard = 0;
          while (!sceneReadyFromResult(latestOutcome.result) && guard < 60) {
            setActionPhase(doc, `wait:${action.actionId}:${guard + 1}`);
            showFrameMessage(doc, "后端仍在生成场景正文，完成后会进入审阅页。");
            await new Promise((resolve) => window.setTimeout(resolve, 2000));
            const nextOutcome = await runWorkspaceAction(action.actionId, {
              refs: refsRef.current || refs,
              form,
              skipPreHydrate: true,
              skipShellState: true,
            });
            setRefs(nextOutcome.refs);
            refsRef.current = nextOutcome.refs;
            latestOutcome = nextOutcome;
            applyRealtimeResultState(doc, nextOutcome.result, action.actionId);
            guard += 1;
          }
          if (!sceneReadyFromResult(latestOutcome.result)) {
            throw new Error("场景正文仍未生成完成，请稍后重试。");
          }
        }
        const successMessage = action.actionId === "storySetup.answerQuestion" ? "回答已保存。" : outcome.message || "操作已完成。";
        showFrameMessage(doc, successMessage, outcome.skipped ? "neutral" : "success");
      } catch (error) {
        setActionPhase(doc, `error:${action.actionId}:${error?.message || ""}`);
        console.warn("[MAFS UI] action failed", action.actionId, error);
        showFrameMessage(doc, userFacingError(error), "error");
        setFrameBusy(doc, false);
        return;
      }
    }
    setFrameBusy(doc, false);
    if (action.to) {
      if (latestOutcome) {
        pendingNavigationResultRef.current = {
          pageId: action.to,
          actionId: action.actionId,
          result: latestOutcome.result,
          refs: latestOutcome.refs,
          form,
          createdAt: Date.now(),
        };
      }
      navigate(action.to);
    }
    } catch (error) {
      setActionPhase(doc, `error:${action.actionId || action.to || "navigation"}:${error?.message || ""}`);
      console.warn("[MAFS UI] action failed before backend call", action.actionId || action.to || "navigation", error);
      showFrameMessage(doc, userFacingError(error), "error");
      setFrameBusy(doc, false);
    }
  }

  async function hydrateFrameReadOnlyState(doc) {
    const actionId = READ_ONLY_LOAD_ACTION_BY_PAGE_ID[pageId];
    if (pageId === "story-setup-generating") {
      return;
    }
    if (!actionId || !doc?.body || doc.body.dataset.mafsReadOnlyHydratedFor === `${pageId}:${actionId}`) {
      return;
    }
    doc.body.dataset.mafsReadOnlyHydratedFor = `${pageId}:${actionId}`;
    try {
      const outcome = await runWorkspaceAction(actionId, {
        refs: refsRef.current || refs,
        form: {},
        skipPreHydrate: true,
        skipShellState: true,
      });
      setRefs(outcome.refs);
      refsRef.current = outcome.refs;
      const renderResult = {
        ...(outcome.result || {}),
        action_id: actionId,
        action_result: outcome.result?.action_result || outcome.result,
        hydrated_refs: outcome.refs,
        health: outcome.result?.health || outcome.result?.action_result?.health,
      };
      applyRealtimeResultState(doc, renderResult, actionId);
      applyBackendFormState(
        doc,
        renderResult,
        outcome.refs || {},
      );
    } catch (error) {
      if (getApiMode() === "live") {
        console.warn("[MAFS UI] read-only frame hydration failed", pageId, actionId, error);
      }
      applyRealtimeResultState(doc, {
        status: "empty",
        safe_summary: "当前项目暂无此页可展示的数据。",
      }, actionId);
    }
  }

  function hydrateFrameFromPendingNavigation(doc) {
    const pending = pendingNavigationResultRef.current;
    if (!pending || pending.pageId !== pageId || !doc?.body) {
      return;
    }
    pendingNavigationResultRef.current = null;
    if (pending.refs) {
      setRefs(pending.refs);
      refsRef.current = pending.refs;
    }
    applyRealtimeResultState(
      doc,
      {
        ...(pending.result || {}),
        action_id: pending.actionId,
        action_result: pending.result?.action_result || pending.result,
        hydrated_refs: pending.refs,
      },
      pending.actionId || "navigation",
    );
    applyBackendFormState(doc, pending.result, pending.form || {});
  }

  function startRealtimePolling(doc) {
    const actionId = REALTIME_LOAD_ACTION_BY_PAGE_ID[pageId];
    if (!actionId || !doc?.body || doc.body.dataset.mafsRealtimePollingFor === `${pageId}:${actionId}`) {
      return;
    }
    doc.body.dataset.mafsRealtimePollingFor = `${pageId}:${actionId}`;
    const startupActionId = GENERATION_START_ACTION_BY_PAGE_ID[pageId];
    let pollCount = 0;
    let stopped = false;

    const runStartupAction = async () => {
      if (!startupActionId || doc.body.dataset.mafsGenerationStartupDone === "true") {
        return;
      }
      doc.body.dataset.mafsGenerationStartupDone = "true";
      installGenerationGateEnforcer(doc);
      lockStorySetupGenerationDom(doc);
      setGenerationGate(doc, false, "后端正在生成故事设定草案");
      try {
        const outcome = await runWorkspaceAction(startupActionId, {
          refs: refsRef.current || refs,
          form: {},
          skipPreHydrate: true,
          skipShellState: true,
        });
        setRefs(outcome.refs);
        refsRef.current = outcome.refs;
        applyRealtimeResultState(doc, outcome.result, startupActionId);
        const ready = generationReadyFromRefsOrResult(pageId, outcome.refs, outcome.result);
        setGenerationGate(doc, ready, ready ? "后端草案生成完成" : "后端仍在生成故事设定草案");
      } catch (error) {
        doc.body.dataset.mafsGenerationStartupDone = "false";
        setGenerationGate(doc, false, "后端草案生成失败，请重试");
        if (getApiMode() === "live") {
          console.warn("[MAFS UI] realtime startup action failed", pageId, startupActionId, error);
        }
        showFrameMessage(doc, userFacingError(error), "error");
      }
    };

    const poll = async () => {
      if (stopped || pageIdRef.current !== pageId || iframeRef.current?.contentDocument !== doc) {
        return;
      }
      pollCount += 1;
      try {
        const outcome = await runWorkspaceAction(actionId, {
          refs: refsRef.current || refs,
          form: {},
          skipPreHydrate: true,
          skipShellState: true,
        });
        setRefs(outcome.refs);
        refsRef.current = outcome.refs;
        applyRealtimeResultState(doc, outcome.result, actionId);
      } catch (error) {
        if (getApiMode() === "live") {
          console.warn("[MAFS UI] realtime poll failed", pageId, actionId, error);
        }
        applyRealtimeResultState(
          doc,
          {
            status: "empty",
            safe_summary: "暂无此项数据",
          },
          actionId,
        );
      }
      if (!stopped && pollCount < REALTIME_MAX_POLLS && pageIdRef.current === pageId) {
        window.setTimeout(poll, REALTIME_POLL_INTERVAL_MS);
      }
    };

    window.setTimeout(async () => {
      await runStartupAction();
      poll();
    }, 250);
    doc.defaultView.addEventListener(
      "pagehide",
      () => {
        stopped = true;
      },
      { once: true },
    );
  }

  function bindFrameInteractions() {
    const iframe = iframeRef.current;
    const doc = iframe?.contentDocument;
    if (!doc) {
      return;
    }
    injectBridgeStyle(doc);
    doc.body.dataset.mafsPageId = pageId;
    clearLegacyStorySetupEntryDefaults(doc);
    clearLegacyCharacterEntryDefaults(doc);

    if (pageId === "plugin-entry") {
      ensurePluginEntryActionButton(doc);
    }
    if (pageId === "final-result") {
      ensureFinalResultPluginActionButton(doc);
    }

    page.actions.forEach((action) => {
      if (!action.selector) {
        return;
      }
      doc.querySelectorAll(action.selector).forEach((element) => {
        const bindingKey = `${action.actionId || ""}:${action.to || ""}:${action.selector}`;
        element.dataset.mafsInteractive = "true";
        element.dataset.mafsActionId = action.actionId || "";
        if (action.to) {
          element.dataset.mafsTarget = action.to;
        }
        if (element.dataset.mafsSelectorBound !== bindingKey) {
          element.dataset.mafsSelectorBound = bindingKey;
          element.addEventListener(
            "click",
            (event) => {
              event.preventDefault();
              event.stopImmediatePropagation();
              if (isBackendGenerationGatePending(event.target)) {
                showFrameMessage(doc, "后端仍在生成草案，完成后才能进入下一页。");
                return;
              }
              setLastAction(doc, action.actionId || action.to || "");
              executeAction(action, doc, event.target);
            },
            true,
          );
        }
      });
    });

    const interactive = Array.from(doc.querySelectorAll("button, a, [role='button']"));
    interactive.forEach((element) => {
      if (isLocalOnlyControl(page, element)) {
        return;
      }
      const matchedAction = page.actions.find((action) => actionMatches(element, action));
      const isBack = normalizeText(element.textContent || element.getAttribute("aria-label") || "").includes("返回");

      if (!matchedAction && !isBack) {
        return;
      }

      element.dataset.mafsInteractive = "true";
      if (matchedAction?.actionId) {
        element.dataset.mafsActionId = matchedAction.actionId;
      }
      if (matchedAction?.to) {
        element.dataset.mafsTarget = matchedAction.to;
      }

      element.addEventListener(
        "click",
        (event) => {
          const action = matchedAction || { to: getPreviousPage(pageId).id };
          event.preventDefault();
          event.stopImmediatePropagation();
          if (isBackendGenerationGatePending(event.target)) {
            showFrameMessage(doc, "后端仍在生成草案，完成后才能进入下一页。");
            return;
          }
          setLastAction(doc, action.actionId || action.to || "");
          executeAction(action, doc, event.target);
        },
        true,
      );
    });

    doc.addEventListener(
      "click",
      (event) => {
        const target = event.target?.closest?.("button, a, [role='button']");
        if (event.target?.closest?.("[data-mafs-selector-bound]")) {
          return;
        }
        if (isLocalOnlyControl(page, event.target)) {
          return;
        }
        const action =
          findDatasetAction(event.target) ||
          findSelectorAction(page, event.target) ||
          (target && page.actions.find((candidate) => actionMatches(target, candidate))) ||
          findHomeCoordinateAction(page, event, doc) ||
          (target && isBackElement(target) ? { to: getPreviousPage(pageId).id } : null) ||
          findPrimaryFallbackAction(page, target) ||
          findBlankDismissAction(page, target);

        if (!action) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        if (isBackendGenerationGatePending(event.target)) {
          showFrameMessage(doc, "后端仍在生成草案，完成后才能进入下一页。");
          return;
        }
        setLastAction(doc, action.actionId || action.to || "");
        executeAction(action, doc, event.target);
      },
      true,
    );

    applyBackendPendingState(doc);
    initializeStorySetupQuestionDom(doc);
    hydrateFrameFromPendingNavigation(doc);
    hydrateFrameReadOnlyState(doc);
    startRealtimePolling(doc);
  }

  return (
    <div className={`app-shell${showDirectory ? " has-directory" : ""}`}>
      {showDirectory && (
        <aside className="directory-rail" aria-label="工作台目录">
          <div className="directory-title">目录</div>
          <nav className="directory-nav">
            {DIRECTORY_ITEMS.map((item) => {
              const active = item.active.includes(pageId);
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`directory-item${active ? " active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  onClick={async () => {
                    try {
                      const nextRefs = await hydrateWorkspaceRefs(refsRef.current || refs, { workspaceId: workspaceIdForPageId(item.to) });
                      setRefs(nextRefs);
                      refsRef.current = nextRefs;
                    } catch (error) {
                      if (getApiMode() === "live") {
                        console.warn("[MAFS UI] directory hydrate failed", error);
                      }
                    }
                    navigate(item.to);
                  }}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>
        </aside>
      )}
      <iframe
        ref={iframeRef}
        className="confirmed-ui-frame"
        title={page.title}
        src={page.src}
        onLoad={bindFrameInteractions}
      />
    </div>
  );
}
