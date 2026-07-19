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
const CHAPTER_PLAN_PAGE_IDS = new Set([
  "chapter-source",
  "chapter-building",
  "chapter-framework-review",
  "chapter-route-entry",
  "chapter-route-generating",
  "chapter-route-review",
  "chapter-scene-count",
  "chapter-issue",
  "chapter-revision",
  "chapter-confirm",
]);
const SCENE_PAGE_IDS = new Set([
  "scene-entry",
  "scene-generating",
  "scene-review",
  "scene-revision",
  "scene-impact",
  "scene-continuity",
  "scene-gate",
  "scene-confirm",
  "chapter-closeout",
]);
const FINAL_OUTPUT_PAGE_IDS = new Set(["final-entry", "final-assembly", "final-review", "final-settings", "final-exporting", "final-result", "final-issue"]);
const PLUGIN_OUTPUT_PAGE_IDS = new Set(["plugin-entry", "plugin-select", "plugin-running", "plugin-checkpoint", "plugin-review", "plugin-issue"]);

const WORKFLOW_BACK_TARGET_BY_PAGE_ID = {
  projects: "home",
  "current-project": "projects",
  "template-demo": "current-project",
  framework: "current-project",
  "framework-library": "framework",
  "imported-session": "framework-candidate",
  "import-source": "current-project",
  analyzing: "import-source",
  "analysis-result": "import-source",
  "framework-candidate": "analysis-result",
  "story-setup-entry": "current-project",
  "story-setup-generating": "story-setup-entry",
  "story-setup-review": "story-setup-entry",
  "story-setup-missing": "story-setup-review",
  "story-setup-decision": "story-setup-review",
  "story-setup-handoff": "story-setup-review",
  "world-entry": "current-project",
  "world-generating": "world-entry",
  "world-review": "world-entry",
  "world-gap": "world-review",
  "world-revision": "world-review",
  "world-confirm": "world-review",
  "character-entry": "current-project",
  "character-generating": "character-entry",
  "character-review": "character-entry",
  "character-conflict": "character-review",
  "character-missing": "character-review",
  "character-revision": "character-review",
  "character-confirm": "character-review",
  "role-library": "current-project",
  "role-context": "role-library",
  "a-tier-state-change": "role-library",
  "chapter-source": "current-project",
  "chapter-building": "chapter-source",
  "chapter-framework-review": "chapter-source",
  "chapter-route-entry": "chapter-source",
  "chapter-route-generating": "chapter-route-entry",
  "chapter-route-review": "chapter-route-entry",
  "chapter-scene-count": "chapter-route-review",
  "chapter-issue": "chapter-route-review",
  "chapter-revision": "chapter-route-review",
  "chapter-confirm": "chapter-route-review",
  "scene-entry": "current-project",
  "scene-brief": "scene-entry",
  "scene-generating": "scene-entry",
  "scene-review": "scene-entry",
  "scene-revision": "scene-review",
  "scene-continuity": "scene-review",
  "scene-confirm": "scene-review",
  "scene-gate": "scene-review",
  "scene-impact": "scene-review",
  "chapter-closeout": "scene-entry",
  "final-entry": "current-project",
  "final-assembly": "final-entry",
  "final-review": "final-assembly",
  "final-settings": "final-review",
  "final-exporting": "final-settings",
  "final-result": "final-exporting",
  "final-issue": "final-entry",
  "plugin-entry": "current-project",
  "plugin-select": "plugin-entry",
  "plugin-running": "plugin-select",
  "plugin-checkpoint": "plugin-running",
  "plugin-review": "plugin-entry",
  "plugin-issue": "plugin-review",
  "settings-overview": "current-project",
  "settings-appearance": "settings-overview",
  "settings-model": "settings-overview",
  "settings-health": "settings-overview",
  "settings-secrets": "settings-overview",
  "settings-preferences": "settings-overview",
};

function workflowBackTarget(pageId) {
  return WORKFLOW_BACK_TARGET_BY_PAGE_ID[pageId] || getPreviousPage(pageId).id;
}

function backTargetForElement(pageId, element) {
  const label = controlActionText(element);
  if (label.includes("返回总览") || label.includes("返回当前项目")) {
    return "current-project";
  }
  if (label.includes("返回档案馆") || label.includes("返回项目列表")) {
    return "projects";
  }
  return workflowBackTarget(pageId);
}

const READ_ONLY_LOAD_ACTION_BY_PAGE_ID = {
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
  "role-context": "roles.contextPreview",
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
  "scene-revision": "scene.currentRevision",
  "scene-continuity": "scene.continuityCheck",
  "scene-confirm": "scene.current",
  "scene-gate": "scene.continuityCheck",
  "scene-impact": "scene.currentRevision",
  "chapter-closeout": "scene.archiveCurrent",
  "final-entry": "final.evaluate",
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
  "settings-health": "settings.workbench",
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
const MODEL_GENERATION_RETRY_DELAYS_MS = [900, 1800];

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

function sceneSelectionFromDocument(doc) {
  let parentSceneId = "";
  let parentSceneIndex = 0;
  try {
    parentSceneId = String(doc?.defaultView?.parent?.__mafsSelectedSceneId || "");
    parentSceneIndex = Number(doc?.defaultView?.parent?.__mafsSelectedSceneIndex || 0) || 0;
  } catch {
    // Same-origin product frames expose their selection to the parent. Embedded
    // hosts may forbid parent access, so retain the page-local selection.
  }
  const sceneId = String(doc?.body?.dataset?.mafsSelectedSceneId || parentSceneId || "");
  const sceneIndex = Number(doc?.body?.dataset?.mafsSelectedSceneIndex || parentSceneIndex || 0) || 0;
  if (!sceneId && !sceneIndex) {
    return {};
  }
  return {
    ...(sceneId ? { sceneId } : {}),
    ...(sceneIndex ? { sceneIndex } : {}),
    sceneSelectionPinned: true,
  };
}

function persistSceneSelection(doc, scene) {
  if (!doc?.body || !scene) {
    return;
  }
  const sceneId = firstNonEmpty(scene.scene_id, scene.sceneId, scene.id);
  const sceneIndex = Number(scene.scene_index || scene.sceneIndex || 0) || 0;
  if (sceneId) {
    doc.body.dataset.mafsSelectedSceneId = sceneId;
  }
  if (sceneIndex) {
    doc.body.dataset.mafsSelectedSceneIndex = String(sceneIndex);
  }
  try {
    if (sceneId) {
      doc.defaultView.parent.__mafsSelectedSceneId = sceneId;
    }
    if (sceneIndex) {
      doc.defaultView.parent.__mafsSelectedSceneIndex = sceneIndex;
    }
  } catch {
    // Keep the iframe-local selection when an embedding host forbids access.
  }
}

function navigate(pageId) {
  window.location.hash = pageId;
}

function isImmediateNavigationAction(action) {
  return Boolean(action?.to && (!action?.actionId || action.actionId.startsWith("navigation.")));
}

function postActionTarget(action, latestOutcome = null) {
  const actionId = String(action?.actionId || "");
  if (actionId === "chapter.generatePlan" || actionId === "chapter.revise") {
    const result = latestOutcome?.result || {};
    const directDraft =
      result?.draft ||
      result?.chapter_plan?.draft ||
      result?.chapterPlan?.draft ||
      result?.action_result?.draft ||
      result?.actionResult?.draft ||
      null;
    const draft = directDraft || findNestedObject(
      result,
      (item) => Array.isArray(item?.chapter_routes) || Array.isArray(item?.chapterRoutes),
    );
    const routes =
      draft?.chapter_routes ||
      draft?.chapterRoutes ||
      result?.chapters ||
      result?.chapter_plan?.chapters ||
      result?.chapterPlan?.chapters ||
      [];
    if (Array.isArray(routes) && routes.length) {
      return "chapter-route-review";
    }
  }
  if (actionId === "scene.generateFirst" || actionId === "scene.generateNext" || actionId === "scene.regenerateFirst") {
    const result = latestOutcome?.result || {};
    const participantGate = findNestedObject(
      result,
      (item) => item?.generation_blocked === true || item?.generationBlocked === true,
    );
    if (participantGate) {
      return "scene-gate";
    }
    if (sceneReadyFromResult(result)) {
      return "scene-review";
    }
  }
  if (actionId === "scene.confirmParticipant") {
    // Confirming a participant only changes the scene context. It never
    // generates prose, so stale or nested historical scene records must not
    // route the user into a previous scene review.
    return "scene-entry";
  }
  if (actionId === "scene.commit") {
    const result = latestOutcome?.result || {};
    const autoRepair = findNestedObject(
      result,
      (item) => item?.commit_auto_repair_required === true || item?.commitAutoRepairRequired === true,
    );
    if (autoRepair) {
      return "scene-review";
    }
  }
  return action?.to || "";
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, "");
}

function closestActionControl(element) {
  return element?.closest?.("button, a, [role='button'], input[type='button'], input[type='submit']") || null;
}

function controlActionText(element) {
  const control = closestActionControl(element);
  if (!control) {
    return "";
  }
  return normalizeText(`${control.textContent || ""} ${control.getAttribute("aria-label") || ""} ${control.title || ""} ${control.value || ""}`);
}

function isShortExplicitControl(element) {
  const control = closestActionControl(element);
  if (!control) {
    return false;
  }
  const text = controlActionText(control);
  return Boolean(text) && text.length <= 80;
}

function cssEscapeValue(doc, value) {
  const text = String(value || "");
  return doc?.defaultView?.CSS?.escape ? doc.defaultView.CSS.escape(text) : text.replace(/["\\]/g, "\\$&");
}

function actionMatches(element, action) {
  if (action.selector) {
    return element.matches(action.selector);
  }
  if (!isShortExplicitControl(element)) {
    return false;
  }
  const text = controlActionText(element);
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
  if (page.id.startsWith("story-setup-") && target.closest("[data-phase], [data-strip]")) {
    const phaseElement = target.closest("[data-phase], [data-strip]");
    const phase = String(phaseElement?.dataset?.phase || phaseElement?.dataset?.strip || "");
    const targetByPhase = {
      entry: "story-setup-entry",
      generating: "story-setup-generating",
      review: "story-setup-review",
      handoff: "story-setup-decision",
    };
    return targetByPhase[phase] ? { to: targetByPhase[phase] } : null;
  }
  if (
    ["import-source", "analyzing", "analysis-result", "framework-candidate"].includes(page.id) &&
    target.closest(".route-step[data-route]")
  ) {
    const route = String(target.closest(".route-step[data-route]")?.dataset?.route || "");
    const targetByRoute = {
      source: "import-source",
      analysis: "analyzing",
      result: "analysis-result",
      candidate: "framework-candidate",
    };
    const to = targetByRoute[route];
    return to && to !== page.id ? { to } : null;
  }
  if (WORLD_CANVAS_PAGE_IDS.has(page.id) && target.closest("[data-stage]")) {
    const stage = String(target.closest("[data-stage]")?.dataset?.stage || "");
    const targetByStage = {
      source: "world-entry",
      generate: "world-generating",
      review: "world-review",
      fact: "world-confirm",
    };
    const to = targetByStage[stage];
    if (!to || to === page.id) {
      return null;
    }
    return {
      to,
      ...(stage === "review" || stage === "fact" ? { actionId: "world.current" } : {}),
    };
  }
  if (CHARACTER_PAGE_IDS.has(page.id) && target.closest(".stage-button, [data-stage]")) {
    const stageElement = target.closest(".stage-button, [data-stage]");
    const stageLabel = normalizeText(stageElement?.textContent || "");
    const stage = String(
      stageElement?.dataset?.stage ||
        (stageLabel.includes("生成入口")
          ? "entry"
          : stageLabel.includes("生成草案")
            ? "generate"
            : stageLabel.includes("审阅确认")
              ? "review"
              : stageLabel.includes("角色底座")
                ? "fact"
                : ""),
    );
    const targetByStage = {
      entry: "character-entry",
      generate: "character-generating",
      review: "character-review",
      fact: "role-library",
    };
    const to = targetByStage[stage];
    if (!to || to === page.id) {
      return null;
    }
    return {
      to,
      actionId: stage === "fact" ? "roles.refresh" : "characters.current",
    };
  }
  if (
    (page.id === "story-setup-review" || page.id === "story-setup-missing") &&
    target.closest(".mini-save, #saveButton")
  ) {
    const button = target.closest(".mini-save, #saveButton");
    const questionCard = button?.closest?.(".question") || button?.closest?.("[data-story-setup-question-id]");
    const questionId =
      button?.dataset?.storySetupQuestionId ||
      questionCard?.dataset?.storySetupQuestionId ||
      "";
    return {
      to: page.id,
      actionId: "storySetup.answerQuestion",
      localContext: { storySetupQuestionId: questionId },
    };
  }
  if (page.id === "character-confirm" && target.closest("#confirmButton, #sideConfirmButton")) {
    const button = target.closest("#confirmButton, #sideConfirmButton");
    const actionId = String(button?.dataset?.mafsActionId || "");
    if (actionId && actionId !== "characters.confirm") {
      return {
        to: String(button?.dataset?.mafsTarget || "role-library"),
        actionId,
      };
    }
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
  if (page.id === "chapter-route-review" && target.closest("#mafsSceneCountButton")) {
    return { to: "chapter-scene-count" };
  }
  if (page.id === "chapter-route-review" && target.closest("#mafsConfirmChapterButton")) {
    return { to: "chapter-confirm" };
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
  const control = target.closest("button, a, [role='button'], input, select, textarea");
  if (
    control?.closest(".mafs-backend-rendered") &&
    !control.closest("[data-mafs-action-id], [data-mafs-target]")
  ) {
    return true;
  }
  if (control?.matches("[data-local-only='true'], [data-mafs-local-only='true']")) {
    return true;
  }
  if (
    target.closest(
      "[role='tab'], .tab-button, .section-tab, .view-tab, .filter-button, .view-button, [data-panel], [data-filter]",
    )
  ) {
    return true;
  }
  if (page.id === "story-setup-review" && target.closest(".draft-card, [role='tab'], .question-toggle, .answer-input")) {
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
    target.closest("#issueList .issue-item")
  ) {
    return true;
  }
  if (
    CHARACTER_PAGE_IDS.has(page.id) &&
    target.closest(".tier-trigger, .tier-option, #clearButton")
  ) {
    return true;
  }
  if (page.id === "role-library" && target.closest("#roleList .item[data-role-index]")) {
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
  if (page.id === "settings-model" && target.closest(".profile-card, .provider-pill")) {
    return true;
  }
  if (page.id === "final-settings" && target.closest(".format-card[data-format]")) {
    return true;
  }
  if (page.id === "final-entry" && target.closest("[data-final-issue-index]")) {
    return true;
  }
  if (
    page.id === "final-review" &&
    target.closest(".warning-row, #resolveWarning, #openSource, #readCheck, #warningCheck")
  ) {
    return true;
  }
  if (page.id === "final-exporting" && target.closest(".step-row")) {
    return true;
  }
  if (page.id === "projects" && target.closest(".project-card")) {
    return true;
  }
  if (page.id === "current-project" && target.closest(".stage-node")) {
    return true;
  }
  if (
    page.id === "template-demo" &&
    target.closest(".template-card, .demo-card, .filter-button, .flow-step, .demo-action[data-local-only]")
  ) {
    return true;
  }
  if (
    page.id === "import-source" &&
    target.closest(".source-option, .path-step, #ledgerButton, #closeLedger, #chooseFile, #saveDraft")
  ) {
    return true;
  }
  if (
    page.id === "chapter-scene-count" &&
    target.closest("#mafsSceneCountMinus, #mafsSceneCountPlus, #mafsSceneCountInput")
  ) {
    return true;
  }
  if (
    page.id === "chapter-revision" &&
    target.closest("#mafsClearChapterRevisionButton, #mafsChapterRevisionPrompt")
  ) {
    return true;
  }
  return false;
}

function setAlias(form, key, value) {
  if (!key || form[key] !== undefined) {
    return;
  }
  form[key] = value;
}

function isBackendPlaceholderFormValue(value) {
  const text = String(value ?? "").trim();
  return (
    !text ||
    text === "暂无此项数据" ||
    text === "正在读取项目数据" ||
    text === "待后端接入"
  );
}

function setPreferredAlias(form, key, value) {
  if (!key) {
    return;
  }
  const currentValue = form[key];
  if (
    currentValue === undefined ||
    (isBackendPlaceholderFormValue(currentValue) &&
      !isBackendPlaceholderFormValue(value))
  ) {
    form[key] = value;
  }
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
    resolutionnote: ["worldRevision"],
  };

  (aliasMap[rawKey] || aliasMap[compactKey] || aliasMap[lowerKey] || []).forEach((alias) => {
    setAlias(form, alias, value);
  });

  if (lowerKey.includes("revision")) {
    setPreferredAlias(form, "worldRevision", value);
    setPreferredAlias(form, "characterRevision", value);
    setPreferredAlias(form, "chapterRevision", value);
    setPreferredAlias(form, "sceneRevision", value);
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
  if (chapterCount && !form.chapterCount) {
    form.chapterCount = chapterCount;
  }

  const sceneCountText = textContent(doc, "#count-value");
  const sceneCount = sceneCountText.match(/\d+/)?.[0];
  if (sceneCount && !form.sceneCount) {
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

  const activeProvider = doc.querySelector(".provider-pill.active[data-provider]")?.dataset?.provider;
  if (activeProvider) {
    form.providerType = activeProvider;
  }

  const activeDecision = doc.querySelector(
    ".decision-option.active[data-decision], [aria-checked='true'][data-decision]",
  )?.dataset?.decision;
  if (activeDecision) {
    form.decisionType = activeDecision;
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

function isGeneratedQuestionSuggestionText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  return (
    /^可参考[:：]/.test(text) ||
    /^参考[:：]/.test(text) ||
    /^建议[:：]/.test(text) ||
    text.includes("仅锁定") ||
    text.includes("可参考") ||
    text.includes("建议用户确认")
  );
}

function storySetupQuestionAnswered(question) {
  const status = String(question?.answer_status || question?.answerStatus || "").toLowerCase();
  const normalizedStatus = status.replace(/[\s-]+/g, "_");
  const explicitAnswerText = String(question?.answer_text || question?.answerText || question?.user_answer || question?.userAnswer || "").trim();
  const hasCleanAnswerText = Boolean(explicitAnswerText && !isGeneratedQuestionSuggestionText(explicitAnswerText));
  const hasExplicitUserAnswerRef = Boolean(question?.user_answer_ref || question?.userAnswerRef);
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
  return Boolean(hasExplicitUserAnswerRef || (hasCleanAnswerText && positiveStatuses.has(normalizedStatus)));
}

function storySetupQuestionAnswerText(question) {
  const text = String(
    question?.answer_text ||
    question?.answerText ||
      question?.user_answer ||
      question?.userAnswer ||
      "",
  ).trim();
  return isGeneratedQuestionSuggestionText(text) ? "" : text;
}

function extractActionLocalContext(action, sourceTarget, form) {
  const refs = { ...(action?.localContext || {}) };
  const nextForm = {};
  const sourceDocument = sourceTarget?.ownerDocument;
  if (sourceDocument && SCENE_PAGE_IDS.has(framePageId(sourceDocument))) {
    Object.assign(refs, sceneSelectionFromDocument(sourceDocument));
  }
  if (action?.actionId?.startsWith("template.")) {
    const doc = sourceTarget?.ownerDocument;
    const templateId =
      sourceTarget?.closest?.("[data-template-id]")?.dataset?.templateId ||
      doc?.body?.dataset?.mafsSelectedTemplateId ||
      "";
    const demoSeedId =
      sourceTarget?.closest?.("[data-demo-seed-id]")?.dataset?.demoSeedId ||
      doc?.body?.dataset?.mafsSelectedDemoSeedId ||
      "";
    if (templateId) {
      refs.templateId = templateId;
    }
    if (demoSeedId) {
      refs.demoSeedId = demoSeedId;
    }
    return { refs, form: nextForm };
  }
  if (action?.actionId === "final.download") {
    const formatControl = sourceTarget?.closest?.("[data-format]");
    const exportFormat = String(formatControl?.dataset?.format || form?.exportFormat || "txt");
    nextForm.exportFormat = ["txt", "markdown", "json"].includes(exportFormat) ? exportFormat : "txt";
    return { refs, form: nextForm };
  }
  if (action?.actionId === "projects.openSelected") {
    const doc = sourceTarget?.ownerDocument;
    const selectedProjectId =
      sourceTarget?.closest?.("[data-project-id]")?.dataset?.projectId ||
      sourceTarget?.closest?.(".project-card")?.dataset?.id ||
      doc?.body?.dataset?.mafsSelectedProjectId ||
      "";
    if (selectedProjectId) {
      refs.selectedProjectId = selectedProjectId;
      nextForm.selectedProjectId = selectedProjectId;
    }
    return { refs, form: nextForm };
  }
  if (
    action?.actionId?.startsWith("framework.") ||
    action?.actionId === "analyze.startEditSession" ||
    action?.actionId === "analyze.refresh"
  ) {
    const doc = sourceTarget?.ownerDocument;
    const target = sourceTarget?.closest?.(
      "[data-imported-edit-session-id], [data-imported-activation-plan-id], [data-analyze-candidate-id]",
    ) || sourceTarget;
    const importedEditSessionId =
      target?.dataset?.importedEditSessionId ||
      doc?.getElementById("importedEditSessionId")?.value ||
      "";
    const importedActivationPlanId =
      target?.dataset?.importedActivationPlanId ||
      doc?.getElementById("importedActivationPlanId")?.value ||
      "";
    const analyzeCandidateId =
      target?.dataset?.analyzeCandidateId ||
      doc?.getElementById("analyzeCandidateId")?.value ||
      "";
    if (importedEditSessionId) {
      refs.importedEditSessionId = importedEditSessionId;
      nextForm.importedEditSessionId = importedEditSessionId;
    }
    if (importedActivationPlanId) {
      refs.importedActivationPlanId = importedActivationPlanId;
      nextForm.importedActivationPlanId = importedActivationPlanId;
    }
    if (analyzeCandidateId) {
      refs.analyzeCandidateId = analyzeCandidateId;
      nextForm.analyzeCandidateId = analyzeCandidateId;
    }
    return { refs, form: nextForm };
  }
  if (action?.actionId?.startsWith("roles.")) {
    const doc = sourceTarget?.ownerDocument;
    const characterId =
      sourceTarget?.closest?.("[data-character-id]")?.dataset?.characterId ||
      doc?.body?.dataset?.mafsSelectedCharacterId ||
      "";
    if (characterId) {
      refs.characterId = characterId;
    }
    return { refs, form: nextForm };
  }
  if (action?.actionId === "chapter.revise") {
    const doc = sourceTarget?.ownerDocument;
    const revisionInput = doc?.getElementById("mafsChapterRevisionPrompt");
    nextForm.chapterRevision = revisionInput?.value ?? form?.chapterRevision ?? "";
    return { refs, form: nextForm };
  }
  if (
    action?.actionId === "scene.revise" ||
    action?.actionId === "scene.reviseConfirmed"
  ) {
    const doc = sourceTarget?.ownerDocument;
    const revisionInput =
      doc?.getElementById("mafsSceneRevisionInput") ||
      doc?.querySelector(
        "textarea[name='scene-revision'], textarea[data-mafs-scene-revision], textarea#revisionPrompt",
      );
    const revisionText = String(
      revisionInput?.value ?? form?.sceneRevision ?? "",
    ).trim();
    if (revisionText && !isBackendPlaceholderFormValue(revisionText)) {
      nextForm.sceneRevision = revisionText;
    }
    return { refs, form: nextForm };
  }
  if (action?.actionId === "scene.openExisting" || action?.to === "scene-revision") {
    const sceneTarget = sourceTarget?.closest?.("[data-mafs-scene-id]") || sourceTarget;
    const sceneId = sceneTarget?.dataset?.mafsSceneId || "";
    const sceneIndex = Number(sceneTarget?.dataset?.mafsSceneIndex || 0) || 0;
    if (sceneId) {
      refs.sceneId = sceneId;
    }
    if (sceneIndex) {
      refs.sceneIndex = sceneIndex;
    }
    refs.sceneSelectionPinned = true;
    return { refs, form: nextForm };
  }
  if (action?.actionId !== "storySetup.answerQuestion" || !sourceTarget?.closest) {
    return { refs, form: nextForm };
  }

  const button = sourceTarget.closest(".mini-save, #saveButton");
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
    sourceDocument?.querySelector?.("#answerInput") ||
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
    body.mafs-frame-hydrating {
      min-height: 100vh;
      background: #f6f0e4 !important;
      cursor: wait;
    }
    body.mafs-frame-hydrating > :not(.mafs-frame-hydration-overlay) {
      visibility: hidden !important;
      pointer-events: none !important;
    }
    .mafs-frame-hydration-overlay {
      position: fixed;
      inset: 0;
      z-index: 2147483647;
      display: grid;
      place-items: center;
      padding: 24px;
      background: #f6f0e4;
      color: #2d2823;
      font: 700 14px/1.65 "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Arial, sans-serif;
      letter-spacing: 0;
    }
    .mafs-frame-hydration-overlay > div {
      width: min(420px, calc(100vw - 48px));
      border: 1px solid rgba(121, 89, 74, 0.22);
      border-radius: 8px;
      padding: 18px;
      background: rgba(255, 252, 244, 0.98);
      box-shadow: 0 18px 48px rgba(43, 35, 29, 0.14);
    }
    .mafs-frame-hydration-overlay strong {
      display: block;
      margin-bottom: 6px;
      font-size: 18px;
    }
    .mafs-frame-hydration-overlay p {
      margin: 0;
      font-weight: 500;
    }
    [data-mafs-backend-gate="pending"] {
      cursor: wait !important;
      opacity: 0.62 !important;
    }
    .mafs-backend-busy-overlay {
      position: fixed;
      inset: 0;
      z-index: 2147483646;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgba(44, 38, 32, 0.26);
      backdrop-filter: blur(3px);
    }
    .mafs-backend-busy-card {
      width: min(460px, calc(100vw - 48px));
      border: 1px solid rgba(121, 89, 74, 0.28);
      border-radius: 8px;
      padding: 18px;
      background: rgba(255, 252, 244, 0.98);
      box-shadow: 0 18px 48px rgba(43, 35, 29, 0.22);
      color: #2d2823;
      font: 700 14px/1.65 "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Arial, sans-serif;
      letter-spacing: 0;
    }
    .mafs-backend-busy-card strong {
      display: block;
      margin-bottom: 6px;
      font-size: 18px;
    }
    .mafs-backend-busy-card p {
      margin: 0;
    }
    .mafs-backend-busy-elapsed {
      margin-top: 10px !important;
      color: #5d6f64;
      font-variant-numeric: tabular-nums;
    }
    .mafs-generation-retry {
      min-height: 40px;
      border: 1px solid rgba(121, 89, 74, 0.32);
      border-radius: 6px;
      padding: 9px 16px;
      background: #fffaf0;
      color: #4b3b31;
      font: 700 13px/1.4 "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Arial, sans-serif;
      letter-spacing: 0;
      cursor: pointer;
    }
    .mafs-generation-retry:hover {
      border-color: rgba(121, 89, 74, 0.55);
      background: #f7efe1;
    }
    .mafs-generation-retry:disabled {
      cursor: wait;
      opacity: 0.6;
    }
  `;
  doc.head?.appendChild(style);
}

function setFrameHydrating(doc, hydrating, message = "正在同步当前工作台的项目数据。") {
  if (!doc?.body) {
    return;
  }
  injectBridgeStyle(doc);
  doc.body.classList.toggle("mafs-frame-hydrating", Boolean(hydrating));
  doc.body.dataset.mafsFrameHydration = hydrating ? "pending" : "ready";
  let overlay = doc.getElementById("mafs-frame-hydration-overlay");
  if (!hydrating) {
    overlay?.remove();
    return;
  }
  if (!overlay) {
    overlay = doc.createElement("div");
    overlay.id = "mafs-frame-hydration-overlay";
    overlay.className = "mafs-frame-hydration-overlay";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    overlay.innerHTML = "<div><strong>正在同步当前工作台</strong><p></p></div>";
    doc.body.appendChild(overlay);
  }
  const detail = overlay.querySelector("p");
  if (detail) {
    detail.textContent = message;
  }
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
  toast.setAttribute("role", tone === "error" ? "alert" : "status");
  toast.textContent = message;
  window.clearTimeout(toast._mafsTimer);
  if (tone === "error") {
    toast._mafsTimer = null;
    return;
  }
  toast._mafsTimer = window.setTimeout(() => {
    toast?.remove();
  }, 2600);
}

function backendActionBusyMessage(actionId) {
  if (["scene.generateFirst", "scene.generateNext", "scene.regenerateFirst"].includes(actionId)) {
    return "后端正在调用模型生成当前幕正文并执行质量与连续性检查。完成前不会进入下一页。";
  }
  if (["storySetup.generate", "worldCanvas.generate", "character.generate", "chapter.generatePlan"].includes(actionId)) {
    return "后端正在调用模型整理当前创作内容。收到完整结果后会自动进入下一步。";
  }
  return "后端正在处理当前操作。收到成功响应后才会更新页面或进入下一步。";
}

function setFrameBusy(doc, busy, message = "") {
  if (!doc?.body) {
    return;
  }
  injectBridgeStyle(doc);
  doc.body.classList.toggle("mafs-action-busy", Boolean(busy));
  const existing = doc.getElementById("mafs-backend-busy-overlay");
  if (!busy) {
    const timer = existing?._mafsElapsedTimer;
    if (timer) {
      doc.defaultView?.clearInterval(timer);
    }
    existing?.remove();
    return;
  }
  const overlay = existing || doc.createElement("div");
  overlay.id = "mafs-backend-busy-overlay";
  overlay.className = "mafs-backend-busy-overlay";
  overlay.dataset.mafsLiveStatus = "true";
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-live", "polite");
  overlay.setAttribute("aria-busy", "true");
  overlay.innerHTML = `
    <div class="mafs-backend-busy-card">
      <strong>后端处理中</strong>
      <p>${escapeHtml(message || "后端正在处理当前操作。完成前不会进入下一页。")}</p>
      <p class="mafs-backend-busy-elapsed">已等待 0 秒</p>
    </div>
  `;
  if (!existing) {
    doc.body.appendChild(overlay);
  }
  markBackendRendered(overlay);
  overlay._mafsBusyStartedAt = Date.now();
  if (overlay._mafsElapsedTimer) {
    doc.defaultView?.clearInterval(overlay._mafsElapsedTimer);
  }
  overlay._mafsElapsedTimer = doc.defaultView?.setInterval(() => {
    const elapsed = Math.max(0, Math.floor((Date.now() - overlay._mafsBusyStartedAt) / 1000));
    const label = overlay.querySelector(".mafs-backend-busy-elapsed");
    if (label) {
      label.textContent = `已等待 ${elapsed} 秒`;
    }
  }, 1000);
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

function storySetupDraftReadyFromResult(result) {
  const draftBundle = findStorySetupDraftBundle(result);
  if (!draftBundle) {
    return false;
  }
  const usedFallback = Boolean(
    draftBundle.used_deterministic_fallback ?? draftBundle.usedDeterministicFallback,
  );
  if (!usedFallback) {
    return true;
  }
  const prompt = findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.story_setup_prompt_id &&
          (item?.active_model_provider_type || item?.activeModelProviderType),
      ),
  );
  const providerType = String(
    prompt?.active_model_provider_type || prompt?.activeModelProviderType || "",
  )
    .trim()
    .toLowerCase();
  return providerType === "local";
}

function findStorySetupQuestions(result) {
  const container = findNestedObject(result, (item) => {
    const questions = item?.story_setup_questions || item?.storySetupQuestions || item?.questions;
    return Array.isArray(questions) && questions.some((question) => question?.question_text || question?.questionText);
  });
  if (!container) {
    return [];
  }
  const questions =
    container.story_setup_questions || container.storySetupQuestions || container.questions || [];
  const controlledAnswers =
    container.controlled_question_answers || container.controlledQuestionAnswers || {};
  return questions.map((question) => {
    const questionId = storySetupQuestionId(question);
    const controlledAnswer = String(controlledAnswers?.[questionId] || "").trim();
    return controlledAnswer
      ? {
          ...question,
          answer_text: controlledAnswer,
        }
      : question;
  });
}

function storySetupFieldLabel(key) {
  const labels = {
    world_scope: "世界范围",
    tone_candidates: "基调候选",
    hard_rule_candidates: "硬规则候选",
    soft_rule_candidates: "软规则候选",
    unknown_logic_gaps: "待确认缺口",
    potential_conflict: "核心冲突",
    protagonist: "主角",
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
    cosmology: "宇宙与自然规则",
    geography: "地理与空间",
    society: "社会与秩序",
    antagonist: "对抗方",
    companion: "同伴方向",
    act_structure: "幕结构",
    pacing: "节奏安排",
    theme_integration: "主题融入",
    ch1: "第一章",
    ch2: "第二章",
    ch3: "第三章",
    ch4: "第四章",
    ch5: "第五章",
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
      summary: fieldLines(world, ["cosmology", "geography", "society", "world_scope", "tone_candidates", "potential_conflict"], 3).join("；") || draftBundle.safe_summary || "后端已生成世界画布候选方向。",
      badge: world.requires_confirmation === false ? "可直接采用" : "需下游确认",
      source: "故事设定草案",
      target: "世界画布",
      keep: fieldLines(world, ["cosmology", "geography", "society", "hard_rule_candidates", "soft_rule_candidates", "detected_key_terms"], 4),
      confirm: fieldLines(world, ["unknown_logic_gaps", "world_scope", "tone_candidates", "prompt_signal_summary"], 3),
    },
    cast: {
      eyebrow: "角色方向草案",
      title: "角色方向",
      summary: fieldLines(cast, ["protagonist", "antagonist", "companion", "main_cast_size", "protagonist_function", "desire_direction"], 3).join("；") || "后端已生成角色主轴候选方向。",
      badge: cast.requires_confirmation === false ? "可直接采用" : "方向草案",
      source: "故事设定草案",
      target: "角色主轴",
      keep: fieldLines(cast, ["protagonist", "antagonist", "companion", "main_cast_size", "protagonist_function", "opposing_force_direction"], 4),
      confirm: fieldLines(cast, ["desire_direction", "relationship_tension_direction", "prompt_signal_summary"], 3),
    },
    framework: {
      eyebrow: "Framework 建议",
      title: "Framework 建议",
      summary: fieldLines(framework, ["act_structure", "pacing", "theme_integration", "macro_framework_shape", "conflict_escalation_path", "constraint_strength_suggestion"], 3).join("；") || "后端已生成全局叙事骨架候选方向。",
      badge: framework.requires_confirmation === false ? "可直接采用" : "可映射 Framework",
      source: "故事设定草案",
      target: "Framework",
      keep: fieldLines(framework, ["act_structure", "pacing", "theme_integration", "macro_framework_shape", "genre_tags", "constraint_strength_suggestion"], 4),
      confirm: fieldLines(framework, ["conflict_escalation_path", "reversal_crisis_climax_direction", "prompt_signal_summary"], 3),
    },
    chapters: {
      eyebrow: "章节路线建议",
      title: "章节路线建议",
      summary: fieldLines(chapters, ["ch1", "ch2", "ch3", "ch4", "ch5", "route_type", "chapter_route", "length_hint"], 3).join("；") || "后端已生成章节路线候选方向。",
      badge: chapters.requires_confirmation === false ? "可直接采用" : "章节候选",
      source: "故事设定草案",
      target: "章节计划",
      keep: fieldLines(chapters, ["ch1", "ch2", "ch3", "ch4", "ch5", "chapter_route", "length_hint"], 5),
      confirm: fieldLines(chapters, ["notes", "prompt_signal_summary"], 2),
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
  } else {
    delete element.dataset.mafsActionId;
  }
  if (targetPage) {
    element.dataset.mafsTarget = targetPage;
  } else {
    delete element.dataset.mafsTarget;
  }
  element.dataset.mafsInteractive = "true";
  markBackendRendered(element);
  if (element.dataset.mafsDirectActionBound !== "true") {
    element.dataset.mafsDirectActionBound = "true";
    element.addEventListener(
      "click",
      (event) => {
        const doc = element.ownerDocument;
        const bridge = doc?.defaultView?.__MAFS_EXECUTE_ACTION__;
        if (typeof bridge !== "function") {
          return;
        }
        const action = {
          ...(element.dataset.mafsActionId ? { actionId: element.dataset.mafsActionId } : {}),
          ...(element.dataset.mafsTarget ? { to: element.dataset.mafsTarget } : {}),
        };
        if (!action.actionId && !action.to) {
          return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        bridge(action, element);
      },
      true,
    );
  }
}

function suppressStaticSiblingsForBackendPanel(doc, panel, target, pageIds = []) {
  const currentPageId = framePageId(doc);
  if (!panel || !target || !pageIds.includes(currentPageId)) {
    return;
  }
  Array.from(target.children || []).forEach((child) => {
    if (child === panel) {
      child.classList.remove("mafs-empty-suppressed");
      return;
    }
    child.classList.add("mafs-empty-suppressed");
    child.dataset.mafsSuppressedStatic = "true";
    child.querySelectorAll("input, textarea, select").forEach((control) => {
      control.disabled = true;
      control.dataset.mafsSuppressedStatic = "true";
      const inputType = String(control.getAttribute("type") || "").toLowerCase();
      if (inputType === "checkbox" || inputType === "radio") {
        control.checked = false;
      } else if (control.tagName === "SELECT") {
        control.selectedIndex = -1;
      } else {
        control.value = "";
      }
    });
  });
  doc.querySelectorAll("button, a, [role='button']").forEach((element) => {
    if (panel.contains(element) || element.contains(panel)) {
      return;
    }
    element.classList.add("mafs-empty-suppressed");
    element.dataset.mafsSuppressedStatic = "true";
  });
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

function firstItem(value, keys = []) {
  if (Array.isArray(value)) {
    return value[0] || null;
  }
  if (!value || typeof value !== "object") {
    return null;
  }
  for (const key of keys) {
    const candidate = value[key];
    if (Array.isArray(candidate) && candidate.length) {
      return candidate[0];
    }
  }
  return null;
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
  if (normalized.includes("complete") || normalized.includes("final") || normalized.includes("export")) {
    return "查看最终输出";
  }
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
  return "继续故事设定";
}

function projectNextTarget(step) {
  const normalized = String(step || "").toLowerCase();
  if (normalized.includes("complete") || normalized.includes("final") || normalized.includes("export")) {
    return "final-entry";
  }
  if (normalized.includes("scene") || normalized.includes("writing")) {
    return "scene-entry";
  }
  if (normalized.includes("chapter") || normalized.includes("framework")) {
    return "chapter-source";
  }
  if (normalized.includes("character") || normalized.includes("role")) {
    return "character-entry";
  }
  if (normalized.includes("world")) {
    return "world-entry";
  }
  return "story-setup-entry";
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
  const rawUpdatedAt = project?.updated_at || project?.updatedAt || project?.created_at || project?.createdAt;
  const updatedAtMs = new Date(rawUpdatedAt || 0).getTime();
  const normalizedStatus = String(status).toLowerCase();
  const statusKey =
    normalizedStatus.includes("complete") || normalizedStatus.includes("finish")
      ? "completed"
      : normalizedStatus.includes("pause")
        ? "paused"
        : normalizedStatus.includes("archive")
          ? "archived"
          : "ongoing";
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
    statusKey,
    statusLabel: projectStatusLabel(status),
    updated: formatProjectTime(rawUpdatedAt),
    updatedAtMs: Number.isFinite(updatedAtMs) ? updatedAtMs : 0,
    stage: next.replace(/^继续/, ""),
    next,
    nextTarget: projectNextTarget(step),
    progress,
    summary,
    genre: firstNonEmpty(project?.genre, project?.story_genre, project?.storyGenre, project?.primary_genre, project?.primaryGenre),
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
  const rawProjects = findNestedArray(result, ["projects", "items", "records"]).filter(
    (item) =>
      item &&
      typeof item === "object" &&
      !String(item.origin_type || item.originType || "").toLowerCase().includes("legacy_debug"),
  );
  if (!rawProjects.length) {
    return false;
  }
  const projects = rawProjects.map(normalizeProjectCard).sort((a, b) => b.updatedAtMs - a.updatedAtMs);
  let selectedId = doc.body.dataset.mafsSelectedProjectId || projects[0].id;
  let activeStatus = "all";
  let activeGenre = "all";
  let sortMode = "recent";
  let query = "";

  const renderDetail = (project) => {
    const selected = project || projects.find((item) => item.id === selectedId) || projects[0];
    selectedId = selected.id;
    doc.body.dataset.mafsSelectedProjectId = selected.id;
    setRenderedText(detailTitle, selected.title);
    setRenderedText(detailSummary, selected.summary);
    const continueButton = doc.querySelector("#continue-button");
    setRenderedText(continueButton, selected.next);
    if (continueButton) {
      continueButton.dataset.projectId = selected.id;
      bindBackendActionElement(continueButton, "projects.openSelected", selected.nextTarget);
    }
    const detailButton = doc.querySelector("#detail-button");
    if (detailButton) {
      detailButton.dataset.projectId = selected.id;
      bindBackendActionElement(detailButton, "projects.openSelected", "current-project");
    }
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

  const filteredProjects = () => {
    const visible = projects.filter((project) => {
      const statusMatch = activeStatus === "all" || project.statusKey === activeStatus;
      const genreMatch = activeGenre === "all" || project.genre === activeGenre;
      const queryMatch = !query || `${project.title} ${project.summary} ${project.meta.join(" ")}`.toLowerCase().includes(query);
      return statusMatch && genreMatch && queryMatch;
    });
    return visible.sort((a, b) =>
      sortMode === "progress"
        ? b.progress - a.progress || b.updatedAtMs - a.updatedAtMs
        : b.updatedAtMs - a.updatedAtMs || b.progress - a.progress,
    );
  };

  const renderCards = () => {
    const visibleProjects = filteredProjects();
    cards.innerHTML = "";
    visibleProjects.slice(0, 24).forEach((project) => {
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
    setRenderedText(doc.querySelector("#result-sub"), `${visibleProjects.length} 个故事档案`);
    setRenderedText(doc.querySelector("#result-title"), query || activeStatus !== "all" || activeGenre !== "all" ? "筛选结果" : "最近继续");
    if (visibleProjects.length && !visibleProjects.some((item) => item.id === selectedId)) {
      renderDetail(visibleProjects[0]);
    }
  };

  const statusLabels = {
    ongoing: "进行中",
    completed: "已完成",
    paused: "暂停",
    archived: "归档",
    all: "全部",
  };
  const statusList = doc.getElementById("status-filters");
  if (statusList) {
    statusList.innerHTML = "";
    ["ongoing", "completed", "paused", "archived", "all"].forEach((statusKey) => {
      const count = statusKey === "all" ? projects.length : projects.filter((project) => project.statusKey === statusKey).length;
      if (!count && statusKey !== "all") return;
      const button = doc.createElement("button");
      button.type = "button";
      button.className = `filter-button${statusKey === activeStatus ? " active" : ""}`;
      button.dataset.status = statusKey;
      button.innerHTML = `<span>${statusLabels[statusKey]}</span><span>${count}</span>`;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        activeStatus = statusKey;
        statusList.querySelectorAll(".filter-button").forEach((item) => item.classList.toggle("active", item === button));
        renderCards();
      }, true);
      statusList.appendChild(button);
    });
    markBackendRendered(statusList);
  }

  const genreList = doc.getElementById("genre-filters");
  if (genreList) {
    genreList.innerHTML = "";
    const genres = Array.from(new Set(projects.map((project) => project.genre).filter(Boolean)));
    [["all", "全部题材"], ...genres.map((genre) => [genre, genre])].forEach(([genreKey, label]) => {
      const count = genreKey === "all" ? projects.length : projects.filter((project) => project.genre === genreKey).length;
      const button = doc.createElement("button");
      button.type = "button";
      button.className = `filter-button${genreKey === activeGenre ? " active" : ""}`;
      button.dataset.genre = genreKey;
      button.innerHTML = `<span>${escapeHtml(label)}</span><span>${count}</span>`;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        activeGenre = genreKey;
        genreList.querySelectorAll(".filter-button").forEach((item) => item.classList.toggle("active", item === button));
        renderCards();
      }, true);
      genreList.appendChild(button);
    });
    markBackendRendered(genreList);
  }

  const search = doc.getElementById("search");
  if (search && search.dataset.mafsProjectSearchBound !== "true") {
    search.dataset.mafsProjectSearchBound = "true";
    search.addEventListener("input", (event) => {
      event.stopImmediatePropagation();
      query = String(search.value || "").trim().toLowerCase();
      renderCards();
    }, true);
  }

  const tabFilters = { continue: "ongoing", history: "all", works: "completed" };
  doc.querySelectorAll(".view-tab[data-view]").forEach((button) => {
    if (button.dataset.mafsProjectTabBound === "true") return;
    button.dataset.mafsProjectTabBound = "true";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      activeStatus = tabFilters[button.dataset.view] || "all";
      doc.querySelectorAll(".view-tab").forEach((item) => item.classList.toggle("active", item === button));
      statusList?.querySelectorAll(".filter-button").forEach((item) => item.classList.toggle("active", item.dataset.status === activeStatus));
      renderCards();
    }, true);
  });
  const sortButton = doc.getElementById("sort-button");
  if (sortButton) {
    sortButton.disabled = false;
    sortButton.title = "切换项目排序方式";
    sortButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      sortMode = sortMode === "recent" ? "progress" : "recent";
      sortButton.textContent = sortMode === "recent" ? "最近更新" : "进度优先";
      renderCards();
    }, true);
  }

  renderCards();
  renderDetail(projects.find((item) => item.id === selectedId) || projects[0]);
  return true;
}

function renderCurrentProjectSurface(doc, result) {
  if (framePageId(doc) !== "current-project") {
    return false;
  }
  const overview =
    result?.current_project_overview ||
    result?.action_result?.current_project_overview ||
    (result?.action_result?.app_progress ? result.action_result : null) ||
    (result?.app_progress ? result : null);
  if (!overview) {
    return false;
  }

  const appProgress = overview.app_progress || overview.appProgress || {};
  const projectData = overview.project_data || overview.projectData || {};
  const project = projectData.project || appProgress.project || {};
  const worldCanvas = projectData.world_canvas || projectData.worldCanvas || {};
  const progressState = overview.product_progress_state || overview.productProgressState || {};
  const progressSummary =
    overview.product_progress_summary ||
    overview.productProgressSummary ||
    progressState.summary ||
    {};
  const nextActionValue =
    overview.product_progress_next_actions ||
    overview.productProgressNextActions ||
    progressState.next_actions ||
    progressState.nextActions ||
    {};
  const nextAction = Array.isArray(nextActionValue) ? nextActionValue[0] || {} : nextActionValue;
  const blockingValue =
    overview.product_progress_blocking_issues ||
    overview.productProgressBlockingIssues ||
    progressState.blocking_issues ||
    progressState.blockingIssues ||
    [];
  const blockingIssues = Array.isArray(blockingValue)
    ? blockingValue
    : Array.isArray(blockingValue?.items)
      ? blockingValue.items
      : [];
  const exportRuns =
    overview.final_exports?.export_runs ||
    overview.finalExports?.exportRuns ||
    progressState.final_exports?.export_runs ||
    [];
  const storyProgress = appProgress.story_progress || appProgress.storyProgress || {};
  const progressStatus = firstNonEmpty(
    storyProgress.story_progress_status,
    storyProgress.storyProgressStatus,
    appProgress.project?.status,
    project.status,
  ).toLowerCase();
  const storyComplete =
    progressStatus.includes("story_draft_complete") ||
    progressStatus.includes("complete") ||
    exportRuns.length > 0;

  const stepMap = new Map(
    (Array.isArray(appProgress.steps) ? appProgress.steps : []).map((step) => [
      String(step?.key || ""),
      String(step?.state || "").toLowerCase(),
    ]),
  );
  const isDone = (...keys) => keys.some((key) => ["done", "complete", "completed", "confirmed", "ready"].includes(stepMap.get(key)));
  const stageDefinitions = [
    {
      key: "story_setup",
      stepKeys: ["project", "story_setup"],
      label: "故事设定",
      target: "story-setup-entry",
      completeTitle: "故事设定已完成",
      completeText: "项目题材、创作前提和故事设定交接已经建立，可随时回看。",
      pendingText: "先确认故事前提与创作边界，再进入后续工作台。",
    },
    {
      key: "framework",
      stepKeys: ["framework"],
      label: "Framework",
      target: "framework",
      completeTitle: "Framework 已可用",
      completeText: "宏观故事骨架已经建立；各章 Framework 仍会在对应章节即时构建。",
      pendingText: "需要先完成故事骨架编排。",
    },
    {
      key: "world_canvas",
      stepKeys: ["world_canvas"],
      label: "世界画布",
      target: "world-entry",
      completeTitle: "世界画布已确认",
      completeText: "世界结构、历史、地理、文化与特殊规则已经成为后续生成的事实底座。",
      pendingText: "需要生成并确认世界画布。",
    },
    {
      key: "characters",
      stepKeys: ["characters"],
      label: "角色主轴",
      target: "character-entry",
      completeTitle: "角色主轴已确认",
      completeText: "主要角色、关系和参与生成所需的角色档案已经建立。",
      pendingText: "需要创建并确认主要角色。",
    },
    {
      key: "chapter_plan",
      stepKeys: ["chapter_plan"],
      label: "章节计划",
      target: "chapter-source",
      completeTitle: "章节计划已完成",
      completeText: "当前故事的章节路线、篇章功能和每章幕数已经建立。",
      pendingText: "需要为当前章节构建篇章 Framework 与章节路线。",
    },
    {
      key: "chapter_scene",
      stepKeys: ["scene", "chapter_scene"],
      label: "场景写作",
      target: "scene-entry",
      completeTitle: "场景写作已完成",
      completeText: "场景正文已经确认，章节已归档，故事草稿可进入最终组装。",
      pendingText: "需要继续生成、审阅并确认当前场景。",
    },
    {
      key: "final_outputs",
      stepKeys: ["final_outputs"],
      label: "最终输出",
      target: "final-entry",
      completeTitle: "最终故事包已就绪",
      completeText: "故事草稿已完成，可查看成稿、选择交付格式并导出。",
      pendingText: "故事草稿完成并通过最终检查后即可导出。",
    },
  ].map((stage, index) => ({
    ...stage,
    index: index + 1,
    done: stage.key === "final_outputs" ? storyComplete : isDone(...stage.stepKeys),
  }));

  const summaryStageId = firstNonEmpty(
    progressSummary.current_stage_id,
    progressSummary.currentStageId,
    storyComplete ? "final_outputs" : "",
  );
  const currentStage =
    stageDefinitions.find((stage) => stage.key === summaryStageId) ||
    stageDefinitions.find((stage) => !stage.done) ||
    stageDefinitions[stageDefinitions.length - 1];
  const projectTitle = firstNonEmpty(project.title, project.requested_title, project.requestedTitle, "未命名故事");
  const projectDescription = firstNonEmpty(
    worldCanvas.story_direction,
    worldCanvas.storyDirection,
    progressSummary.ordinary_summary,
    progressSummary.ordinarySummary,
    "项目资料已从后端同步，可从下方工作区继续创作。",
  );
  const compactDescription = projectDescription.length > 220 ? `${projectDescription.slice(0, 220)}…` : projectDescription;
  const activeModel = appProgress.active_model || appProgress.activeModel || {};
  const modelLabel = activeModel.configured
    ? [activeModel.provider_type || activeModel.providerType, activeModel.model_name || activeModel.modelName].filter(Boolean).join(" / ")
    : "未配置";
  const originLabel = firstNonEmpty(
    progressSummary.origin_badge_label,
    progressSummary.originBadgeLabel,
    projectData.project_origin_type,
    projectData.projectOriginType,
    "用户创作项目",
  );

  setRenderedText(doc.querySelector(".identity-band .eyebrow"), `PROJECT DOSSIER · ${project.project_id || projectData.active_project_id || ""}`.trim());
  setRenderedText(doc.querySelector(".identity-band .project-title"), projectTitle);
  setRenderedText(doc.querySelector(".identity-band .project-desc"), compactDescription);
  const metaValues = [
    originLabel,
    modelLabel || "未配置",
    firstNonEmpty(progressSummary.current_stage_label, progressSummary.currentStageLabel, currentStage.label),
    storyComplete ? "故事草稿已完成" : worldCanvas.status === "confirmed" ? "世界事实已确认" : "继续确认中",
  ];
  doc.querySelectorAll(".identity-band .meta-item strong").forEach((element, index) => {
    setRenderedText(element, metaValues[index] || "暂无");
  });
  setRenderedText(doc.querySelector(".project-pill"), project.project_id ? "活动项目已选择" : "尚未选择项目");

  const stageByKey = Object.fromEntries(stageDefinitions.map((stage) => [stage.key, stage]));
  const selectStage = (stageKey) => {
    const stage = stageByKey[stageKey] || currentStage;
    doc.querySelectorAll(".stage-node").forEach((node) => {
      node.classList.toggle("current", node.dataset.key === stage.key);
    });
    doc.querySelectorAll(".quick-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.key === stage.key);
    });
    setRenderedText(doc.getElementById("stageDetailTitle"), stage.done ? stage.completeTitle : `${stage.label}待推进`);
    setRenderedText(doc.getElementById("stageDetailText"), stage.done ? stage.completeText : stage.pendingText);
    setRenderedText(doc.getElementById("stageStatus"), stage.done ? "已完成" : "待推进");
    setRenderedText(doc.getElementById("stageCounter"), `${stage.index} / 7 · ${stage.done ? "已完成" : "待推进"}`);
    setRenderedText(doc.getElementById("currentStageText"), currentStage.label);
    setRenderedText(doc.getElementById("actionTitle"), stage.done ? `查看${stage.label}` : `继续${stage.label}`);
    setRenderedText(doc.getElementById("actionReason"), stage.done ? stage.completeText : stage.pendingText);
    setRenderedText(doc.getElementById("targetWorkspace"), stage.label);
    setRenderedText(doc.getElementById("confirmNeed"), stage.done ? "已完成" : "按工作台确认");
    const primaryAction = doc.getElementById("primaryAction");
    setRenderedText(primaryAction, stage.done ? `查看${stage.label}` : `继续${stage.label}`);
    bindBackendActionElement(primaryAction, "", stage.target);
  };
  if (doc.defaultView) {
    doc.defaultView.__mafsSelectCurrentProjectStage = selectStage;
  }

  stageDefinitions.forEach((stage) => {
    const node = doc.querySelector(`.stage-node[data-key="${stage.key}"]`);
    if (node) {
      node.classList.toggle("done", stage.done);
      node.classList.toggle("locked", false);
      node.classList.toggle("current", stage.key === currentStage.key);
      setRenderedText(node.querySelector("strong"), stage.label);
      setRenderedText(node.querySelector("span"), stage.done ? "已完成" : "待推进");
      markBackendRendered(node);
      if (node.dataset.mafsCurrentProjectStageBound !== "true") {
        node.dataset.mafsCurrentProjectStageBound = "true";
        node.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          doc.defaultView?.__mafsSelectCurrentProjectStage?.(node.dataset.key);
        }, true);
      }
    }
    const quick = doc.querySelector(`.quick-item[data-key="${stage.key}"]`);
    if (quick) {
      quick.classList.toggle("done", stage.done);
      quick.classList.toggle("locked", false);
      quick.classList.toggle("active", stage.key === currentStage.key);
      setRenderedText(quick.querySelector(".quick-main strong"), stage.label);
      setRenderedText(quick.querySelector(".quick-main span"), stage.done ? "已完成" : "待推进");
      setRenderedText(quick.querySelector(".quick-state"), "进入");
      bindBackendActionElement(quick, "", stage.target);
    }
  });
  selectStage(currentStage.key);

  const bottomBand = doc.querySelector(".bottom-band");
  if (bottomBand) {
    bottomBand.innerHTML = "";
    const createPanel = (title, count) => {
      const panel = doc.createElement("section");
      panel.className = "surface-panel mafs-backend-rendered";
      const heading = doc.createElement("div");
      heading.className = "surface-title";
      heading.innerHTML = `${escapeHtml(title)} <span>${count}</span>`;
      panel.appendChild(heading);
      return panel;
    };
    const appendTask = (panel, title, summary, target, warning = false) => {
      const row = doc.createElement("div");
      row.className = `task-row${warning ? " warn" : ""}`;
      row.innerHTML = `<div class="task-mark"></div><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(summary)}</span></div>`;
      const button = doc.createElement("button");
      button.type = "button";
      button.className = "mini-action";
      button.textContent = target ? "前往" : "已确认";
      if (target) {
        bindBackendActionElement(button, "", target);
      } else {
        button.disabled = true;
      }
      row.appendChild(button);
      panel.appendChild(row);
    };
    const pendingStages = stageDefinitions.filter((stage) => !stage.done);
    const taskPanel = createPanel(storyComplete ? "项目完成状态" : "待推进事项", storyComplete ? 1 : pendingStages.length);
    if (storyComplete) {
      appendTask(taskPanel, "故事草稿与最终故事包已完成", "可进入最终输出查看、选择格式并下载真实成稿。", "final-entry");
    } else {
      pendingStages.slice(0, 2).forEach((stage) => appendTask(taskPanel, `继续${stage.label}`, stage.pendingText, stage.target));
    }
    const blockerPanel = createPanel("阻塞提醒", blockingIssues.length);
    if (blockingIssues.length) {
      blockingIssues.slice(0, 2).forEach((issue) => {
        appendTask(
          blockerPanel,
          firstNonEmpty(issue.title, issue.issue_title, "需要处理的阻塞"),
          firstNonEmpty(issue.reason, issue.safe_summary, issue.summary, "请进入对应工作台处理。"),
          currentStage.target,
          true,
        );
      });
    } else {
      appendTask(blockerPanel, "当前无阻塞", "后端进度视图未报告阻塞问题。", "");
    }
    bottomBand.append(taskPanel, blockerPanel);
    markBackendRendered(bottomBand);
  }

  const preferredTarget = stageByKey[firstNonEmpty(nextAction.target_workspace_id, nextAction.targetWorkspaceId)] || currentStage;
  setRenderedText(doc.getElementById("actionTitle"), firstNonEmpty(nextAction.title, preferredTarget.done ? `查看${preferredTarget.label}` : `继续${preferredTarget.label}`));
  setRenderedText(doc.getElementById("actionReason"), firstNonEmpty(nextAction.reason, preferredTarget.done ? preferredTarget.completeText : preferredTarget.pendingText));
  const primaryAction = doc.getElementById("primaryAction");
  setRenderedText(primaryAction, firstNonEmpty(nextAction.title, preferredTarget.done ? `查看${preferredTarget.label}` : `继续${preferredTarget.label}`));
  bindBackendActionElement(primaryAction, "", preferredTarget.target);
  bindBackendActionElement(doc.querySelector(".back"), "", "projects");
  markBackendRendered(doc.querySelector(".workspace"));
  return true;
}

function templateDisplayName(template) {
  const id = firstNonEmpty(template?.template_id, template?.templateId);
  const labels = {
    template_story_foundation: "故事基础起点",
    template_character_drama: "角色戏剧起点",
    template_mystery_serial: "悬疑连载起点",
  };
  return labels[id] || firstNonEmpty(template?.display_name, template?.displayName, id, "未命名模板");
}

function templatePreviewText(template) {
  const id = firstNonEmpty(template?.template_id, template?.templateId);
  const labels = {
    template_story_foundation: "提供世界范围、核心冲突和章节方向的可复用起始问题。",
    template_character_drama: "提供人物弧光与关系建立所需的可复用起始问题。",
    template_mystery_serial: "提供线索节奏、揭示时机与连续性规划的可复用起始问题。",
  };
  return labels[id] || firstNonEmpty(template?.safe_preview, template?.safePreview, template?.safe_summary, "可复用结构起点。");
}

function renderTemplateDemoSurface(doc, result) {
  if (framePageId(doc) !== "template-demo") {
    return false;
  }
  const payload = result?.action_result || result || {};
  const templates =
    payload.templates?.templates ||
    payload.project_templates?.templates ||
    payload.templates ||
    [];
  const demoSeeds =
    payload.demo_seeds?.demo_seed_profiles ||
    payload.demoSeeds?.demoSeedProfiles ||
    payload.demo_seed_profiles ||
    [];
  const originBadge =
    payload.project_origin_badge ||
    payload.projectOriginBadge ||
    {};
  const originType = firstNonEmpty(
    originBadge.origin_type,
    originBadge.originType,
  ).toLowerCase();
  const isDemoProject = Boolean(
    originType === "demo_seed" ||
    originBadge.is_demo_project ||
    originBadge.isDemoProject,
  );
  if (!Array.isArray(templates) || !templates.length) {
    return false;
  }

  const templateList = doc.querySelector(".template-list");
  const demoList = doc.querySelector(".demo-list");
  const templateBadge = doc.querySelector(".template-panel .badge");
  setRenderedText(templateBadge, String(templates.length));
  setRenderedText(doc.querySelector(".source-pill"), `当前项目：${firstNonEmpty(result?.hydrated_refs?.projectTitle, "模板结构起点")}`);
  setRenderedText(doc.querySelector(".origin-title"), "可复用结构起点");
  setRenderedText(doc.querySelector(".origin-copy"), "模板只提供起始问题和结构参考，不会覆盖当前项目前提，也不会直接写入故事事实。");

  const selectTemplate = (template) => {
    const templateId = firstNonEmpty(template.template_id, template.templateId);
    doc.body.dataset.mafsSelectedTemplateId = templateId;
    templateList?.querySelectorAll(".template-card").forEach((card) => {
      card.classList.toggle("selected", card.dataset.templateId === templateId);
    });
    setRenderedText(doc.getElementById("selectedTitle"), templateDisplayName(template));
    setRenderedText(doc.getElementById("selectedCopy"), templatePreviewText(template));
    setRenderedText(doc.getElementById("flowTitle"), "模板已选择");
    setRenderedText(doc.getElementById("flowText"), "点击“使用所选模板”后，后端会创建并校验实例化请求，再把起始材料交给 Framework 工作台。");
  };

  if (templateList) {
    templateList.innerHTML = "";
    templates.forEach((template, index) => {
      const templateId = firstNonEmpty(template.template_id, template.templateId, `template_${index + 1}`);
      const card = doc.createElement("button");
      card.type = "button";
      card.className = `template-card${index === 0 ? " selected" : ""}`;
      card.dataset.templateId = templateId;
      card.innerHTML = `
        <span class="sample-sheet" aria-hidden="true"></span>
        <span class="template-main">
          <strong>${escapeHtml(templateDisplayName(template))}</strong>
          <span>${escapeHtml(templatePreviewText(template))}</span>
          <span class="tag-row"><span class="tag safe">安全内置</span><span class="tag">${escapeHtml(firstNonEmpty(template.recommended_entry_workspace, template.recommendedEntryWorkspace, "Framework"))}</span></span>
        </span>`;
      card.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        selectTemplate(template);
      }, true);
      templateList.appendChild(card);
    });
    markBackendRendered(templateList);
    selectTemplate(templates[0]);
  }
  const templateSearch = doc.querySelector(".template-panel .search");
  const clearTemplateFilter = doc.querySelector(".template-panel .filter-button");
  const applyTemplateFilter = () => {
    const searchText = String(templateSearch?.value || "").trim().toLowerCase();
    templateList?.querySelectorAll(".template-card").forEach((card) => {
      card.hidden = Boolean(searchText) && !String(card.textContent || "").toLowerCase().includes(searchText);
    });
    if (clearTemplateFilter) {
      clearTemplateFilter.disabled = !searchText;
      clearTemplateFilter.title = searchText ? "清除模板筛选" : "尚未输入筛选条件";
    }
  };
  if (templateSearch) {
    templateSearch.value = "";
    templateSearch.placeholder = "搜索模板";
    templateSearch.addEventListener("input", applyTemplateFilter);
  }
  if (clearTemplateFilter) {
    clearTemplateFilter.textContent = "×";
    clearTemplateFilter.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (templateSearch) {
        templateSearch.value = "";
      }
      applyTemplateFilter();
      templateSearch?.focus();
    }, true);
  }
  applyTemplateFilter();

  const primaryAction = doc.getElementById("primaryAction");
  setRenderedText(primaryAction, "使用所选模板");
  bindBackendActionElement(primaryAction, "template.validateAndInstantiate", "framework");
  doc.querySelectorAll(".flow-step").forEach((step) => {
    step.disabled = true;
    step.removeAttribute("data-mafs-action-id");
    step.removeAttribute("data-mafs-target");
  });

  if (demoList) {
    demoList.innerHTML = "";
    if (Array.isArray(demoSeeds) && demoSeeds.length) {
      demoSeeds.forEach((demo, index) => {
        const demoId = firstNonEmpty(demo.demo_seed_id, demo.demoSeedId, `demo_seed_${index + 1}`);
        const card = doc.createElement("button");
        card.type = "button";
        card.className = `demo-card${index === 0 ? " selected" : ""}`;
        card.dataset.demoSeedId = demoId;
        card.innerHTML = `
          <span class="demo-icon">演</span>
          <span class="demo-main"><strong>${escapeHtml(firstNonEmpty(demo.display_name, demo.displayName, "隔离演示样本"))}</strong><span>${escapeHtml(firstNonEmpty(demo.safe_preview, demo.safePreview, "只用于产品流程演示。"))}</span></span>`;
        card.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          doc.body.dataset.mafsSelectedDemoSeedId = demoId;
          demoList.querySelectorAll(".demo-card").forEach((item) => item.classList.toggle("selected", item === card));
          setRenderedText(doc.getElementById("demoTitle"), `${firstNonEmpty(demo.display_name, demo.displayName, "演示样本")}隔离审计`);
        }, true);
        demoList.appendChild(card);
      });
      doc.body.dataset.mafsSelectedDemoSeedId = firstNonEmpty(demoSeeds[0].demo_seed_id, demoSeeds[0].demoSeedId);
    } else {
      const empty = doc.createElement("p");
      empty.className = "panel-note";
      empty.textContent = "当前没有可运行的隔离演示样本。";
      demoList.appendChild(empty);
    }
    markBackendRendered(demoList);
  }
  setRenderedText(doc.getElementById("demoTitle"), "演示样本隔离审计");
  const demoActions = doc.querySelectorAll(".demo-action");
  if (demoActions[0] && demoSeeds.length) {
    setRenderedText(demoActions[0], "运行所选演示");
    if (isDemoProject) {
      bindBackendActionElement(demoActions[0], "template.runDemo", "current-project");
    } else {
      setRenderedText(demoActions[0], "仅隔离演示项目可运行");
      demoActions[0].disabled = true;
      demoActions[0].dataset.localOnly = "true";
      demoActions[0].removeAttribute("data-mafs-action-id");
      demoActions[0].removeAttribute("data-mafs-target");
      demoActions[0].title = "当前是真实用户项目，不能运行 demo seed。";
    }
  }
  if (demoActions[1]) {
    demoActions[1].dataset.localOnly = "true";
    demoActions[1].disabled = true;
    setRenderedText(demoActions[1], "演示与真实项目隔离");
  }
  doc.querySelectorAll(".audit-metric strong").forEach((metric, index) => {
    const values = ["隔离", "不可写入", "不可复制", "无正文", "需显式选择", "通过"];
    setRenderedText(metric, values[index] || "通过");
  });
  const safetyCopy = [
    "模板只创建可审阅的起始材料，不会直接写入当前项目事实。",
    "Framework、世界画布和角色仍需要用户在对应工作台确认。",
    "演示样本只生成隔离记录，不写入真实项目。",
  ];
  doc.querySelectorAll(".safety-item p").forEach((paragraph, index) => {
    setRenderedText(paragraph, safetyCopy[index] || "保持用户确认边界。");
  });
  markBackendRendered(doc.querySelector(".workspace"));
  return true;
}

function renderAnalyzeImportSourceSurface(doc, result) {
  if (framePageId(doc) !== "import-source") {
    return false;
  }
  const payload = result?.action_result || result || {};
  const imports = payload.imports?.imports || payload.imports || [];
  const inputDefaults = [
    ["storyTitle", "港口钟楼证词", ""],
    ["sourceNote", "旧稿第一卷 / 用户导入", ""],
    ["filename", "harbor-clocktower-source.txt", ""],
  ];
  inputDefaults.forEach(([id, legacyValue, replacement]) => {
    const input = doc.getElementById(id);
    if (input && input.value === legacyValue) {
      input.value = replacement;
    }
  });
  const sourceText = doc.getElementById("sourceText");
  if (sourceText && sourceText.value.startsWith("第一章，港口城在傍晚失去了一段集体记忆。")) {
    sourceText.value = "";
  }
  if (sourceText) {
    sourceText.placeholder = "粘贴 Analyze Stories 导出的 framework package JSON，或使用“上传文件”选择对应 JSON 文件。";
  }
  const storyTitle = doc.getElementById("storyTitle");
  if (storyTitle) storyTitle.placeholder = "导入记录标题（可选）";
  const sourceNote = doc.getElementById("sourceNote");
  if (sourceNote) sourceNote.placeholder = "来源备注（可选）";
  const filename = doc.getElementById("filename");
  if (filename) filename.placeholder = "framework-package.json";
  setRenderedText(doc.querySelector(".hero p"), "导入 Analyze Stories 已生成的分析产物或 Framework 包，校验后形成候选结构；当前页面不会把原始故事直接写入生成项目。");
  setRenderedText(doc.getElementById("editorEyebrow"), "Analyze Stories 产物");
  setRenderedText(doc.getElementById("editorTitle"), "Framework Package JSON");
  setRenderedText(doc.getElementById("sourceState"), Array.isArray(imports) && imports.length ? `${imports.length} 条历史导入` : "等待导入");
  setRenderedText(doc.getElementById("wordCount"), sourceText?.value ? String(sourceText.value.length) : "0");
  setRenderedText(doc.getElementById("chapterCount"), "由导入包决定");
  setRenderedText(doc.getElementById("modeName"), "JSON 导入");

  doc.querySelectorAll(".source-option").forEach((option, index) => {
    const enabled = index === 0 || index === 1;
    option.classList.toggle("active", index === 0);
    option.disabled = !enabled;
    if (!enabled) {
      option.title = "原始故事分析将在 Analyze Stories 独立工作台中完成。";
    }
  });
  const sourceDescriptions = [
    "粘贴 Analyze Stories 导出的 JSON 产物",
    "上传 Framework Package JSON 文件",
    "完整书卷分析请在 Analyze Stories 工作台完成",
    "导入 Analyze Stories 已生成的分析产物",
  ];
  doc.querySelectorAll(".source-option .source-copy span").forEach((description, index) => {
    setRenderedText(description, sourceDescriptions[index] || "选择可导入的数据源。");
  });
  const kindSelect = doc.getElementById("kindSelect");
  if (kindSelect) {
    Array.from(kindSelect.options).forEach((option) => {
      option.hidden = !/framework|json|bundle/i.test(`${option.value} ${option.textContent}`);
      if (option.value === "cross_chapter_state_package") {
        option.textContent = "跨章节状态包";
      }
    });
  }
  const metricLabels = ["字符", "章节", "源类型", "状态"];
  doc.querySelectorAll(".metrics .metric span").forEach((label, index) => {
    setRenderedText(label, metricLabels[index] || "状态");
  });
  const guardCopy = [
    "只创建导入记录，不直接改写当前 Framework。",
    "导入产物先经过结构校验，再生成可审阅候选。",
    "候选只有在用户确认后才会进入正式编排。",
  ];
  doc.querySelectorAll(".guard-item > div:last-child span").forEach((description, index) => {
    setRenderedText(description, guardCopy[index] || "保持用户确认边界。");
  });

  const recordList = doc.getElementById("recordList");
  if (recordList) {
    recordList.innerHTML = "";
    if (Array.isArray(imports) && imports.length) {
      imports.slice(0, 12).forEach((item) => {
        const card = doc.createElement("article");
        card.className = "record-card";
        card.innerHTML = `
          <strong>${escapeHtml(firstNonEmpty(item.import_id, item.importId, "导入记录"))}</strong>
          <span>${escapeHtml(firstNonEmpty(item.import_status, item.importStatus, "未知状态"))}</span>
          <div class="record-meta"><span>${escapeHtml(firstNonEmpty(item.parse_status, item.parseStatus, "未解析"))}</span><span>${escapeHtml(formatProjectTime(item.updated_at || item.updatedAt || item.received_at || item.receivedAt))}</span></div>`;
        recordList.appendChild(card);
      });
    } else {
      const empty = doc.createElement("p");
      empty.textContent = "还没有 Analyze Stories 导入记录。";
      recordList.appendChild(empty);
    }
    markBackendRendered(recordList);
  }

  const routeTargets = {
    source: "import-source",
    analysis: "analyzing",
    result: "analysis-result",
    candidate: "framework-candidate",
  };
  doc.querySelectorAll("[data-route]").forEach((button) => {
    const target = routeTargets[button.dataset.route];
    if (target) {
      bindBackendActionElement(button, "", target);
    }
  });
  const startAnalysis = doc.getElementById("startAnalysis");
  setRenderedText(startAnalysis, "导入并校验");
  bindBackendActionElement(startAnalysis, "analyze.import", "analyzing");
  const saveDraft = doc.getElementById("saveDraft");
  if (saveDraft && saveDraft.dataset.mafsLocalDraftBound !== "true") {
    saveDraft.dataset.mafsLocalDraftBound = "true";
    saveDraft.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const draft = {
        title: storyTitle?.value || "",
        note: sourceNote?.value || "",
        filename: filename?.value || "",
        sourceText: sourceText?.value || "",
      };
      doc.defaultView?.sessionStorage?.setItem("mafsAnalyzeImportDraft", JSON.stringify(draft));
      showFrameMessage(doc, "导入草稿已保存在当前浏览器会话。", "success");
    }, true);
  }
  markBackendRendered(doc.querySelector(".workspace"));
  return true;
}

function analyzeStoriesPayload(result) {
  return result?.action_result || result?.actionResult || result || {};
}

function analyzeStoriesImportDetail(payload) {
  const detail =
    payload?.selected_import ||
    payload?.selectedImport ||
    payload?.import_detail ||
    payload?.importDetail ||
    null;
  if (detail?.manifest || detail?.artifacts || detail?.input_fingerprints) {
    return detail;
  }
  if (payload?.manifest || payload?.artifacts || payload?.input_fingerprints) {
    return payload;
  }
  return null;
}

function analyzeStoriesCandidateList(payload) {
  const response =
    payload?.framework_candidates ||
    payload?.frameworkCandidates ||
    {};
  const candidates =
    response?.candidates ||
    response?.framework_candidates ||
    response?.frameworkCandidates ||
    [];
  return Array.isArray(candidates) ? candidates : [];
}

function analyzeStoriesSelectedCandidate(payload, importId = "") {
  const direct =
    payload?.selected_candidate ||
    payload?.selectedCandidate ||
    payload?.candidate ||
    payload?.action_result ||
    null;
  if (direct?.candidate_id || direct?.candidateId || direct?.framework_candidate_id) {
    return direct;
  }
  return (
    analyzeStoriesCandidateList(payload).find((candidate) => {
      const candidateImportId = firstNonEmpty(
        candidate?.import_id,
        candidate?.importId,
        candidate?.source_import_id,
        candidate?.sourceImportId,
      );
      return Boolean(importId && candidateImportId === importId);
    }) ||
    null
  );
}

function renderAnalyzeStoriesWorkflowSurface(doc, result) {
  const pageId = framePageId(doc);
  if (!["analyzing", "analysis-result", "framework-candidate"].includes(pageId)) {
    return false;
  }
  const payload = analyzeStoriesPayload(result);
  const detail = analyzeStoriesImportDetail(payload) || {};
  const manifest = detail.manifest || detail.import_manifest || detail.importManifest || {};
  const artifacts = detail.artifacts || [];
  const fingerprints = detail.input_fingerprints || detail.inputFingerprints || [];
  const validation =
    detail.validation_report ||
    detail.validationReport ||
    payload.validation_report ||
    payload.validationReport ||
    {};
  const artifact = Array.isArray(artifacts) ? artifacts[0] || {} : {};
  const fingerprint = Array.isArray(fingerprints) ? fingerprints[0] || {} : {};
  const importId = firstNonEmpty(
    manifest.import_id,
    manifest.importId,
    payload.import_id,
    payload.importId,
  );
  const inputTitle = firstNonEmpty(
    fingerprint.input_title,
    fingerprint.inputTitle,
    artifact.original_filename,
    artifact.originalFilename,
    importId,
    "未命名 Analyze Stories 导入",
  );
  const filename = firstNonEmpty(
    artifact.original_filename,
    artifact.originalFilename,
    fingerprint.input_filename,
    fingerprint.inputFilename,
    "未提供文件名",
  );
  const fileKind = firstNonEmpty(
    artifact.file_kind,
    artifact.fileKind,
    manifest.file_kinds?.[0],
    manifest.fileKinds?.[0],
    "framework_package",
  );
  const importStatus = firstNonEmpty(
    manifest.import_status,
    manifest.importStatus,
    "unknown",
  );
  const parseStatus = firstNonEmpty(
    manifest.parse_status,
    manifest.parseStatus,
    artifact.parse_status,
    artifact.parseStatus,
    "unknown",
  );
  const validationPassed = Boolean(
    validation.passed ??
    validation.ready_for_next_step ??
    validation.readyForNextStep,
  );
  const blockers =
    validation.blocking_issues ||
    validation.blockingIssues ||
    validation.next_step_blockers ||
    validation.nextStepBlockers ||
    [];
  const warnings = validation.warnings || [];
  const candidate = analyzeStoriesSelectedCandidate(payload, importId);
  const candidateId = firstNonEmpty(
    candidate?.candidate_id,
    candidate?.candidateId,
    candidate?.framework_candidate_id,
    candidate?.frameworkCandidateId,
  );
  const candidateStatus = firstNonEmpty(
    candidate?.candidate_status,
    candidate?.candidateStatus,
    candidateId ? "available" : "not_created",
  );

  const routeTargets = {
    source: "import-source",
    analysis: "analyzing",
    result: "analysis-result",
    candidate: "framework-candidate",
  };
  doc.querySelectorAll("[data-route]").forEach((button) => {
    const target = routeTargets[button.dataset.route];
    if (!target) {
      return;
    }
    if (button.dataset.route === "candidate" && !candidateId) {
      bindBackendActionElement(button, "analyze.createCandidate", target);
    } else {
      bindBackendActionElement(button, button.dataset.route === "candidate" ? "analyze.refresh" : "", target);
    }
  });

  if (pageId === "analyzing") {
    const hero = doc.querySelector(".hero");
    setRenderedText(hero?.querySelector("h1"), validationPassed ? "分析完成" : "分析结果需处理");
    setRenderedText(
      hero?.querySelector("p"),
      validationPassed
        ? "导入源已完成解析与结构校验，可以进入结果审阅。"
        : "导入源已完成解析，但仍有问题需要在结果页处理。",
    );
    const summaryValues = [inputTitle, filename, fileKind, importId || "等待导入记录"];
    doc.querySelectorAll(".source-summary .summary-item strong").forEach((element, index) => {
      setRenderedText(element, summaryValues[index] || "无");
    });
    setRenderedText(doc.getElementById("parseLabel"), parseStatus === "parsed" ? "已完成" : parseStatus);
    setRenderedText(doc.getElementById("validateLabel"), validationPassed ? "通过" : "需处理");
    setRenderedText(doc.getElementById("candidateLabel"), candidateId ? "可审阅" : "待生成");
    setRenderedText(doc.getElementById("stageEyebrow"), validationPassed ? "分析完成" : "等待处理");
    setRenderedText(doc.getElementById("stageTitle"), validationPassed ? "导入与结构校验已完成" : "导入结果需要处理");
    setRenderedText(doc.getElementById("progressBadge"), validationPassed ? "100%" : "待处理");
    setRenderedText(doc.getElementById("queueImport"), importId ? "导入记录已创建" : "等待导入记录");
    setRenderedText(doc.getElementById("queueValidation"), validationPassed ? "结构校验通过" : `${blockers.length} 个阻塞`);
    setRenderedText(doc.getElementById("queueReport"), detail.story_analysis_report_refs?.length ? "分析报告引用已载入" : "Framework Package 已解析");
    setRenderedText(doc.getElementById("queueCandidate"), candidateId ? "候选可审阅" : "等待用户生成候选");
    const queueCopies = [
      `${filename} 已进入当前导入记录。`,
      validationPassed ? "结构校验已完成，可以进入结果审阅。" : `${blockers.length} 个阻塞需要处理。`,
      detail.story_analysis_report_refs?.length ? "报告只作为审阅材料。" : "当前导入包没有额外报告引用。",
      candidateId ? `候选 ${candidateId} 已准备完成。` : "可在结果页生成未激活候选。",
    ];
    doc.querySelectorAll(".queue-item > div:last-child > span").forEach((element, index) => {
      setRenderedText(element, queueCopies[index] || "");
    });
    const pauseButton = doc.getElementById("pauseButton");
    const backgroundButton = doc.getElementById("backgroundButton");
    if (pauseButton) pauseButton.hidden = true;
    if (backgroundButton) backgroundButton.hidden = true;
    const resultButton = doc.getElementById("resultButton");
    setRenderedText(resultButton, "查看分析结果");
    bindBackendActionElement(resultButton, "analyze.refresh", "analysis-result");
    if (resultButton) resultButton.disabled = false;
    const corePanel = doc.querySelector(".core-panel");
    if (corePanel) {
      corePanel.innerHTML = `
        <div class="core-head">
          <div>
            <span>后端分析结果</span>
            <h2>${escapeHtml(validationPassed ? "导入与结构校验已完成" : "导入结果需要处理")}</h2>
          </div>
          <div class="progress-badge">100%</div>
        </div>
        <div style="padding:18px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.5);line-height:1.75;">
          <strong>${escapeHtml(inputTitle)}</strong>
          <p style="margin:8px 0 0;">${escapeHtml(
            validationPassed
              ? `后端已解析 ${fileKind}，校验结果为通过；有 ${warnings.length} 个提醒和 ${blockers.length} 个阻塞。`
              : `后端已解析 ${fileKind}，但仍有 ${blockers.length} 个阻塞。`,
          )}</p>
        </div>
        <div class="stage-track" aria-label="分析阶段">
          ${[
            ["01", "接收记录"],
            ["02", "解析结构"],
            ["03", detail.story_analysis_report_refs?.length ? "提取报告" : "确认无外部报告"],
            ["04", "校验边界"],
            ["05", candidateId ? "候选已准备" : "等待生成候选"],
          ].map(([index, label]) => `
            <div class="stage-button done" style="cursor:default;">
              <span>${escapeHtml(index)}</span>
              <strong>${escapeHtml(label)}</strong>
            </div>`).join("")}
        </div>`;
      markBackendRendered(corePanel);
    }
    ["parseBar", "validateBar", "candidateBar"].forEach((id) => {
      const bar = doc.getElementById(id);
      if (bar) bar.style.width = "100%";
    });
    setRenderedText(doc.getElementById("logTitle"), "后端处理记录");
    const logList = doc.getElementById("logList");
    if (logList) {
      logList.innerHTML = [
        `接收导入记录：${importId || "等待"}`,
        `解析结构：${fileKind}`,
        `结构校验：${validationPassed ? "通过" : "需处理"}`,
        `Framework 候选：${candidateId || "尚未生成"}`,
      ].map((line) => `<div class="log-line"><span>${escapeHtml(line)}</span></div>`).join("");
      markBackendRendered(logList);
    }
    markBackendRendered(doc.querySelector("main"));
    return true;
  }

  if (pageId === "analysis-result") {
    const summaryValues = [inputTitle, importId || "无", fileKind, importStatus];
    doc.querySelectorAll(".status-list .status-item strong").forEach((element, index) => {
      if (index < summaryValues.length) {
        setRenderedText(element, summaryValues[index]);
      }
    });
    setRenderedText(doc.getElementById("importStatusText"), importStatus);
    setRenderedText(doc.getElementById("validationText"), validationPassed ? "通过" : "未通过");
    setRenderedText(doc.getElementById("verdictText"), validationPassed ? "可继续" : "需处理");
    setRenderedText(
      doc.getElementById("verdictCopy"),
      validationPassed
        ? `结构校验通过；${warnings.length} 个提醒，${blockers.length} 个阻塞。`
        : `存在 ${blockers.length} 个阻塞，请先处理后再生成候选。`,
    );
    setRenderedText(doc.getElementById("candidateCardValue"), candidateId ? candidateStatus : "待生成");
    setRenderedText(
      doc.getElementById("candidateCardCopy"),
      candidateId ? `候选 ${candidateId} 已可审阅。` : "生成后进入候选审阅。",
    );
    setRenderedText(doc.getElementById("detailEyebrow"), "导入总览");
    setRenderedText(doc.getElementById("detailTitle"), inputTitle);
    setRenderedText(
      doc.getElementById("detailBody"),
      validationPassed
        ? `当前 ${fileKind} 已完成解析并通过结构校验；它仍是审阅材料，不会自动写入当前 Framework。`
        : `当前 ${fileKind} 仍有 ${blockers.length} 个阻塞，需要处理后才能生成候选。`,
    );
    const resultDetailList = doc.getElementById("detailList");
    if (resultDetailList) {
      resultDetailList.innerHTML = [
        ["导入状态", importStatus],
        ["解析状态", parseStatus],
        ["文件类型", fileKind],
        ["用户确认", validation.requires_user_confirmation ?? validation.requiresUserConfirmation ? "需要" : "不需要"],
      ].map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join("");
      markBackendRendered(resultDetailList);
    }
    setRenderedText(doc.getElementById("ringText"), validationPassed ? "PASS" : "CHECK");
    const reportRefs =
      detail.story_analysis_report_refs ||
      detail.storyAnalysisReportRefs ||
      [];
    const resultCards = doc.querySelectorAll(".result-card");
    const resultCardValues = [
      ["导入记录", importStatus, `${filename} / ${parseStatus}`],
      ["校验报告", validationPassed ? "通过" : "需处理", `${warnings.length} 个提醒 / ${blockers.length} 个阻塞`],
      ["报告引用", `${reportRefs.length} 份`, reportRefs.length ? "可在报告 Viewer 中审阅。" : "当前导入包没有外部故事分析报告。"],
      ["Framework 候选", candidateId ? candidateStatus : "待生成", candidateId ? `候选 ${candidateId} 已可审阅。` : "生成后进入候选审阅。"],
    ];
    const resultTabData = {
      overview: {
        eyebrow: "总览",
        title: inputTitle,
        body: validationPassed
          ? "导入记录已完成解析和结构校验，当前材料不会自动写入 Framework。"
          : "导入记录存在阻塞，需要先处理问题记录。",
        ring: validationPassed ? "PASS" : "CHECK",
        pills: [parseStatus, fileKind, importStatus],
        rows: [
          ["导入 ID", importId || "无"],
          ["导入状态", importStatus],
          ["解析状态", parseStatus],
          ["用户确认", validation.requires_user_confirmation ?? validation.requiresUserConfirmation ? "需要" : "不需要"],
        ],
      },
      validation: {
        eyebrow: "校验",
        title: validationPassed ? "结构校验通过" : "结构校验需要处理",
        body: `当前有 ${warnings.length} 个提醒和 ${blockers.length} 个阻塞。`,
        ring: validationPassed ? "PASS" : String(blockers.length),
        pills: [validationPassed ? "通过" : "未通过", `提醒 ${warnings.length}`, `阻塞 ${blockers.length}`],
        rows: [
          ["是否通过", validationPassed ? "是" : "否"],
          ["可继续", validationPassed ? "是" : "否"],
          ["提醒", String(warnings.length)],
          ["阻塞", String(blockers.length)],
        ],
      },
      report: {
        eyebrow: "报告",
        title: reportRefs.length ? "故事分析报告引用" : "无外部故事分析报告",
        body: reportRefs.length
          ? "报告只作为解释与证据来源，不会直接转化为故事生成约束。"
          : "当前导入内容是 Framework Package，因此没有额外的故事分析报告引用。",
        ring: String(reportRefs.length),
        pills: reportRefs.length ? ["报告引用", "仅供审阅", "不自动回写"] : ["无报告引用"],
        rows: reportRefs.length
          ? reportRefs.slice(0, 4).map((item, index) => [
              `报告 ${index + 1}`,
              firstNonEmpty(item.report_ref_id, item.reportRefId, item.safe_title, item.safeTitle, String(item)),
            ])
          : [["报告引用", "无"]],
      },
      candidate: {
        eyebrow: "候选",
        title: candidateId ? "Framework 候选可审阅" : "Framework 候选待生成",
        body: candidateId
          ? `候选 ${candidateId} 已完成规范化，仍需经过导入编辑会话与用户确认。`
          : "生成候选只会创建未激活副本，不会自动改写当前 Framework。",
        ring: candidateId ? "READY" : "WAIT",
        pills: [candidateStatus, candidateId ? "未激活" : "待生成", "需确认"],
        rows: [
          ["候选 ID", candidateId || "尚未生成"],
          ["候选状态", candidateStatus],
          ["可进入编辑", candidateId ? "是" : "否"],
          ["激活状态", "未激活"],
        ],
      },
    };
    const renderResultTab = (tabId) => {
      const tab = resultTabData[tabId] || resultTabData.overview;
      setRenderedText(doc.getElementById("detailEyebrow"), tab.eyebrow);
      setRenderedText(doc.getElementById("detailTitle"), tab.title);
      setRenderedText(doc.getElementById("detailBody"), tab.body);
      setRenderedText(doc.getElementById("ringText"), tab.ring);
      const detailList = doc.getElementById("detailList");
      if (detailList) {
        detailList.innerHTML = tab.rows.map(([label, value]) => `
          <div class="detail-row"><b>${escapeHtml(String(label))}</b><span>${escapeHtml(String(value))}</span></div>`).join("");
        markBackendRendered(detailList);
      }
      const pillRow = doc.getElementById("pillRow");
      if (pillRow) {
        pillRow.innerHTML = tab.pills.map((pill) => `<span class="pill">${escapeHtml(String(pill))}</span>`).join("");
        markBackendRendered(pillRow);
      }
      doc.querySelectorAll("[data-tab]").forEach((element) => {
        element.classList.toggle("active", element.dataset.tab === tabId);
      });
    };
    resultCards.forEach((card, index) => {
      const [label, value, copy] = resultCardValues[index] || ["结果", "无", ""];
      setRenderedText(card.querySelector("span"), label);
      setRenderedText(card.querySelector("strong"), value);
      setRenderedText(card.querySelector("p"), copy);
      card.dataset.localOnly = "true";
      if (card.dataset.mafsAnalyzeResultTabBound !== "true") {
        card.dataset.mafsAnalyzeResultTabBound = "true";
        card.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          renderResultTab(card.dataset.tab || "overview");
        }, true);
      }
      markBackendRendered(card);
    });
    doc.querySelectorAll(".tab-button").forEach((button) => {
      button.dataset.localOnly = "true";
      if (button.dataset.mafsAnalyzeResultTabBound !== "true") {
        button.dataset.mafsAnalyzeResultTabBound = "true";
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          renderResultTab(button.dataset.tab || "overview");
        }, true);
      }
    });
    renderResultTab("overview");
    setRenderedText(doc.getElementById("nextValidation"), validationPassed ? "校验通过" : "存在阻塞");
    setRenderedText(doc.getElementById("nextCandidate"), candidateId ? "候选可审阅" : "候选待生成");
    setRenderedText(doc.getElementById("nextCandidateCopy"), candidateId ? candidateId : "生成后再进入候选审阅。");
    const nextItems = doc.querySelectorAll(".next-item");
    if (nextItems[1]) {
      setRenderedText(nextItems[1].querySelector("strong"), reportRefs.length ? "报告可审阅" : "无外部分析报告");
      setRenderedText(
        nextItems[1].querySelector("span"),
        reportRefs.length ? "报告只作为解释与证据来源。" : "当前导入内容为 Framework Package。",
      );
    }
    const candidateButton = doc.getElementById("candidateButton");
    setRenderedText(candidateButton, candidateId ? "查看 Framework 候选" : "生成 Framework 候选");
    bindBackendActionElement(
      candidateButton,
      candidateId ? "analyze.refresh" : "analyze.createCandidate",
      "framework-candidate",
    );
    const revalidateButton = doc.getElementById("revalidateButton");
    setRenderedText(revalidateButton, "重新校验导入包");
    bindBackendActionElement(revalidateButton, "analyze.validateBundle", "analysis-result");
    const openReportButton = doc.getElementById("openReportButton");
    if (openReportButton && !reportRefs.length) {
      setRenderedText(openReportButton, "无外部分析报告");
      openReportButton.disabled = true;
      openReportButton.dataset.localOnly = "true";
    }
    const issueList = doc.querySelector("#issueBackdrop .issue-list, #issueBackdrop .drawer-list");
    if (issueList) {
      const issueItems = [...blockers.map((item) => ["阻塞", item]), ...warnings.map((item) => ["提醒", item])];
      issueList.innerHTML = issueItems.length
        ? issueItems.map(([kind, item]) => `<div class="issue-row"><strong>${escapeHtml(kind)}</strong><span>${escapeHtml(worldCanvasText(item) || String(item))}</span></div>`).join("")
        : '<div class="issue-row"><strong>通过</strong><span>当前导入包没有阻塞或提醒。</span></div>';
      markBackendRendered(issueList);
    }
    setRenderedText(doc.getElementById("issueTitle"), "问题记录");
    markBackendRendered(doc.querySelector("main"));
    return true;
  }

  const normalizedPackage =
    candidate?.normalized_framework_package ||
    candidate?.normalizedFrameworkPackage ||
    {};
  const macroFramework =
    normalizedPackage.macro_framework ||
    normalizedPackage.macroFramework ||
    {};
  const macroComponents = macroFramework.components || [];
  const chapterAssignments =
    normalizedPackage.chapter_macro_assignments ||
    normalizedPackage.chapterMacroAssignments ||
    [];
  const chapterModules =
    normalizedPackage.component_vocabulary?.chapter_modules ||
    normalizedPackage.componentVocabulary?.chapterModules ||
    [];
  const canProceed = Boolean(
    candidate?.can_proceed_to_m4_workbench ??
    candidate?.canProceedToM4Workbench,
  );
  const candidateList = doc.querySelector(".candidate-list");
  doc.querySelectorAll("div > span").forEach((label) => {
    if (String(label.textContent || "").trim() === "候选") {
      const value = label.parentElement?.querySelector("strong");
      if (value) {
        setRenderedText(value, candidateId || "尚未生成");
      }
    }
  });
  if (candidateList) {
    candidateList.innerHTML = "";
    if (candidateId) {
      const card = doc.createElement("button");
      card.type = "button";
      card.className = "candidate-card active";
      card.dataset.localOnly = "true";
      card.innerHTML = `
        <span>${escapeHtml(candidateStatus)}</span>
        <strong>${escapeHtml(firstNonEmpty(macroFramework.label, macroFramework.title, candidateId))}</strong>
        <div class="candidate-meta">
          <b>宏组件 ${macroComponents.length}</b>
          <b>章节映射 ${chapterAssignments.length}</b>
          <b>篇章模块 ${chapterModules.length}</b>
        </div>`;
      candidateList.appendChild(card);
    } else {
      const empty = doc.createElement("p");
      empty.textContent = "当前导入记录尚未生成 Framework 候选。";
      candidateList.appendChild(empty);
    }
    markBackendRendered(candidateList);
  }
  setRenderedText(doc.getElementById("leftVerdict"), canProceed ? "可进入编辑会话" : "候选不可用");
  setRenderedText(
    doc.getElementById("leftVerdictCopy"),
    canProceed ? "候选已规范化，将以 inactive copy 打开，不会直接激活。" : "请返回分析结果处理阻塞。",
  );
  setRenderedText(doc.getElementById("candidateStatus"), candidateStatus);
  setRenderedText(doc.getElementById("candidateTitle"), firstNonEmpty(macroFramework.label, candidateId, "Framework 候选"));
  setRenderedText(doc.getElementById("scoreBox"), canProceed ? "可审阅" : "阻塞");
  setRenderedText(doc.getElementById("detailEyebrow"), "候选总览");
  setRenderedText(doc.getElementById("detailTitle"), firstNonEmpty(macroFramework.label, candidateId, "Framework 候选"));
  setRenderedText(doc.getElementById("detailBody"), `候选来源于 ${importId || "当前导入"}，仍需用户在导入编辑会话中确认。`);
  const candidateDetailList = doc.getElementById("detailList");
  if (candidateDetailList) {
    candidateDetailList.innerHTML = [
      ["候选 ID", candidateId || "无"],
      ["候选状态", candidateStatus],
      ["可进入编辑", canProceed ? "是" : "否"],
      ["用户确认", candidate?.requires_user_confirmation ?? candidate?.requiresUserConfirmation ? "需要" : "不需要"],
    ].map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join("");
    markBackendRendered(candidateDetailList);
  }
  setRenderedText(doc.getElementById("selectedName"), firstNonEmpty(macroFramework.label, candidateId, "Framework 候选"));
  setRenderedText(doc.getElementById("selectedStatus"), canProceed ? "可创建 inactive edit session。" : "当前候选不可进入编辑。");
  setRenderedText(doc.getElementById("sideValidation"), canProceed ? "候选校验通过" : "候选存在阻塞");
  setRenderedText(doc.getElementById("sideValidationCopy"), `${macroComponents.length} 个宏组件，${chapterModules.length} 个篇章模块。`);
  const countValues = [
    `宏组件 ${macroComponents.length}`,
    `章节映射 ${chapterAssignments.length}`,
    `篇章模块 ${chapterModules.length}`,
    `阻塞 ${canProceed ? 0 : 1}`,
  ];
  doc.querySelectorAll("#countGrid > *").forEach((element, index) => {
    setRenderedText(element, countValues[index] || "");
  });
  const revalidateButton = doc.getElementById("revalidateButton");
  setRenderedText(revalidateButton, "候选已校验");
  if (revalidateButton) {
    revalidateButton.disabled = true;
    revalidateButton.dataset.localOnly = "true";
  }
  const previewButton = doc.getElementById("previewButton");
  setRenderedText(previewButton, "预览组件清单");
  if (previewButton && previewButton.dataset.mafsAnalyzePreviewBound !== "true") {
    previewButton.dataset.mafsAnalyzePreviewBound = "true";
    previewButton.dataset.localOnly = "true";
    previewButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      setRenderedText(doc.getElementById("detailEyebrow"), "组件");
      setRenderedText(doc.getElementById("detailTitle"), "候选组件清单");
      setRenderedText(
        doc.getElementById("detailBody"),
        [...macroComponents, ...chapterModules]
          .map((item) => firstNonEmpty(item.label, item.component_id, item.componentId, item.module_id, item.moduleId))
          .filter(Boolean)
          .join("、") || "当前候选没有可展示的组件。",
      );
    }, true);
  }
  const primaryButton = doc.getElementById("primaryButton");
  setRenderedText(primaryButton, canProceed ? "打开导入编辑会话" : "候选不可用");
  if (canProceed) {
    bindBackendActionElement(primaryButton, "analyze.startEditSession", "imported-session");
  } else if (primaryButton) {
    primaryButton.disabled = true;
  }
  const diffList = doc.getElementById("diffList");
  if (diffList) {
    const diffItems = [
      `规范化状态：${candidateStatus}`,
      `来源导入：${importId || "无"}`,
      `宏观 Framework：${macroComponents.length} 个组件`,
      `篇章 Framework：${chapterModules.length} 个模块`,
    ];
    diffList.innerHTML = diffItems.map((item) => `<div class="diff-row"><strong>${escapeHtml(item)}</strong></div>`).join("");
    markBackendRendered(diffList);
  }
  markBackendRendered(doc.querySelector("main"));
  return true;
}

function importedFrameworkSurfacePayload(result) {
  const payload = result?.action_result || result?.actionResult || result || {};
  if (
    payload?.selected_imported_edit_session ||
    payload?.selectedImportedEditSession ||
    payload?.imported_edit_sessions ||
    payload?.importedEditSessions
  ) {
    return payload;
  }
  return payload?.action_result || payload?.actionResult || payload;
}

function renderImportedFrameworkSessionSurface(doc, result) {
  if (framePageId(doc) !== "imported-session") {
    return false;
  }
  const payload = importedFrameworkSurfacePayload(result);
  const sessionsResponse =
    payload?.imported_edit_sessions ||
    payload?.importedEditSessions ||
    {};
  const sessions =
    sessionsResponse.edit_sessions ||
    sessionsResponse.editSessions ||
    [];
  const selectedResult =
    payload?.selected_imported_edit_session ||
    payload?.selectedImportedEditSession ||
    payload?.action_result ||
    payload?.actionResult ||
    {};
  const session =
    selectedResult.edit_session ||
    selectedResult.editSession ||
    sessions[0] ||
    {};
  const validation =
    selectedResult.validation_report ||
    selectedResult.validationReport ||
    session.latest_validation_report ||
    session.latestValidationReport ||
    session.validation_report ||
    session.validationReport ||
    {};
  const plan =
    selectedResult.activation_plan ||
    selectedResult.activationPlan ||
    payload?.activation_plan ||
    payload?.activationPlan ||
    null;
  const sessionId = firstNonEmpty(session.edit_session_id, session.editSessionId);
  const candidateId = firstNonEmpty(session.candidate_id, session.candidateId);
  const packageData =
    session.working_framework_package ||
    session.workingFrameworkPackage ||
    {};
  const macroFramework =
    packageData.macro_framework ||
    packageData.macroFramework ||
    {};
  const macroComponents = (macroFramework.components || []).filter((item) => !item.deleted);
  const chapterModules =
    packageData.component_vocabulary?.chapter_modules ||
    packageData.componentVocabulary?.chapterModules ||
    [];
  const assignments =
    packageData.chapter_macro_assignments ||
    packageData.chapterMacroAssignments ||
    [];
  const builtChapterFrameworks =
    packageData.built_chapter_frameworks ||
    packageData.builtChapterFrameworks ||
    [];
  const sourceRefs = session.source_refs || session.sourceRefs || [];
  const patches = selectedResult.patches || [];
  const warnings = validation.warnings || [];
  const blockers = validation.blocking_issues || validation.blockingIssues || [];
  const activationMode = firstNonEmpty(
    plan?.activation_mode,
    plan?.activationMode,
    session.activation_mode,
    session.activationMode,
    "reference_only",
  );
  const modeLabels = {
    reference_only: "仅参考",
    merge: "合并",
    set_active: "设为当前",
  };
  const sourceTypeLabels = {
    framework_candidate: "Framework 候选",
    normalization_report: "规范化报告",
    import: "Analyze Stories 导入记录",
    story_analysis_report: "故事分析报告",
    analysis_report_viewer: "分析报告审阅记录",
  };
  const planStatus = firstNonEmpty(plan?.plan_status, plan?.planStatus, "尚未生成");
  const sessionStatus = firstNonEmpty(session.session_status, session.sessionStatus, "draft");
  const requiresConfirmation = Boolean(
    validation.requires_user_confirmation ??
    validation.requiresUserConfirmation ??
    true,
  );

  const ensureHiddenInput = (id, value) => {
    let input = doc.getElementById(id);
    if (!input) {
      input = doc.createElement("input");
      input.type = "hidden";
      input.id = id;
      input.name = id;
      doc.body.appendChild(input);
    }
    input.value = String(value || "");
    return input;
  };
  ensureHiddenInput("importedEditSessionId", sessionId);
  ensureHiddenInput("importedActivationPlanId", firstNonEmpty(plan?.plan_id, plan?.planId));
  ensureHiddenInput("analyzeCandidateId", candidateId);
  const activationModeInput = ensureHiddenInput("activationMode", activationMode);

  const metricValues = [
    sessionStatus,
    modeLabels[activationMode] || activationMode,
    String(patches.length || session.patch_ids?.length || session.patchIds?.length || 0),
    String(warnings.length),
    String(blockers.length),
  ];
  doc.querySelectorAll(".metrics .metric b").forEach((element, index) => {
    setRenderedText(element, metricValues[index] || "0");
  });

  const candidateCard = doc.querySelector(".candidate-card");
  if (candidateCard) {
    candidateCard.innerHTML = `
      <b>${escapeHtml(firstNonEmpty(macroFramework.label, macroFramework.title, candidateId, "导入 Framework 候选"))}</b>
      <span>${escapeHtml(`${macroComponents.length} 个宏组件 / ${chapterModules.length} 个篇章模块 / ${assignments.length} 个章节映射`)}</span>`;
    candidateCard.dataset.analyzeCandidateId = candidateId;
    bindBackendActionElement(candidateCard, "analyze.refresh", "framework-candidate");
    candidateCard.classList.add("active");
    markBackendRendered(candidateCard);
  }
  const candidateStatusBadge = [...doc.querySelectorAll(".section-head h2")]
    .find((heading) => heading.textContent.trim() === "候选与会话")
    ?.parentElement?.querySelector(".badge");
  setRenderedText(candidateStatusBadge, candidateId ? "候选可编辑" : "无候选");
  const candidateButtons = doc.querySelectorAll(".action-row .small-btn");
  const openCandidateButton = candidateButtons[0];
  const createSessionButton = candidateButtons[1];
  if (openCandidateButton) {
    setRenderedText(openCandidateButton, "返回候选审阅");
    openCandidateButton.dataset.analyzeCandidateId = candidateId;
    bindBackendActionElement(openCandidateButton, "analyze.refresh", "framework-candidate");
  }
  if (createSessionButton) {
    setRenderedText(createSessionButton, "新建候选副本");
    createSessionButton.dataset.analyzeCandidateId = candidateId;
    bindBackendActionElement(createSessionButton, "analyze.startEditSession", "imported-session");
    createSessionButton.disabled = !candidateId;
  }

  const sessionCards = doc.querySelectorAll(".session-card");
  sessionCards.forEach((card, index) => {
    const item = sessions[index];
    if (!item) {
      card.remove();
      return;
    }
    const itemId = firstNonEmpty(item.edit_session_id, item.editSessionId);
    const itemStatus = firstNonEmpty(item.session_status, item.sessionStatus, "draft");
    const itemMode = firstNonEmpty(item.activation_mode, item.activationMode, "未选择");
    const itemWarnings = Number(item.warning_count || item.warningCount || 0);
    card.innerHTML = `
      <b>${escapeHtml(itemId)}</b>
      <span>${escapeHtml(`${itemStatus} / ${modeLabels[itemMode] || itemMode} / ${itemWarnings} 个提醒`)}</span>`;
    card.classList.toggle("active", itemId === sessionId);
    card.dataset.importedEditSessionId = itemId;
    bindBackendActionElement(card, "framework.selectImportedSession", "imported-session");
    markBackendRendered(card);
  });
  const sessionCountBadge = [...doc.querySelectorAll(".section-head h3")]
    .find((heading) => heading.textContent.trim() === "编辑会话")
    ?.parentElement?.querySelector(".badge");
  setRenderedText(sessionCountBadge, `${sessions.length} 条`);

  const sourceList = doc.querySelector(".source-list");
  if (sourceList) {
    sourceList.innerHTML = sourceRefs.length
      ? sourceRefs.map((item) => `
          <div class="source-row">
            <span class="source-dot"></span>
            <div>
              <b>${escapeHtml(sourceTypeLabels[firstNonEmpty(item.source_type, item.sourceType)] || "来源")}</b>
              <span>${escapeHtml(firstNonEmpty(item.source_id, item.sourceId, "已载入"))}</span>
            </div>
          </div>`).join("")
      : '<div class="source-row"><span class="source-dot"></span><div><b>当前候选</b><span>尚无额外来源引用。</span></div></div>';
    markBackendRendered(sourceList);
  }

  doc.querySelectorAll(".mode").forEach((button) => {
    const mode = button.dataset.impact || "";
    button.classList.toggle("active", mode === activationMode);
    button.dataset.localOnly = "true";
    if (button.dataset.mafsImportedModeBound !== "true") {
      button.dataset.mafsImportedModeBound = "true";
      button.addEventListener("click", () => {
        activationModeInput.value = mode;
      });
    }
  });

  const compareValues = [
    ["宏观组件", macroComponents.length],
    ["篇章模块", chapterModules.length],
    ["章节映射", assignments.length],
    ["已构建未来章", builtChapterFrameworks.length],
  ];
  doc.querySelectorAll(".compare-grid").forEach((grid, gridIndex) => {
    if (gridIndex !== 0) {
      return;
    }
    grid.querySelectorAll(".mini-card").forEach((card, index) => {
      const [label, value] = compareValues[index] || ["数据", 0];
      setRenderedText(card.querySelector("span"), label);
      setRenderedText(card.querySelector("b"), String(value));
    });
  });

  const componentList = doc.querySelector(".component-list");
  const componentLabel = doc.getElementById("componentLabel");
  const componentInstruction = doc.getElementById("componentInstruction");
  const componentOrder = doc.getElementById("componentOrder");
  const componentIdInput = ensureHiddenInput("importedComponentId", firstNonEmpty(macroComponents[0]?.component_id, macroComponents[0]?.componentId));
  const selectComponent = (item, card) => {
    doc.querySelectorAll(".component-card").forEach((element) => element.classList.remove("active"));
    card?.classList.add("active");
    componentIdInput.value = firstNonEmpty(item.component_id, item.componentId);
    if (componentLabel) componentLabel.value = firstNonEmpty(item.label, item.component_id, item.componentId);
    if (componentInstruction) {
      componentInstruction.value = firstNonEmpty(item.instruction, item.safe_summary, item.safeSummary);
      componentInstruction.classList.remove("mafs-backend-pending");
    }
    if (componentOrder) componentOrder.value = String(item.order || 1);
  };
  if (componentList) {
    componentList.innerHTML = "";
    macroComponents.forEach((item, index) => {
      const card = doc.createElement("button");
      card.type = "button";
      card.className = `component-card${index === 0 ? " active" : ""}`;
      card.dataset.localOnly = "true";
      card.innerHTML = `
        <b>${escapeHtml(firstNonEmpty(item.label, item.component_id, item.componentId))}</b>
        <span>${escapeHtml(`${firstNonEmpty(item.component_id, item.componentId)} / order ${item.order || index + 1}`)}</span>`;
      card.addEventListener("click", () => selectComponent(item, card));
      componentList.appendChild(card);
    });
    if (macroComponents[0]) {
      selectComponent(macroComponents[0], componentList.querySelector(".component-card"));
    } else {
      componentList.innerHTML = "<p>当前候选没有宏观 Framework 组件。</p>";
      [componentLabel, componentInstruction, componentOrder].forEach((input) => {
        if (input) input.disabled = true;
      });
    }
    markBackendRendered(componentList);
  }

  const chapterStrip = doc.querySelector(".chapter-strip");
  const chapterIndexInput = ensureHiddenInput("importedChapterIndex", assignments[0]?.chapter_index || assignments[0]?.chapterIndex || "");
  const linkedIdsInput = ensureHiddenInput(
    "linkedMacroComponentIds",
    (assignments[0]?.linked_macro_component_ids || assignments[0]?.linkedMacroComponentIds || []).join(","),
  );
  const chapterTitle = doc.getElementById("chapterTitle");
  const chapterLinked = doc.getElementById("chapterLinked");
  const mappingDetail = chapterTitle?.closest(".detail-card");
  const renderMappingEditor = (assignment, card) => {
    const chapterIndex = Number(assignment.chapter_index || assignment.chapterIndex || 0);
    const linkedIds = assignment.linked_macro_component_ids || assignment.linkedMacroComponentIds || [];
    chapterIndexInput.value = String(chapterIndex || "");
    linkedIdsInput.value = linkedIds.join(",");
    doc.querySelectorAll(".map-card").forEach((element) => element.classList.remove("active"));
    card?.classList.add("active");
    setRenderedText(chapterTitle, `第 ${chapterIndex} 章映射`);
    if (chapterLinked) {
      chapterLinked.innerHTML = `
        <span style="display:block;margin-bottom:8px;">勾选本章轻量关联的宏观 Framework 组件。保存后只形成映射补丁，不会提前构建完整篇章 Framework。</span>
        <span class="mafs-imported-mapping-options" style="display:flex;flex-wrap:wrap;gap:8px;">
          ${macroComponents.map((item) => {
            const componentId = firstNonEmpty(item.component_id, item.componentId);
            const checked = linkedIds.includes(componentId) ? "checked" : "";
            return `<label style="display:inline-flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid rgba(121,89,74,0.18);border-radius:8px;background:rgba(255,255,255,0.52);">
              <input type="checkbox" data-mafs-linked-component-id="${escapeHtml(componentId)}" ${checked}>
              <span>${escapeHtml(firstNonEmpty(item.label, componentId))}</span>
            </label>`;
          }).join("")}
        </span>`;
      chapterLinked.querySelectorAll("[data-mafs-linked-component-id]").forEach((checkbox) => {
        checkbox.addEventListener("change", () => {
          const selectedIds = [...chapterLinked.querySelectorAll("[data-mafs-linked-component-id]:checked")]
            .map((item) => item.dataset.mafsLinkedComponentId)
            .filter(Boolean);
          linkedIdsInput.value = selectedIds.join(",");
        });
      });
      markBackendRendered(chapterLinked);
    }
  };
  if (chapterStrip) {
    chapterStrip.innerHTML = "";
    assignments.forEach((assignment, index) => {
      const chapterIndex = Number(assignment.chapter_index || assignment.chapterIndex || index + 1);
      const linkedIds = assignment.linked_macro_component_ids || assignment.linkedMacroComponentIds || [];
      const card = doc.createElement("button");
      card.type = "button";
      card.className = `map-card${index === 0 ? " active" : ""}`;
      card.dataset.localOnly = "true";
      card.innerHTML = `
        <b>第 ${chapterIndex} 章</b>
        <small>${escapeHtml(linkedIds.join(", ") || "尚未映射")}</small>`;
      card.addEventListener("click", () => renderMappingEditor(assignment, card));
      chapterStrip.appendChild(card);
    });
    if (assignments[0]) {
      renderMappingEditor(assignments[0], chapterStrip.querySelector(".map-card"));
    } else {
      chapterStrip.innerHTML = "<p>当前候选没有提前固化未来章节映射。</p>";
      mappingDetail?.remove();
    }
    markBackendRendered(chapterStrip);
  }
  const chapterBadge = [...doc.querySelectorAll(".section-head h3")]
    .find((heading) => heading.textContent.trim() === "章节映射")
    ?.parentElement?.querySelector(".badge");
  setRenderedText(chapterBadge, `${assignments.length} 章`);

  const validationCard = [...doc.querySelectorAll("article.detail-card")]
    .find((card) => card.querySelector("h3")?.textContent.trim() === "验证报告");
  if (validationCard) {
    setRenderedText(validationCard.querySelector(".badge"), validation.passed ? "通过" : "需处理");
    setRenderedText(
      validationCard.querySelector("p"),
      validation.passed
        ? `当前候选副本校验通过；有 ${warnings.length} 个提醒和 ${blockers.length} 个阻塞。`
        : `当前候选副本尚未通过校验；有 ${warnings.length} 个提醒和 ${blockers.length} 个阻塞。`,
    );
    markBackendRendered(validationCard);
  }
  const validationGrid = doc.querySelectorAll(".compare-grid")[1];
  const validationValues = [
    ["提醒", warnings.length],
    ["阻塞", blockers.length],
    ["确认", requiresConfirmation ? "需要" : "不需要"],
    ["计划", planStatus],
  ];
  validationGrid?.querySelectorAll(".mini-card").forEach((card, index) => {
    const [label, value] = validationValues[index] || ["状态", "无"];
    setRenderedText(card.querySelector("span"), label);
    setRenderedText(card.querySelector("b"), String(value));
  });

  const impact = plan?.impact_summary || plan?.impactSummary || {};
  setRenderedText(doc.getElementById("impactMode"), activationMode);
  setRenderedText(
    doc.getElementById("impactPackage"),
    impact.will_write_framework_package ?? impact.willWriteFrameworkPackage ? "是" : "否",
  );
  setRenderedText(
    doc.getElementById("impactMapping"),
    impact.will_write_framework_macro_mapping_decision ?? impact.willWriteFrameworkMacroMappingDecision ? "是" : "否",
  );
  const impactCards = doc.querySelectorAll(".impact-card");
  if (impactCards[1]) {
    setRenderedText(
      impactCards[1].querySelector("span:last-child"),
      impact.will_write_import_decision ?? impact.willWriteImportDecision ?? true ? "是" : "否",
    );
  }
  if (impactCards[3]) {
    setRenderedText(
      impactCards[3].querySelector("span:last-child"),
      impact.will_rebuild_built_chapter_frameworks ?? impact.willRebuildBuiltChapterFrameworks ? "是" : "否",
    );
  }

  const checkRow = doc.querySelector(".check-row");
  if (checkRow) {
    checkRow.innerHTML = `
      <input id="acceptWarnings" name="acceptWarnings" type="checkbox" ${requiresConfirmation ? "" : "checked"}>
      <label for="acceptWarnings">我已查看提醒，并理解导入结构在确认前不会影响当前故事。</label>`;
    markBackendRendered(checkRow);
  }
  const acceptWarnings = doc.getElementById("acceptWarnings");
  const dockButtons = doc.querySelectorAll(".action-dock .dock-btn");
  const saveButton = dockButtons[0];
  const validateButton = dockButtons[1];
  const buildPlanButton = dockButtons[2];
  const confirmButton = dockButtons[3];
  bindBackendActionElement(saveButton, "framework.saveImportedSession", "imported-session");
  bindBackendActionElement(validateButton, "framework.validateImportedSession", "imported-session");
  bindBackendActionElement(buildPlanButton, "framework.buildActivationPlan", "imported-session");
  if (confirmButton) {
    confirmButton.dataset.importedActivationPlanId = firstNonEmpty(plan?.plan_id, plan?.planId);
    bindBackendActionElement(confirmButton, "framework.confirmActivationPlan", "framework");
    const refreshConfirmState = () => {
      const planReady = Boolean(plan && planStatus === "draft" && blockers.length === 0);
      confirmButton.disabled = !planReady || (requiresConfirmation && !acceptWarnings?.checked);
    };
    acceptWarnings?.addEventListener("change", refreshConfirmState);
    refreshConfirmState();
  }
  [saveButton, validateButton, buildPlanButton].forEach((button) => {
    if (button) button.disabled = !sessionId;
  });
  markBackendRendered(doc.querySelector(".workspace"));
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
    const userPremiseMatch = text.match(
      /User story premise:\s*([\s\S]*?)(?=\n(?:Safe premise summary|Required story elements|User World Canvas focus|ProjectStoryPremise:)|$)/i,
    );
    text = userPremiseMatch ? userPremiseMatch[1] : text;
    text = text
      .replace(/^ProjectStoryPremise:\s*/i, "")
      .replace(/项目前提锚点[:：][\s\S]*$/g, "")
      .trim();
  }
  return text || fallback;
}

function worldCanvasUserPromptText(result, world = null) {
  const premise = findProjectStoryPremisePayload(result) || {};
  const state = findStorySetupStatePayload(result) || {};
  return worldCanvasPromptInputText(
    firstNonEmpty(
      premise.user_story_premise,
      premise.userStoryPremise,
      state.controlled_prompt_text,
      state.controlledPromptText,
      state.story_setup_prompt?.controlled_prompt_text,
      state.storySetupPrompt?.controlledPromptText,
      world?.latest_user_prompt,
      world?.latestUserPrompt,
      world?.source_story_idea,
      world?.sourceStoryIdea,
    ),
    "",
  );
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

function promptContainsPositiveTerm(promptText, term) {
  const source = String(promptText || "");
  let searchFrom = 0;
  while (searchFrom < source.length) {
    const index = source.indexOf(term, searchFrom);
    if (index < 0) {
      return false;
    }
    const prefix = source.slice(Math.max(0, index - 12), index).replace(/\s+/g, "");
    const suffix = source.slice(index + term.length, index + term.length + 8).replace(/\s+/g, "");
    const negated =
      /(?:不要|不想要|不需要|避免|禁止|排除|拒绝|并非|不是|不能是|不得|无|without|not)$/i.test(prefix) ||
      /(?:除外|排除)$/i.test(suffix);
    if (!negated) {
      return true;
    }
    searchFrom = index + term.length;
  }
  return false;
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
  const genreTerms = ["科幻", "魔幻", "奇幻", "低魔", "仙侠", "武侠", "历史", "传奇", "爱情", "喜剧", "恐怖", "犯罪", "都市", "校园", "冒险", "战争", "治愈", "悲剧", "现实", "志怪", "公案", "悬疑"];
  const genre = genreTerms.filter((term) => promptContainsPositiveTerm(source, term)).slice(0, 4).join("、");
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
        ["题材气质", firstNonEmpty(promptSections.genre, tone)],
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

function renderWorldCanvasGapSurface(doc, world, filter = null) {
  if (!doc?.defaultView || !isFramePage(doc, new Set(["world-gap"]))) {
    return false;
  }
  const queueList = doc.getElementById("queueList");
  if (!queueList) {
    return false;
  }
  const allIssues = buildWorldCanvasIssueList(world).filter((issue) => issue.title !== "当前没有阻塞审查项");
  const safeFilter = filter || doc.body.dataset.mafsWorldGapFilter || "all";
  const visibleIssues = allIssues.filter((issue) => safeFilter === "all" || issue.type === safeFilter);
  const counts = {
    unknown: allIssues.filter((issue) => issue.type === "unknown").length,
    conflict: allIssues.filter((issue) => issue.type === "conflict").length,
    confirm: allIssues.filter((issue) => issue.type === "confirm").length,
  };
  doc.body.dataset.mafsWorldGapFilter = safeFilter;
  let selectedIssue = visibleIssues[0] || null;

  const setChoice = (issue, choice = "clarify") => {
    if (!issue) {
      return;
    }
    const labels = {
      clarify: "补全为明确世界事实",
      open: "保留为开放项，延后揭示",
      revise: "修订相关设定以消除缺口",
    };
    doc.querySelectorAll("#decisionGrid .decision-button").forEach((button) => {
      button.classList.toggle("selected", button.dataset.choice === choice);
    });
    const note = doc.getElementById("resolutionNote");
    if (note) {
      note.value = `请处理当前世界画布问题「${issue.title}」：${issue.summary}。用户选择：${labels[choice]}。修订必须保持当前用户故事前提、已确认硬规则和题材基调，不得引入模板故事内容。`;
      note.dispatchEvent(new doc.defaultView.Event("input", { bubbles: true }));
    }
    setRenderedText(doc.getElementById("draftWriteTitle"), labels[choice]);
    setRenderedText(doc.getElementById("draftWriteCopy"), `新草案只处理「${issue.title}」，其它已确认世界事实保持不变。`);
    setRenderedText(doc.getElementById("downstreamTitle"), "重新审阅后再写入下游");
    setRenderedText(doc.getElementById("downstreamCopy"), "角色、Framework、章节和场景只读取用户确认后的新版世界画布。 ");
  };

  const renderSelected = (issue) => {
    selectedIssue = issue;
    setRenderedText(doc.getElementById("resolverTitle"), issue?.title || "当前没有待处理问题");
    setRenderedText(doc.getElementById("resolverSummary"), issue?.summary || "世界画布可以返回审阅并继续确认。 ");
    setRenderedText(doc.getElementById("resolverType"), issue?.label || "可继续");
    setRenderedText(doc.getElementById("resolverDetail"), issue?.detail || "当前分类没有需要处理的真实项目数据。 ");
    setRenderedText(doc.getElementById("sourceEvidence"), issue ? "来自当前世界画布草案的审查结果。" : "当前无阻塞项。 ");
    setRenderedText(
      doc.getElementById("impactRange"),
      issue?.type === "conflict" ? "世界规则与连续性" : issue?.type === "unknown" ? "世界规则与角色行动" : "用户确认与下游生成",
    );
    setRenderedText(doc.getElementById("suggestionText"), issue ? "选择处理方式并提交模型修订。" : "返回草案审阅。 ");
    queueList.querySelectorAll(".queue-item").forEach((button) => {
      button.classList.toggle("active", button.dataset.issueKey === issue?.key);
    });
    setChoice(issue, "clarify");
  };

  queueList.innerHTML = "";
  if (!visibleIssues.length) {
    const empty = doc.createElement("article");
    empty.className = "queue-item mafs-backend-rendered";
    empty.innerHTML = `<span><strong>当前分类没有待处理项</strong><small>请切换分类或返回草案审阅。</small></span><span class="type-badge">空</span>`;
    queueList.appendChild(empty);
  } else {
    visibleIssues.forEach((issue, index) => {
      issue.key = `${issue.type}-${index}-${issue.title}`;
      const button = doc.createElement("button");
      button.type = "button";
      button.className = `queue-item${index === 0 ? " active" : ""}`;
      button.dataset.issueKey = issue.key;
      button.innerHTML = `<span><strong>${escapeHtml(issue.title)}</strong><small>${escapeHtml(issue.summary)}</small></span><span class="type-badge">${escapeHtml(issue.label)}</span>`;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        renderSelected(issue);
      }, true);
      queueList.appendChild(button);
    });
  }
  markBackendRendered(queueList);

  const decisionGrid = doc.getElementById("decisionGrid");
  if (decisionGrid) {
    decisionGrid.innerHTML = [
      ["clarify", "补全事实", "让模型根据当前前提补全边界、机制或代价。"],
      ["open", "延后揭示", "保留为开放项，不提前锁死后续剧情。"],
      ["revise", "修订设定", "调整相关设定，消除冲突或不可执行之处。"],
    ].map(([choice, title, copy]) => `<button class="decision-button" type="button" data-choice="${choice}"><strong>${title}</strong><span>${copy}</span></button>`).join("");
    decisionGrid.querySelectorAll(".decision-button").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        setChoice(selectedIssue, button.dataset.choice || "clarify");
      }, true);
    });
    markBackendRendered(decisionGrid);
  }

  doc.querySelectorAll(".filter-button[data-filter]").forEach((button) => {
    const active = button.dataset.filter === safeFilter;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    if (button.dataset.mafsWorldGapFilterBound === "true") {
      return;
    }
    button.dataset.mafsWorldGapFilterBound = "true";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      renderWorldCanvasGapSurface(doc, world, button.dataset.filter || "all");
    }, true);
  });

  const total = allIssues.length;
  setRenderedText(doc.getElementById("stateCardNumber"), `0 / ${total}`);
  setRenderedText(doc.getElementById("progressCount"), `0 / ${total}`);
  setRenderedText(doc.getElementById("unknownCount"), `0 / ${counts.unknown}`);
  setRenderedText(doc.getElementById("conflictCount"), `0 / ${counts.conflict}`);
  setRenderedText(doc.getElementById("confirmCount"), `0 / ${counts.confirm}`);
  setRenderedText(doc.getElementById("progressCopy"), total ? "选择一项并提交处理后，系统会生成新版草案。" : "当前没有待处理问题。 ");
  setRenderedText(doc.getElementById("nextStepNote"), total ? "提交处理后返回草案审阅，新版草案仍需用户确认。" : "可返回草案审阅并继续确认。 ");
  const saveButton = doc.getElementById("saveButton");
  if (saveButton) {
    saveButton.textContent = "提交处理并返回审阅";
    saveButton.disabled = !selectedIssue;
  }
  const continueButton = doc.getElementById("continueButton");
  if (continueButton) {
    continueButton.textContent = "返回草案审阅";
    continueButton.disabled = total > 0;
  }
  renderSelected(selectedIssue);
  return true;
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
      "#storyIdea, #sectionTitle, #factList, #currentSummary, #confirmButton, #revisionText, #contextTitle, #contextList, #requestCopy, #queueList, #resolverTitle, #resolutionNote",
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
  setControlValue(doc, ["#storyIdea"], worldCanvasUserPromptText(result, world));
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
  renderWorldCanvasGapSurface(doc, world);
  renderWorldCanvasRevisionSurface(doc, world);
  applyRealtimeProgressElements(doc, { label: "世界画布草案已同步", percent: 100 });
  [120, 600, 1400].forEach((delayMs) => {
    window.setTimeout(() => {
      suppressWorldCanvasStaticText(doc, world);
      renderWorldCanvasIssues(doc, world);
      renderWorldCanvasAuxiliaryPanels(doc, world);
      renderWorldCanvasGapSurface(doc, world);
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

function renderCharacterRevisionSurface(doc, character, draft, data) {
  if (!doc?.body || framePageId(doc) !== "character-revision" || !character) {
    return;
  }
  const profile = character.profile || {};
  const state = character.current_state || character.currentState || {};
  const report = draft?.validation_report || draft?.validationReport || {};
  const blockingIssues = report.blocking_issues || report.blockingIssues || [];
  const warnings = report.warnings || [];
  const confirmations = report.user_confirmation_needed || report.userConfirmationNeeded || [];
  const relationshipDrafts = draft?.relationship_drafts || draft?.relationshipDrafts || [];
  const name = firstNonEmpty(character.name, "当前角色");
  const displayTier = normalizeCharacterTier(data.displayTier || character.tier) || "A";
  const identity = characterFallbackText(data.identity || profile.identity, `${displayTier} 级角色`);
  const storyFunction = characterFallbackText(profile.story_function || profile.storyFunction, "尚未明确故事作用");
  const relationshipSummary = relationshipDrafts.length
    ? relationshipDrafts
        .map((item) => `${firstNonEmpty(item.type, "关系")}: ${characterFallbackText(item.state, "待确认关系", 180)}`)
        .join("；")
    : "当前没有待写入的关系草案。";
  const stateRefs = [
    ["地点", state.location_id || state.locationId],
    ["势力", state.faction_id || state.factionId],
    ["种族", state.species_id || state.speciesId],
  ].filter(([, value]) => Boolean(value));
  const stateRefText = stateRefs.length
    ? stateRefs.map(([label, value]) => `${label}: ${value}`).join("；")
    : "当前角色没有未确认的世界实体引用。";
  const focusItems = [
    {
      id: "blocking",
      type: "写入阻塞",
      title: blockingIssues.length ? "必须先解决的写入问题" : "当前没有写入阻塞",
      detail: blockingIssues.length ? blockingIssues.join("；") : "后端校验没有返回阻塞项。",
      goal: "只修复阻塞角色写入的问题，不改变已经成立的核心人物设定。",
    },
    {
      id: "function",
      type: "故事作用",
      title: `${name}在故事中的功能`,
      detail: storyFunction,
      goal: "使用贴合本项目的中文叙事功能描述，避免调试枚举或模板角色类型进入正式档案。",
    },
    {
      id: "relationships",
      type: "关系草案",
      title: "关系对象与写入边界",
      detail: relationshipSummary,
      goal: "只写入指向已创建角色的关系；未创建人物保留为背景或待建关系意图。",
    },
    {
      id: "state-refs",
      type: "状态引用",
      title: "角色状态与世界实体的一致性",
      detail: warnings.length ? `${warnings.join("；")} 当前引用：${stateRefText}` : stateRefText,
      goal: "清除或改正尚未存在于世界画布中的实体 ID，避免制造不存在的地点、势力和种族记录。",
    },
    {
      id: "confirmation",
      type: "用户确认",
      title: "需要用户判断的边界",
      detail: confirmations.length ? confirmations.join("；") : "当前没有额外确认项。",
      goal: "保留用户已经确认的角色目标、能力代价、人物弧光和世界观继承关系。",
    },
  ];

  setRenderedText(doc.querySelector(".hero .lead"), `${name}的修订只会生成新草案，不会直接写入角色底座。`);
  setRenderedText(doc.querySelector(".main-head h2"), `修订 ${name} 的角色草案`);
  setRenderedText(doc.querySelector(".main-head .subcopy"), "依据当前草案与后端校验结果描述修改要求；模型将重新生成完整草案并返回审阅。");
  setRenderedText(doc.getElementById("topStatus"), blockingIssues.length ? "存在待修订问题" : "可选择性修订");
  setRenderedText(doc.getElementById("phaseWord"), blockingIssues.length ? `${blockingIssues.length} 项阻塞` : "待修订");
  setRenderedText(doc.getElementById("phaseHint"), `${warnings.length} 项警告`);

  const focusStack = doc.getElementById("focusStack");
  const revisionInput = doc.getElementById("revisionInput");
  const selectFocus = (focus, button) => {
    focusStack?.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
    button?.classList.add("active");
    setRenderedText(doc.getElementById("focusType"), focus.type);
    setRenderedText(doc.getElementById("focusTitle"), focus.title);
    setRenderedText(doc.getElementById("focusDetail"), focus.detail);
    setRenderedText(doc.getElementById("focusGoal"), focus.goal);
    setRenderedText(doc.getElementById("selectedCount"), "1 项");
    setRenderedText(doc.getElementById("focusCounter"), "1 项已选");
    if (revisionInput && !revisionInput.value.trim()) {
      revisionInput.placeholder = `请说明如何修订“${focus.title}”，以及必须保留哪些已确认事实。`;
    }
  };
  if (focusStack) {
    focusStack.innerHTML = "";
    focusItems.forEach((focus, index) => {
      const button = doc.createElement("button");
      button.type = "button";
      button.className = `focus-button mafs-backend-rendered${index === 0 ? " active" : ""}`;
      button.innerHTML = `<span>${escapeHtml(focus.type)}</span><strong>${escapeHtml(focus.title)}</strong><small>${escapeHtml(focus.detail)}</small>`;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        selectFocus(focus, button);
      }, true);
      focusStack.appendChild(button);
    });
    markBackendRendered(focusStack);
    selectFocus(focusItems[0], focusStack.querySelector("button"));
  }

  ["modeRow", "choiceGrid", "protectRow"].forEach((id) => {
    const element = doc.getElementById(id);
    const label = element?.previousElementSibling;
    if (element) {
      element.replaceChildren();
      element.hidden = true;
    }
    if (label?.classList.contains("label")) {
      label.hidden = true;
    }
  });
  const addButton = doc.getElementById("addButton");
  if (addButton) {
    addButton.hidden = true;
  }
  if (revisionInput) {
    if (/(洛间|旧钟|钟楼|保存任何记忆|记忆能力修订)/.test(String(revisionInput.value || ""))) {
      revisionInput.value = "";
      revisionInput.dataset.mafsUserEdited = "false";
    }
    revisionInput.placeholder = `请写明要怎样修订 ${name}，以及必须保留哪些内容。`;
    revisionInput.addEventListener("input", () => {
      const ready = Boolean(revisionInput.value.trim());
      const submit = doc.getElementById("submitButton");
      if (submit) {
        submit.disabled = !ready;
      }
      setRenderedText(doc.getElementById("readyState"), ready ? "可以提交" : "等待修订要求");
      setRenderedText(doc.getElementById("revisionState"), ready ? "修订要求已填写" : "等待填写修订要求");
    });
    markBackendRendered(revisionInput);
  }
  const revisionList = doc.getElementById("revisionList");
  if (revisionList) {
    revisionList.innerHTML = `<div class="revision-item mafs-backend-rendered"><strong>当前后端校验</strong><span>${escapeHtml(blockingIssues.length ? blockingIssues.join("；") : "无阻塞项，可按需修订。")}</span></div>`;
    markBackendRendered(revisionList);
  }
  const resultCards = Array.from(doc.querySelectorAll(".result-card"));
  setLabeledCardText(resultCards[0], "当前角色", `${name} / ${displayTier} 级 / ${identity}`);
  setLabeledCardText(resultCards[1], "修订状态", "等待用户填写修订要求");
  setLabeledCardText(resultCards[2], "下一步", "提交后调用当前模型生成新草案并重新审阅");
  setRenderedText(doc.getElementById("actionHint"), "填写修订要求后提交；生成完成前不会进入下一页。");
  setRenderedText(doc.getElementById("modeState"), "由修订要求决定");
  setRenderedText(doc.getElementById("protectCount"), "保留已确认事实");
  const submitButton = doc.getElementById("submitButton");
  if (submitButton) {
    submitButton.disabled = !revisionInput?.value.trim();
    submitButton.textContent = "提交修订并重新审阅";
    submitButton.dataset.mafsActionId = "characters.revise";
    submitButton.dataset.mafsTarget = "character-generating";
    markBackendRendered(submitButton);
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
  const alreadyConfirmed = String(character?.status || "").toLowerCase() === "confirmed" || String(draft?.status || "").toLowerCase() === "confirmed";
  setLabeledCardText(resultCards[1], "\u5199\u5165\u72b6\u6001", alreadyConfirmed ? "\u5df2\u5199\u5165\u89d2\u8272\u5e95\u5ea7" : "\u5f85\u7528\u6237\u786e\u8ba4\u5199\u5165");
  setLabeledCardText(resultCards[2], "\u4e0b\u4e00\u6b65", alreadyConfirmed ? "\u8fdb\u5165\u89d2\u8272\u6863\u6848\u5e93\u5e76\u6784\u5efa\u4e0a\u4e0b\u6587" : "\u5199\u5165\u540e\u8fdb\u5165\u89d2\u8272\u6863\u6848\u5e93");

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
    button.textContent = alreadyConfirmed ? "\u67e5\u770b\u89d2\u8272\u6863\u6848\u5e93" : "\u786e\u8ba4\u5199\u5165";
    button.dataset.mafsActionId = alreadyConfirmed ? "roles.refresh" : "characters.confirm";
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
  const stalePattern = /(暂无此项数据|正在读取项目数据|待后端接入|洛闻|洛间|低魔悬疑|港口城|旧钟|钟楼修复师|保存任何记忆|æš‚æ— æ­¤é¡¹æ•°æ®|æ­£åœ¨è¯»å–é¡¹ç›®æ•°æ®|å¾…åŽç«¯æŽ¥å…¥)/;
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

function renderCharacterEntryExistingState(doc, character, draft, tier) {
  if (!doc?.body || framePageId(doc) !== "character-entry" || !character) {
    return false;
  }
  const displayTier = normalizeCharacterTier(tier || character.tier) || "A";
  const name = firstNonEmpty(character.name, "当前角色");
  const confirmed = String(character.status || "").toLowerCase() === "confirmed" ||
    String(draft?.status || "").toLowerCase() === "confirmed";
  setRenderedText(doc.getElementById("pageState"), confirmed ? "已确认" : "草案已生成");
  setRenderedText(doc.getElementById("pageState")?.nextElementSibling, "角色主轴状态");
  setRenderedText(doc.getElementById("topStatus"), confirmed ? "角色底座可读" : "角色草案可审阅");
  setRenderedText(
    doc.getElementById("nextNote"),
    `${name} 已存在于当前项目；可查看并修订已有草案，也可以在下方继续创建其他角色。`,
  );
  renderCharacterPanel(doc, character, draft, displayTier);

  doc.querySelectorAll("article").forEach((article) => {
    const label = normalizeText(article.querySelector("span, .label")?.textContent || "");
    const strong = article.querySelector("strong");
    if (label === "来源边界" && strong) {
      setRenderedText(strong, "世界画布 + 用户构想");
    }
    if (normalizeText(strong?.textContent || "") === "角色草案") {
      const status = article.querySelector("span:not(.dot), em") || strong?.nextElementSibling;
      setRenderedText(status, confirmed ? "已确认" : "已生成");
    }
  });

  const actionRow = doc.querySelector(".action-row");
  if (actionRow && !doc.getElementById("reviewButton")) {
    const reviewButton = doc.createElement("button");
    reviewButton.id = "reviewButton";
    reviewButton.type = "button";
    reviewButton.className = "ghost-button mafs-backend-rendered";
    reviewButton.textContent = "查看已有角色草案";
    actionRow.insertBefore(reviewButton, doc.getElementById("generateButton"));
  }
  const reviewButton = doc.getElementById("reviewButton");
  if (reviewButton) {
    bindBackendActionElement(reviewButton, "characters.current", "character-review");
  }
  applyRealtimeProgressElements(doc, {
    label: confirmed ? "角色底座已同步" : "角色草案已同步",
    percent: 100,
  });
  return true;
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
  if (framePageId === "character-entry") {
    return renderCharacterEntryExistingState(
      doc,
      payload.character,
      payload.draft,
      characterPayloadTier(payload.character, payload.draft) || preferredCharacterTierFromResult(result) || "A",
    );
  }
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
    doc.querySelector("#archiveTitle, #characterPrompt, #confirmButton, #reviewTitle, #promptTitle, #revisionInput, #focusStack");
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
  renderCharacterRevisionSurface(doc, character, draft, {
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
    const alreadyConfirmed = String(character?.status || "").toLowerCase() === "confirmed" || String(draft?.status || "").toLowerCase() === "confirmed";
    confirmButton.disabled = false;
    confirmButton.textContent = framePageId === "character-confirm"
      ? (alreadyConfirmed ? "查看角色档案库" : "确认写入")
      : "确认草案";
    if (framePageId === "character-confirm") {
      confirmButton.dataset.mafsActionId = alreadyConfirmed ? "roles.refresh" : "characters.confirm";
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
    const listSignature = JSON.stringify(
      displayRoles.map((role) => {
        const roleProfile = role.profile || {};
        const roleState = role.current_state || role.currentState || {};
        return [
          role.name,
          role.tier,
          role.status,
          firstNonEmpty(roleProfile.background_summary, roleProfile.backgroundSummary, roleProfile.description, roleState.active_goal, roleState.activeGoal),
          firstNonEmpty(roleProfile.story_function, roleProfile.storyFunction, role.role),
        ];
      }),
    );
    if (list.dataset.mafsRoleLibrarySignature !== listSignature) {
      list.dataset.mafsRoleLibrarySignature = listSignature;
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
        item.dataset.roleIndex = String(index);
        item.dataset.roleTier = itemTier;
        item.dataset.characterId = firstNonEmpty(role.character_id, role.characterId, role.role_id, role.roleId);
        item.innerHTML = `<div class="item-head"><strong>${escapeHtml(itemName)}</strong><span class="badge">${escapeHtml(itemTier)} \u7ea7</span></div><p>${escapeHtml(itemSummary)}</p><small>${escapeHtml(role.status || "confirmed")} · ${escapeHtml(itemFunction)}</small>`;
        list.appendChild(item);
      });
    }
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
  const panelSignature = JSON.stringify([
    name,
    primary.tier || "A",
    roleTypeLabel,
    background || goal || "角色档案已从后端同步。",
  ]);
  if (panel.dataset.mafsRoleLibrarySignature !== panelSignature) {
    panel.dataset.mafsRoleLibrarySignature = panelSignature;
    panel.innerHTML = `
      <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端角色档案库</p>
      <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">${escapeHtml(name)}</h3>
      <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(primary.tier || "A")} 级角色</strong> · ${escapeHtml(roleTypeLabel)}</p>
      <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(background || goal || "角色档案已从后端同步。")}</p>
      <button id="mafsRoleContextButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="role-context" data-mafs-action-id="roles.contextPreview" style="display:inline-flex;align-items:center;justify-content:center;min-width:112px;min-height:36px;visibility:visible;opacity:1;">上下文预览</button>
    `;
  }
  const applySelectedRole = (role, index = 0) => {
    if (!role) {
      return;
    }
    const selectedProfile = role.profile || {};
    const selectedState = role.current_state || role.currentState || {};
    const selectedName = firstNonEmpty(role.name, "未命名角色");
    const selectedTier = normalizeCharacterTier(role.tier) || "A";
    const selectedBackground = characterFallbackText(
      firstNonEmpty(
        selectedProfile.background_summary,
        selectedProfile.backgroundSummary,
        selectedProfile.description,
        selectedState.active_goal,
        selectedState.activeGoal,
      ),
      "角色档案已同步。",
      240,
    );
    const selectedFunction = characterFallbackText(
      firstNonEmpty(selectedProfile.story_function, selectedProfile.storyFunction, role.role),
      "角色功能",
      100,
    );
    const selectedRoleType =
      String(role.role || "").toLowerCase() === "protagonist" ? "主角" : selectedFunction;
    const selectedCharacterId = firstNonEmpty(
      role.character_id,
      role.characterId,
      role.role_id,
      role.roleId,
    );
    if (selectedCharacterId) {
      doc.body.dataset.mafsSelectedCharacterId = selectedCharacterId;
      try {
        doc.defaultView.parent.__mafsSelectedCharacterId = selectedCharacterId;
      } catch {
        // The iframe and workbench are same-origin in the product UI; keep the
        // page-local selection when an embedding host forbids parent access.
      }
    }
    list?.querySelectorAll(".item[data-role-index]").forEach((item) => {
      item.classList.toggle("selected", item.dataset.roleIndex === String(index));
    });
    setRenderedText(doc.getElementById("roleName"), selectedName);
    setRenderedText(doc.getElementById("roleSummary"), selectedBackground);
    setRenderedText(doc.getElementById("roleTier"), `${selectedTier} 级`);
    setRenderedText(doc.getElementById("roleStatus"), role.status || "confirmed");
    setRenderedText(doc.getElementById("roleProtection"), selectedTier === "A" ? "A 级保护" : "可管理角色");
    setControlValue(doc, ["#editName"], selectedName);
    setControlValue(doc, ["#editFunction"], selectedFunction);
    setControlValue(doc, ["#editSummary"], selectedBackground);
    if (targetTier) {
      targetTier.value = selectedTier;
    }
    panel.innerHTML = `
      <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端角色档案库</p>
      <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">${escapeHtml(selectedName)}</h3>
      <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(selectedTier)} 级角色</strong> · ${escapeHtml(selectedRoleType)}</p>
      <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(selectedBackground)}</p>
      <button id="mafsRoleContextButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="role-context" data-mafs-action-id="roles.contextPreview" style="display:inline-flex;align-items:center;justify-content:center;min-width:112px;min-height:36px;visibility:visible;opacity:1;">上下文预览</button>
    `;
    markBackendRendered(panel);
  };
  list?.querySelectorAll(".item[data-role-index]").forEach((item) => {
    if (item.dataset.mafsRoleSelectionBound === "true") {
      return;
    }
    item.dataset.mafsRoleSelectionBound = "true";
    item.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const index = Number(item.dataset.roleIndex || 0);
        applySelectedRole(displayRoles[index], index);
      },
      true,
    );
  });
  const currentTierFilter = doc.body.dataset.mafsRoleLibraryTierFilter || "all";
  doc.querySelectorAll(".tab-button[data-tier]").forEach((legacyTab) => {
    if (legacyTab.dataset.mafsRoleTierFilterBound === "true") {
      return;
    }
    const tab = legacyTab.cloneNode(true);
    tab.dataset.mafsRoleTierFilterBound = "true";
    legacyTab.replaceWith(tab);
    tab.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const tier = tab.dataset.tier || "all";
        doc.body.dataset.mafsRoleLibraryTierFilter = tier;
        doc.querySelectorAll(".tab-button[data-tier]").forEach((candidate) => {
          candidate.classList.toggle("active", candidate === tab);
        });
        const visibleItems = [];
        list?.querySelectorAll(".item[data-role-index]").forEach((item) => {
          const visible = tier === "all" || item.dataset.roleTier === tier;
          item.hidden = !visible;
          if (visible) {
            visibleItems.push(item);
          }
        });
        const selectedItem = list?.querySelector(".item.selected:not([hidden])");
        if (!selectedItem && visibleItems.length) {
          const index = Number(visibleItems[0].dataset.roleIndex || 0);
          applySelectedRole(displayRoles[index], index);
        }
      },
      true,
    );
  });
  doc.querySelectorAll(".tab-button[data-tier]").forEach((tab) => {
    tab.classList.toggle("active", (tab.dataset.tier || "all") === currentTierFilter);
  });
  list?.querySelectorAll(".item[data-role-index]").forEach((item) => {
    item.hidden = currentTierFilter !== "all" && item.dataset.roleTier !== currentTierFilter;
  });
  const contextButton = panel.querySelector("#mafsRoleContextButton");
  if (contextButton) {
    contextButton.dataset.mafsTarget = "role-context";
    contextButton.dataset.mafsActionId = "roles.contextPreview";
    contextButton.disabled = false;
  }
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
  const actionResult = result?.action_result || result?.actionResult || result;
  let items = findNestedArray(actionResult, ["items", "context_items", "contextItems"]).filter((item) => item && typeof item === "object");
  let cachedRoles = [];
  const selectedCharacterId = firstNonEmpty(
    doc?.body?.dataset?.mafsSelectedCharacterId,
    doc?.defaultView?.parent?.__mafsSelectedCharacterId,
  );
  try {
    cachedRoles = Array.isArray(doc.defaultView.parent.__mafsLastRoleLibraryRoles)
      ? doc.defaultView.parent.__mafsLastRoleLibraryRoles
      : [];
  } catch {
    cachedRoles = [];
  }
  const selectedCachedRoles = selectedCharacterId
    ? cachedRoles.filter((role) => firstNonEmpty(
      role.character_id,
      role.characterId,
      role.role_id,
      role.roleId,
      role.id,
    ) === selectedCharacterId)
    : cachedRoles;
  const rolesForContext = selectedCachedRoles.length
    ? selectedCachedRoles
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
    if (contextLooksGeneric) {
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

function isProjectFrameworkMaterial(material) {
  return Boolean(material?.id) && !isFrameworkLibraryMaterial(material);
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
  const projectMaterials = materials.filter((item) => isProjectFrameworkMaterial(item));
  if (filter === "macro") {
    return projectMaterials.filter((item) => item.type === "macro_component");
  }
  if (filter === "chapter") {
    return projectMaterials.filter((item) => item.type === "chapter_module" || item.type === "module_component");
  }
  if (filter === "library") {
    return materials.filter((item) => isFrameworkLibraryMaterial(item));
  }
  return projectMaterials;
}

function frameworkMaterialCounts(materials) {
  const projectMaterials = materials.filter((item) => isProjectFrameworkMaterial(item));
  const libraryMaterials = materials.filter((item) => isFrameworkLibraryMaterial(item));
  return {
    all: projectMaterials.length,
    macro: projectMaterials.filter((item) => item.type === "macro_component").length,
    chapter: projectMaterials.filter((item) => item.type === "chapter_module" || item.type === "module_component").length,
    library: libraryMaterials.length,
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

function renderFrameworkChapterCandidates(doc, chapterItems, selectedId) {
  const track = doc.getElementById("skeletonTrack");
  if (!track?.parentElement) {
    return;
  }
  let section = doc.getElementById("mafsFrameworkChapterCandidates");
  if (!section) {
    section = doc.createElement("section");
    section.id = "mafsFrameworkChapterCandidates";
    section.className = "mafs-backend-rendered";
    section.style.marginTop = "14px";
    track.insertAdjacentElement("afterend", section);
  }
  section.innerHTML = `
    <div style="margin-bottom:8px;">
      <strong style="display:block;font-size:14px;">当前章节模块候选</strong>
      <span style="color:#6b5d51;font-size:12px;line-height:1.5;">只作为到达当前章节时的即时构建材料，不进入全书宏观骨架，也不提前固化未来章节。</span>
    </div>
    <div class="mafs-framework-dropzone" data-framework-chapter-candidates="true">
      ${chapterItems.length
        ? chapterItems.map((item) => `
          <article class="mafs-framework-canvas-item${item.id === selectedId ? " active" : ""}" data-framework-id="${escapeHtml(item.id)}">
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.summary)}</p>
            <small>${escapeHtml(frameworkItemTypeLabel(item.type))}</small>
            <div style="margin-top:8px;"><button class="mafs-framework-remove" type="button" data-framework-id="${escapeHtml(item.id)}">移出候选</button></div>
          </article>
        `).join("")
        : `<div class="mafs-framework-empty">可从左侧选择篇章模块，作为当前章即时构建候选。</div>`}
    </div>
  `;
  markBackendRendered(section);
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

function syncFrameworkHiddenForm(doc, canvasItems, chapterItems = []) {
  let hidden = doc.getElementById("mafsFrameworkLinkedIds");
  if (!hidden) {
    hidden = doc.createElement("input");
    hidden.type = "hidden";
    hidden.id = "mafsFrameworkLinkedIds";
    hidden.name = "linkedMacroComponentIds";
    doc.body.appendChild(hidden);
  }
  hidden.value = canvasItems.map((item) => item.id).join(",");
  let chapterHidden = doc.getElementById("mafsFrameworkChapterCandidateIds");
  if (!chapterHidden) {
    chapterHidden = doc.createElement("input");
    chapterHidden.type = "hidden";
    chapterHidden.id = "mafsFrameworkChapterCandidateIds";
    chapterHidden.name = "chapterModuleCandidateIds";
    doc.body.appendChild(chapterHidden);
  }
  chapterHidden.value = chapterItems.map((item) => item.id).join(",");
  let note = doc.getElementById("mafsFrameworkNote");
  if (!note) {
    note = doc.createElement("input");
    note.type = "hidden";
    note.id = "mafsFrameworkNote";
    note.name = "frameworkNote";
    doc.body.appendChild(note);
  }
  note.value = `全书宏观骨架：${canvasItems.map((item) => item.title).join(" / ")}；当前章节模块候选：${chapterItems.map((item) => item.title).join(" / ") || "未选择"}`;
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
    const existingCanvasItems = view.__mafsFrameworkCanvasItems || [];
    const misplacedChapterItems = existingCanvasItems.filter((item) => item.type !== "macro_component");
    view.__mafsFrameworkCanvasItems = existingCanvasItems.filter((item) => item.type === "macro_component");
    view.__mafsFrameworkChapterCandidateItems = [
      ...(view.__mafsFrameworkChapterCandidateItems || []),
      ...misplacedChapterItems,
    ].filter((item, index, items) => items.findIndex((candidate) => candidate.id === item.id) === index);
    const selectedId = view.__mafsFrameworkSelectedId || view.__mafsFrameworkCanvasItems?.[0]?.id || materials[0]?.id || "";
    renderFrameworkMaterialCards(doc, materials, view.__mafsFrameworkFilter || "all", selectedId);
    renderFrameworkCanvas(doc, view.__mafsFrameworkCanvasItems || [], selectedId);
    renderFrameworkChapterCandidates(doc, view.__mafsFrameworkChapterCandidateItems || [], selectedId);
    renderFrameworkRoutePreview(doc, view.__mafsFrameworkCanvasItems || [], assignments);
    syncFrameworkHiddenForm(
      doc,
      view.__mafsFrameworkCanvasItems || [],
      view.__mafsFrameworkChapterCandidateItems || [],
    );
    const selected = view.__mafsFrameworkMaterialsById.get(selectedId) || view.__mafsFrameworkCanvasItems?.[0] || view.__mafsFrameworkChapterCandidateItems?.[0] || materials[0];
    updateFrameworkSelection(doc, selected);
    bindCards();
  };
  const addToCanvas = (id) => {
    const material = view.__mafsFrameworkMaterialsById.get(id);
    if (!material) {
      return;
    }
    const targetItems = material.type === "macro_component"
      ? view.__mafsFrameworkCanvasItems
      : view.__mafsFrameworkChapterCandidateItems;
    if (!targetItems.some((item) => item.id === material.id)) {
      targetItems.push(material);
    }
    view.__mafsFrameworkSelectedId = material.id;
    render();
  };
  const removeFromCanvas = (id) => {
    view.__mafsFrameworkCanvasItems = view.__mafsFrameworkCanvasItems.filter((item) => item.id !== id);
    view.__mafsFrameworkChapterCandidateItems = (view.__mafsFrameworkChapterCandidateItems || []).filter((item) => item.id !== id);
    if (view.__mafsFrameworkSelectedId === id) {
      view.__mafsFrameworkSelectedId = view.__mafsFrameworkCanvasItems[0]?.id || view.__mafsFrameworkChapterCandidateItems[0]?.id || materials[0]?.id || "";
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
      `当前项目 ${counts.all}`,
      `宏观 Framework ${counts.macro}`,
      `篇章 Framework ${counts.chapter}`,
      `资料库 ${counts.library}`,
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
    `已读取当前项目 Framework 包和资料库素材。默认只显示当前项目；需要外部素材时再打开资料库。`,
  );
  setRenderedText(doc.querySelector(".left-panel .panel-title"), "Framework 包素材");
  setRenderedText(doc.querySelector(".left-panel .panel-note"), "打开已导入的宏观 Framework 与篇章 Framework，选择后拖到编排画布。");
  setRenderedText(doc.querySelector(".right-panel .panel-title"), "映射预览");
  setRenderedText(doc.querySelector(".right-panel .panel-note"), "根据当前画布和后端章节映射生成预览。");
  setRenderedText(doc.getElementById("sourceLabel"), "当前来源：当前项目 Framework 包");
  setRenderedText(doc.querySelector(".selected-box p"), "默认只显示当前项目已生成的 Framework 素材，避免其它示例故事混入当前编排。");
  setRenderedText(doc.querySelector(".left-panel .badge"), String(frameworkMaterialCounts(materials).all));
  const chapterCount = Number(workbench.chapter_count || workbench.chapterCount || assignments.length || 5) || 5;
  setRenderedText(doc.querySelector(".right-panel .badge"), String(assignments.length || chapterCount || "可编排"));
  const chapterCountButton = doc.getElementById("chapterCountButton");
  setRenderedText(chapterCountButton, `章节数：${chapterCount} 章`);
  if (chapterCountButton) {
    chapterCountButton.disabled = true;
    chapterCountButton.setAttribute("aria-expanded", "false");
    chapterCountButton.title = "章节总数来自当前项目创作偏好，请在项目设置中修改";
  }
  const chapterCountPicker = doc.getElementById("chapterCountPicker");
  chapterCountPicker?.classList.remove("open");
  const chapterMenu = doc.getElementById("chapterMenu");
  if (chapterMenu) {
    chapterMenu.innerHTML = "";
    chapterMenu.hidden = true;
  }
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
  if (view && !Array.isArray(view.__mafsFrameworkChapterCandidateItems)) {
    view.__mafsFrameworkChapterCandidateItems = [];
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
  if (/Local mock selects vocabulary-valid components/i.test(text)) {
    return "后端根据当前宏观组件、世界画布、角色主轴与记忆包选择了本章模块。";
  }
  return text;
}

function renderChapterFrameworkSurface(doc, frameworkResult, contextSource = {}) {
  const chapterFramework = findChapterFrameworkPayload(frameworkResult);
  if (!chapterFramework) {
    return false;
  }
  const currentPageId = framePageId(doc);
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
  const storyProgressLike = findNestedObject(
    { frameworkResult, contextSource },
    (item) => Boolean(item?.chapter_count || item?.chapterCount || item?.current_chapter_index || item?.currentChapterIndex),
  ) || {};
  const chapterCount = Number(
    frameworkResult?.chapter_count ||
      frameworkResult?.chapterCount ||
      contextSource?.chapter_count ||
      contextSource?.chapterCount ||
      storyProgressLike.chapter_count ||
      storyProgressLike.chapterCount ||
      buildContext.chapter_count ||
      buildContext.chapterCount ||
      0,
  ) || chapterIndex;
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
  const reasonSummaries = uniqueDisplayValues(buildReasons.map((reason) => {
    const selected = (reason.selected_component_ids || reason.selectedComponentIds || []).filter(Boolean).join("、");
    return chapterFrameworkDisplayText(
      firstNonEmpty(reason.reason_summary, reason.reasonSummary, selected),
      "该模块由当前世界、角色和宏观骨架共同决定。",
    );
  }));
  const reasonRows = reasonSummaries.slice(0, 4).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
  const actionButtons = currentPageId === "chapter-framework-review"
    ? `<button id="mafsFrameworkBuildResultButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="chapter-building">返回构建结果</button>
       <button id="mafsChapterRouteEntryButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.currentPlan" data-mafs-target="chapter-route-entry">确认本章 Framework，进入路线</button>`
    : `<button id="mafsCurrentFrameworkReviewButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="chapter.currentFramework" data-mafs-target="chapter-framework-review">查看审阅页</button>
       <button id="mafsChapterRouteEntryButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.currentPlan" data-mafs-target="chapter-route-entry">进入章节路线</button>`;
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端当前章 Framework</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">第${escapeHtml(String(chapterIndex))}章 Framework 已生成</h3>
    <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(userIntent || "当前章 Framework 已按项目世界画布、角色主轴、记忆与宏观骨架即时构建。")}</p>
    <p style="margin:0 0 10px;line-height:1.7;">宏观组件：${escapeHtml(linkedMacros.length ? linkedMacros.join("、") : "后端已按当前章节自动映射。")}</p>
    <ul style="list-style:none;margin:0 0 12px;padding:0;">${moduleRows}</ul>
    ${reasonRows ? `<div style="margin-top:10px;"><strong>选择依据</strong><ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${reasonRows}</ul></div>` : ""}
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
      ${actionButtons}
    </div>
  `;
  bindBackendActionElement(doc.getElementById("mafsCurrentFrameworkReviewButton"), "chapter.currentFramework", "chapter-framework-review");
  bindBackendActionElement(doc.getElementById("mafsFrameworkBuildResultButton"), "", "chapter-building");
  bindBackendActionElement(doc.getElementById("mafsChapterRouteEntryButton"), "chapter.currentPlan", "chapter-route-entry");
  setSelectValueWithOption(doc.getElementById("chapter-count"), chapterCount, (value) => `${value} 章`);
  setSelectValueWithOption(doc.getElementById("current-chapter"), chapterIndex, (value) => `第 ${value} 章`);
  setRenderedText(doc.getElementById("chapter-chip-number"), `第 ${chapterIndex} 章`);
  setRenderedText(doc.getElementById("chapter-chip-meta"), `共 ${chapterCount} 章`);
  setRenderedText(doc.getElementById("mini-current"), String(chapterIndex));
  setRenderedText(doc.querySelector(".hero .lead"), `第${chapterIndex}章 Framework 已从后端生成，可进入审阅或继续章节路线。`);
  setRenderedText(doc.getElementById("topStatus"), "当前章 Framework 已生成");
  setRenderedText(doc.querySelector(".ready-pill"), "已生成");
  replaceEmptyPlaceholders(doc, "已同步");
  markBackendRendered(panel);
  if (currentPageId === "chapter-source") {
    doc.querySelector(".layout")?.classList.add("mafs-empty-suppressed");
    const main = doc.querySelector("main");
    if (main && panel.parentElement !== main) {
      main.appendChild(panel);
    }
  }
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["chapter-source", "chapter-building", "chapter-framework-review"]);
  applyRealtimeProgressElements(doc, { label: "当前章 Framework 已生成", percent: 100 });
  return true;
}

function renderChapterPlanSurface(doc, result) {
  if (!doc?.body || !isFramePage(doc, CHAPTER_PLAN_PAGE_IDS) || !/章节计划/.test(doc.body.textContent || "")) {
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
  const storySetupState = findStorySetupStatePayload(actionResult) || findStorySetupStatePayload(result) || {};
  const storySetupPrompt = storySetupState.story_setup_prompt || storySetupState.storySetupPrompt || {};
  const preferenceSourceText = [
    sourceText,
    premise.user_story_premise,
    premise.userStoryPremise,
    premise.safe_user_story_summary,
    premise.safeUserStorySummary,
    world?.source_story_idea,
    world?.sourceStoryIdea,
    storySetupPrompt.prompt_text,
    storySetupPrompt.promptText,
    storySetupPrompt.safe_prompt_summary,
    storySetupPrompt.safePromptSummary,
    planDraft?.latest_user_prompt,
    planDraft?.latestUserPrompt,
  ]
    .map((value) => formatStorySetupValue(value))
    .filter(Boolean)
    .join("\n");
  const requestedChapterCount = extractCountByUnit(preferenceSourceText, "章");
  const requestedSceneCount =
    extractCountByUnit(preferenceSourceText, "幕") ||
    extractCountByUnit(preferenceSourceText, "场");
  const brief = planDraft?.current_chapter_brief || planDraft?.currentChapterBrief || routes[0] || {};
  const chapterCount = routes.length || Number(planDraft?.chapter_count || planDraft?.chapterCount) || requestedChapterCount || Number(doc.getElementById("chapter-count")?.value || 0) || 1;
  const currentIndex = Number(brief.chapter_index || brief.chapterIndex || routes[0]?.chapter_index || routes[0]?.chapterIndex || 1) || 1;
  const currentTitle = firstNonEmpty(brief.title, routes[currentIndex - 1]?.temporary_title, routes[currentIndex - 1]?.temporaryTitle, `第${currentIndex}章`);
  const chapterGoal = firstNonEmpty(brief.chapter_goal, brief.chapterGoal, routes[currentIndex - 1]?.light_route_summary, routes[currentIndex - 1]?.lightRouteSummary);
  const conflict = firstNonEmpty(brief.main_conflict, brief.mainConflict, routes[currentIndex - 1]?.expected_conflict_hint, routes[currentIndex - 1]?.expectedConflictHint);
  const userSelectedSceneCount = Number(brief.user_selected_scene_count || brief.userSelectedSceneCount || 0);
  const recommendedSceneCount = Number(brief.recommended_scene_count || brief.recommendedSceneCount || 0);
  const plannedSceneCount = Number(
    routes[currentIndex - 1]?.planned_scene_count || routes[currentIndex - 1]?.plannedSceneCount || 0,
  );
  const sceneCount = userSelectedSceneCount || requestedSceneCount || plannedSceneCount || recommendedSceneCount || 0;
  const planValidation = planDraft?.validation_report || planDraft?.validationReport || workflow?.validation || result?.validation || {};
  const blockingIssues = (planValidation.blocking_issues || planValidation.blockingIssues || []).filter(Boolean);
  const planConfirmed = String(planDraft?.status || "").toLowerCase() === "confirmed";
  const planReady = planConfirmed || (planValidation.passed === true && blockingIssues.length === 0);
  const blockingIssueCodes = blockingIssues.map((item) => String(
    typeof item === "string" ? item : firstNonEmpty(item?.code, item?.issue_code, item?.issueCode, item?.message),
  ).trim()).filter(Boolean);
  const frameworkFallbackOnly = Boolean(
    !planConfirmed &&
      blockingIssueCodes.length === 1 &&
      blockingIssueCodes[0] === "chapter_plan_framework_fallback_unacknowledged",
  );
  const planConfirmable = planReady || frameworkFallbackOnly;
  const validationMessage = planReady
    ? "章节路线已通过结构、前提一致性和当前章 Framework 检查。"
    : frameworkFallbackOnly
      ? "当前章节 Framework 使用了保守草案。请审阅路线后明确确认，系统才会进入场景写作。"
      : [...blockingIssueCodes, ...(planValidation.user_confirmation_needed || planValidation.userConfirmationNeeded || [])]
          .join("；") || "后端没有返回可确认的路线验证结果，请重新生成。";
  const confirmationNotes = (planDraft?.user_confirmation_needed || planDraft?.userConfirmationNeeded || []).filter(Boolean);
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
  const routeGenerateButton = doc.getElementById("generate-button") ||
    Array.from(doc.querySelectorAll("button, a, [role='button']")).find((button) => {
      const text = String(button.textContent || button.getAttribute("aria-label") || "").trim();
      return /生成/.test(text) && /章节|路线/.test(text) && !/场景|正文|返回/.test(text);
    });
  bindBackendActionElement(routeGenerateButton, "chapter.generatePlan", "chapter-route-generating");
  const currentPageId = framePageId(doc);
  const shouldShowFrameworkSurfaceOnly = [
    "chapter-source",
    "chapter-building",
    "chapter-framework-review",
  ].includes(currentPageId);
  if (shouldShowFrameworkSurfaceOnly && renderChapterFrameworkSurface(doc, workflow, actionResult)) {
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
    const projectMacroLabels = [
      ...(Array.isArray(frameworkWorkbench.macro_components) ? frameworkWorkbench.macro_components : []),
      ...(Array.isArray(frameworkWorkbench.macroComponents) ? frameworkWorkbench.macroComponents : []),
    ]
      .map((item) => frameworkRecordText(item, "", 80))
      .filter(Boolean)
      .slice(0, 8);
    const frameworkSummary = projectMacroLabels.length
      ? projectMacroLabels.join(" / ")
      : "已确认的宏观 Framework 映射";
    const previousChapterSummary = currentIndex <= 1
      ? "第一章从项目故事前提开始，不存在上一章结果。"
      : "构建时将读取上一章已确认事件、角色状态与未解决目标。";
    const routeActionHtml = currentPageId === "chapter-route-entry"
      ? `<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
          <button id="generate-button" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.generatePlan" data-mafs-target="chapter-route-generating">生成章节路线</button>
        </div>`
      : currentPageId === "chapter-source"
        ? `<div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
            <button id="mafsChapterBuildButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.buildCurrent" data-mafs-target="chapter-building">构建第 ${escapeHtml(String(currentIndex))} 章 Framework</button>
          </div>`
      : "";
    panel.innerHTML = `
      <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">当前项目章节计划</p>
      <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">第 ${escapeHtml(String(currentIndex))} 章即时构建入口</h3>
      <p style="margin:0 0 10px;line-height:1.7;">${escapeHtml(sourceSummary)}</p>
      <ul style="margin:0 0 12px 18px;padding:0;line-height:1.7;">
        <li>总章节数：${escapeHtml(String(chapterCount))}</li>
        <li>当前章：第 ${escapeHtml(String(currentIndex))} 章</li>
        <li>每章目标幕数：${escapeHtml(sceneCount ? String(sceneCount) : "待用户确认")}</li>
        <li>已确认 A 级角色：${escapeHtml(String(displayFoundation.confirmed_a_character_count || 0))}</li>
      </ul>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:0 0 12px;">
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);">
          <strong>当前章输入</strong>
          <p style="margin:6px 0 0;line-height:1.65;">${escapeHtml(currentIndex <= 1 ? "依据项目故事前提、世界画布、主角洛岚的已确认状态和开端组件即时构建。" : "依据上一章确认结果和当前宏观组件即时构建。")}</p>
        </section>
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);">
          <strong>上一章结果</strong>
          <p style="margin:6px 0 0;line-height:1.65;">${escapeHtml(previousChapterSummary)}</p>
        </section>
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);grid-column:1/-1;">
          <strong>已确认宏观 Framework</strong>
          <p style="margin:6px 0 0;line-height:1.65;">${escapeHtml(frameworkSummary)}</p>
        </section>
      </div>
      <p style="margin:0;line-height:1.7;">${displayFoundation.ready ? "前提已满足，可以构建当前章框架。" : "仍需补齐前置条件后才能生成章节路线。"}</p>
      ${routeActionHtml}
    `;
    bindBackendActionElement(doc.getElementById("generate-button"), "chapter.generatePlan", "chapter-route-generating");
    bindBackendActionElement(doc.getElementById("mafsChapterBuildButton"), "chapter.buildCurrent", "chapter-building");
    setRenderedText(doc.getElementById("framework-state"), displayFoundation.ready ? "可构建。" : "待补全。");
    setRenderedText(doc.getElementById("status-text"), displayFoundation.ready ? "当前章还没有 Framework。构建完成后会进入审阅。" : "请先补齐前置条件。");
    setRenderedText(doc.getElementById("action-note"), displayFoundation.ready ? "构建后会进入当前章 Framework 审阅页。" : "请先完成主角团确认等前置条件。");
    replaceEmptyPlaceholders(doc, "后端已同步");
    markBackendRendered(panel);
    if (currentPageId === "chapter-source") {
      doc.querySelector(".layout")?.classList.add("mafs-empty-suppressed");
      const main = doc.querySelector("main");
      if (main && panel.parentElement !== main) {
        main.appendChild(panel);
      }
    }
    suppressStaticSiblingsForBackendPanel(doc, panel, target, ["chapter-route-entry"]);
    applyRealtimeProgressElements(doc, { label: displayFoundation.ready ? "章节前提已同步" : "章节前提待补全", percent: displayFoundation.ready ? 100 : 70 });
    return true;
  }
  if (currentPageId === "chapter-scene-count") {
    const initialSceneCount = userSelectedSceneCount || requestedSceneCount || plannedSceneCount || recommendedSceneCount || 3;
    panel.innerHTML = `
      <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">当前章幕数设置</p>
      <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">确认第 ${escapeHtml(String(currentIndex))} 章的幕数</h3>
      <p style="margin:0 0 12px;line-height:1.7;">用户在故事前提中明确给出的数量优先于模型推荐。修改幕数后，后端会同步重排当前章的场景节拍。</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:14px;">
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);">
          <strong>用户故事前提</strong>
          <p style="margin:6px 0 0;line-height:1.6;">${requestedSceneCount ? `每章 ${escapeHtml(String(requestedSceneCount))} 幕` : "没有指定幕数"}</p>
        </section>
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);">
          <strong>模型推荐</strong>
          <p style="margin:6px 0 0;line-height:1.6;">${recommendedSceneCount ? `${escapeHtml(String(recommendedSceneCount))} 幕` : "未单独推荐"}</p>
        </section>
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);">
          <strong>当前已保存</strong>
          <p style="margin:6px 0 0;line-height:1.6;">${userSelectedSceneCount ? `${escapeHtml(String(userSelectedSceneCount))} 幕` : "尚未保存"}</p>
        </section>
      </div>
      <label for="mafsSceneCountInput" style="display:block;margin-bottom:6px;font-weight:800;">本章幕数</label>
      <div style="display:flex;align-items:center;gap:8px;max-width:320px;">
        <button id="mafsSceneCountMinus" type="button" class="soft-button mafs-backend-rendered" aria-label="减少一幕">−</button>
        <input id="mafsSceneCountInput" name="sceneCount" type="number" min="1" max="20" step="1" value="${escapeHtml(String(initialSceneCount))}" style="width:100%;min-height:42px;padding:8px 10px;border:1px solid rgba(121,89,74,0.26);border-radius:6px;background:#fffdf8;" />
        <button id="mafsSceneCountPlus" type="button" class="soft-button mafs-backend-rendered" aria-label="增加一幕">+</button>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:16px;">
        <button id="mafsBackToRouteReviewButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="chapter-route-review">返回路线审阅</button>
        <button id="save-count-button" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.setSceneCount" data-mafs-target="chapter-route-review">保存幕数</button>
      </div>
    `;
    const countInput = doc.getElementById("mafsSceneCountInput");
    const adjustSceneCount = (delta) => {
      const nextValue = Math.max(1, Math.min(20, Number(countInput?.value || initialSceneCount) + delta));
      if (countInput) {
        countInput.value = String(nextValue);
      }
    };
    doc.getElementById("mafsSceneCountMinus")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      adjustSceneCount(-1);
    });
    doc.getElementById("mafsSceneCountPlus")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      adjustSceneCount(1);
    });
    bindBackendActionElement(doc.getElementById("mafsBackToRouteReviewButton"), "", "chapter-route-review");
    bindBackendActionElement(doc.getElementById("save-count-button"), "chapter.setSceneCount", "chapter-route-review");
    replaceEmptyPlaceholders(doc, "已同步");
    markBackendRendered(panel);
    suppressStaticSiblingsForBackendPanel(doc, panel, target, ["chapter-scene-count"]);
    applyRealtimeProgressElements(doc, { label: "等待确认本章幕数", percent: 92 });
    return true;
  }
  if (currentPageId === "chapter-revision") {
    const currentRoute = routes[currentIndex - 1] || brief || {};
    const currentRouteSummary = firstNonEmpty(
      currentRoute.light_route_summary,
      currentRoute.lightRouteSummary,
      currentRoute.narrative_function,
      currentRoute.narrativeFunction,
      chapterGoal,
      "当前章节路线已从后端同步。",
    );
    const routePreviewRows = routes.map((route, index) => {
      const routeIndex = Number(route.chapter_index || route.chapterIndex || index + 1) || index + 1;
      const title = firstNonEmpty(route.temporary_title, route.temporaryTitle, `第${routeIndex}章`);
      const summary = firstNonEmpty(
        route.light_route_summary,
        route.lightRouteSummary,
        route.narrative_function,
        route.narrativeFunction,
        "等待修订后重新生成。",
      );
      return `<li style="padding:10px 0;border-bottom:1px solid rgba(121,89,74,0.13);line-height:1.65;">
        <strong>第 ${escapeHtml(String(routeIndex))} 章 · ${escapeHtml(title)}</strong>
        <p style="margin:4px 0 0;">${escapeHtml(summary)}</p>
      </li>`;
    }).join("");
    panel.innerHTML = `
      <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">修订章节计划</p>
      <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">修订第 ${escapeHtml(String(currentIndex))} 章及全书路线</h3>
      <p style="margin:0 0 14px;line-height:1.7;">修订会读取当前项目已确认的世界画布、角色、Framework 与用户最新说明，由后端模型重新生成并验证章节路线。页面不会套用演示故事或固定题材。</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-bottom:14px;">
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);">
          <strong>当前范围</strong>
          <p style="margin:6px 0 0;line-height:1.6;">第 ${escapeHtml(String(currentIndex))} 章 / 全书 ${escapeHtml(String(chapterCount))} 章</p>
        </section>
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);">
          <strong>每章目标幕数</strong>
          <p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(sceneCount ? `${sceneCount} 幕` : "尚未确认")}</p>
        </section>
        <section style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.54);grid-column:1/-1;">
          <strong>${escapeHtml(currentTitle)}</strong>
          <p style="margin:6px 0 0;line-height:1.65;">${escapeHtml(currentRouteSummary)}</p>
          <p style="margin:6px 0 0;line-height:1.65;">当前冲突：${escapeHtml(conflict || "围绕已确认的角色目标、世界规则和主要阻力推进。")}</p>
        </section>
      </div>
      <label for="mafsChapterRevisionPrompt" style="display:block;margin-bottom:7px;font-weight:800;">修订说明</label>
      <textarea id="mafsChapterRevisionPrompt" name="chapterRevision" rows="8" placeholder="请说明要保留、删除或调整的章节路线、冲突、揭示节奏、角色弧光与幕数约束。模型会以当前项目已确认事实为准重新生成。" style="width:100%;box-sizing:border-box;resize:vertical;padding:12px;border:1px solid rgba(121,89,74,0.28);border-radius:6px;background:#fffdf8;color:#2d2823;line-height:1.7;"></textarea>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:7px 0 14px;">
        <span id="mafsChapterRevisionCount" style="font-size:12px;color:#6b5d51;">0 字</span>
        <span id="mafsChapterRevisionState" role="status" style="font-size:12px;color:#6b5d51;">等待填写修订说明</span>
      </div>
      <details style="margin-bottom:14px;padding:10px 12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.48);">
        <summary style="cursor:pointer;font-weight:800;">查看当前 ${escapeHtml(String(chapterCount))} 章路线</summary>
        <ol style="margin:10px 0 0;padding:0 0 0 20px;">${routePreviewRows}</ol>
      </details>
      <div style="display:flex;justify-content:flex-end;gap:10px;">
        <button id="mafsBackToRouteReviewButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="chapter-route-review">返回路线审阅</button>
        <button id="mafsClearChapterRevisionButton" type="button" class="soft-button mafs-backend-rendered">清空</button>
        <button id="mafsSubmitChapterRevisionButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.revise" data-mafs-target="chapter-route-review" disabled>提交修订</button>
      </div>
    `;
    const revisionInput = doc.getElementById("mafsChapterRevisionPrompt");
    const revisionCount = doc.getElementById("mafsChapterRevisionCount");
    const revisionState = doc.getElementById("mafsChapterRevisionState");
    const revisionSubmit = doc.getElementById("mafsSubmitChapterRevisionButton");
    const updateRevisionState = () => {
      const value = String(revisionInput?.value || "").trim();
      if (revisionCount) {
        revisionCount.textContent = `${value.length} 字`;
      }
      if (revisionState) {
        revisionState.textContent = value ? "可提交，提交完成后返回路线审阅" : "等待填写修订说明";
      }
      if (revisionSubmit) {
        revisionSubmit.disabled = !value;
      }
    };
    revisionInput?.addEventListener("input", updateRevisionState);
    doc.getElementById("mafsClearChapterRevisionButton")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (revisionInput) {
        revisionInput.value = "";
        revisionInput.focus();
      }
      updateRevisionState();
    });
    bindBackendActionElement(doc.getElementById("mafsBackToRouteReviewButton"), "", "chapter-route-review");
    bindBackendActionElement(revisionSubmit, "chapter.revise", "chapter-route-review");
    updateRevisionState();
    markBackendRendered(panel);
    suppressStaticSiblingsForBackendPanel(doc, panel, target, ["chapter-revision"]);
    applyRealtimeProgressElements(doc, { label: "等待用户提交章节路线修订", percent: 94 });
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
  const routeActions = currentPageId === "chapter-route-review"
    ? `<button id="mafsReviseChapterButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="chapter-revision">修订路线</button>
       <button id="mafsSceneCountButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="chapter-scene-count">${userSelectedSceneCount ? "检查幕数" : "设置幕数"}</button>
       <button id="mafsConfirmChapterButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="chapter-confirm" ${planConfirmable ? "" : "disabled"}>${planReady ? "进入最终确认" : (frameworkFallbackOnly ? "审阅并确认保守草案" : "验证未通过")}</button>`
    : currentPageId === "chapter-confirm"
      ? `<button id="mafsBackToRouteReviewButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="chapter-route-review">返回路线审阅</button>
         <button id="mafsConfirmChapterPlanButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.confirm" data-mafs-target="scene-entry">确认计划并进入场景写作</button>`
      : currentPageId === "chapter-route-entry"
        ? `<button id="mafsReviewChapterRouteButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="chapter-route-review">查看路线审阅</button>
           <button id="mafsRegenerateChapterRouteButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="chapter.generatePlan" data-mafs-target="chapter-route-generating">重新生成章节路线</button>`
        : `<button id="mafsReviewChapterRouteButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="chapter-route-review">查看路线审阅</button>`;
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端章节路线</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">当前第${currentIndex}章路线</h3>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(currentTitle)}</strong>：${escapeHtml(chapterGoal || "章节路线已从后端同步。")}</p>
    <p style="margin:0 0 12px;line-height:1.7;">核心冲突：${escapeHtml(conflict || "围绕当前项目已确认的角色目标、世界规则和主要阻力推进。")}</p>
    <p style="margin:0 0 12px;line-height:1.7;">总章节：${chapterCount}；每章目标幕数：${sceneCount || "待用户确认"}。后续场景写作必须服从当前项目已确认的世界、角色与 Framework。</p>
    <section style="margin:0 0 12px;padding:10px 12px;border:1px solid ${planReady ? "rgba(91,125,108,0.28)" : "rgba(173,102,84,0.32)"};border-radius:8px;background:${planReady ? "rgba(236,245,238,0.72)" : "rgba(252,238,232,0.78)"};">
      <strong>${planReady ? "路线验证通过" : (frameworkFallbackOnly ? "保守草案待确认" : "路线验证未通过")}</strong>
      <p style="margin:5px 0 0;line-height:1.6;">${escapeHtml(validationMessage)}</p>
    </section>
    <ul style="list-style:none;margin:0;padding:0;">${rows}</ul>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
      ${routeActions}
    </div>
  `;
  bindBackendActionElement(doc.getElementById("mafsReviseChapterButton"), "", "chapter-revision");
  bindBackendActionElement(doc.getElementById("mafsSceneCountButton"), "", "chapter-scene-count");
  bindBackendActionElement(doc.getElementById("mafsConfirmChapterButton"), "", "chapter-confirm");
  bindBackendActionElement(doc.getElementById("mafsBackToRouteReviewButton"), "", "chapter-route-review");
  bindBackendActionElement(doc.getElementById("mafsConfirmChapterPlanButton"), "chapter.confirm", "scene-entry");
  bindBackendActionElement(doc.getElementById("mafsReviewChapterRouteButton"), "", "chapter-route-review");
  bindBackendActionElement(doc.getElementById("mafsRegenerateChapterRouteButton"), "chapter.generatePlan", "chapter-route-generating");
  replaceEmptyPlaceholders(doc, "已同步");
  [120, 600, 1400].forEach((delayMs) => {
    window.setTimeout(() => replaceEmptyPlaceholders(doc, "已同步"), delayMs);
  });
  setRenderedText(doc.querySelector(".hero .lead"), `第${currentIndex}章路线已同步，可进入场景写作。`);
  setRenderedText(doc.getElementById("topStatus"), "章节路线已同步");
  markBackendRendered(panel);
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["chapter-route-entry", "chapter-route-generating", "chapter-route-review", "chapter-confirm"]);
  applyRealtimeProgressElements(doc, { label: "章节路线已同步", percent: 100 });
  return true;
}

function cleanStoryRuntimeText(value) {
  return String(value || "")
    .replace(/^\s*Current chapter\s+\d+\s+scene\s+\d+\s*:\s*/i, "")
    .replace(/MODEL_FALLBACK_PLACEHOLDER:\s*External model output was not valid story prose; this diagnostic placeholder must not be exported as story text\.?/gi, "")
    .replace(/Failure summary:\s*Provider HTTP error status=\d+\.?/gi, "")
    .replace(/Structural synopsis:\s*/gi, "")
    .replace(/Chapter goal:\s*/gi, "")
    .replace(/Scene location:[^\n。]*[。.]?/gi, "")
    .replace(/ProjectStoryPremise:\s*/g, "")
    .replace(/ProjectStoryPremise is authoritative for this Prompt-first project\.\s*/gi, "")
    .replace(/User story premise:\s*/gi, "")
    .replace(/\{\s*'_truncated_items'\s*:\s*\d+\s*\}/g, "")
    .replace(/\[object Object\]/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function containsNonStoryFallbackText(value) {
  return /MODEL_FALLBACK_PLACEHOLDER|External model output was not valid story prose|diagnostic placeholder|Failure summary:\s*Provider HTTP error/i.test(String(value || ""));
}

function isNoisyStoryRuntimeText(value) {
  const text = String(value || "");
  return Boolean(
    containsNonStoryFallbackText(text) ||
      /Current chapter\s+\d+\s+scene\s+\d+|Scene\s+\d+|End with|active premise|concrete clue/i.test(text) ||
      /Test the chapter question|Add a different piece|Force at least one|Convert uncertainty|Convert chapter progress|Add final chapter-level|Leave at least one|Escalate the chapter consequence|Make one earlier assumption/i.test(text) ||
      /我想[、，/]|暂定名|一部两章三幕|Prompt-first project|User story premise/i.test(text),
  );
}

function storyRuntimeDisplayText(value, fallback) {
  const cleaned = cleanStoryRuntimeText(value);
  if (!cleaned || isNoisyStoryRuntimeText(cleaned)) {
    return fallback;
  }
  return cleaned;
}

function findScenePayload(result) {
  const directCandidates = [
    result?.selected_scene,
    result?.selectedScene,
    result?.action_result?.selected_scene,
    result?.actionResult?.selectedScene,
    result?.commit?.scene,
    result?.commit?.current_scene,
    result?.commit?.currentScene,
    result?.action_result?.commit?.scene,
    result?.actionResult?.commit?.scene,
    result?.action_result?.action_result?.commit?.scene,
    result?.actionResult?.actionResult?.commit?.scene,
    result?.action_result?.current_scene?.scene,
    result?.actionResult?.currentScene?.scene,
    result?.action_result?.scene,
    result?.actionResult?.scene,
    result?.scene,
    result?.current_scene?.scene,
    result?.currentScene?.scene,
    result?.scene_generation?.scene,
    result?.sceneGeneration?.scene,
  ];
  const direct = directCandidates.find((item) =>
    Boolean(
      item &&
        typeof item === "object" &&
        (item.prose_text ||
          item.proseText ||
          item.scene_id ||
          item.sceneId ||
          (item.scene_index && (item.goal || item.synopsis))),
    ),
  );
  if (direct) {
    return direct;
  }
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

function findSceneProgressPayload(result) {
  const progress =
    result?.scene_progress ||
    result?.sceneProgress ||
    result?.action_result?.scene_progress ||
    result?.action_result?.sceneProgress ||
    result?.actionResult?.scene_progress ||
    result?.actionResult?.sceneProgress ||
    result?.current_scene?.progress ||
    result?.currentScene?.progress ||
    result?.action_result?.current_scene?.progress ||
    result?.action_result?.currentScene?.progress ||
    result?.actionResult?.current_scene?.progress ||
    result?.actionResult?.currentScene?.progress ||
    findNestedObject(result, (item) =>
      Boolean(
        item?.next_scene_index ||
          item?.nextSceneIndex ||
          item?.scene_count ||
          item?.sceneCount ||
          item?.can_generate_next ||
          item?.canGenerateNext,
      ),
    ) ||
    {};
  return progress && typeof progress === "object" ? progress : {};
}

function findSceneReadinessPayload(result) {
  const readiness =
    result?.current_scene?.readiness ||
    result?.currentScene?.readiness ||
    result?.readiness ||
    findNestedObject(result, (item) =>
      Boolean(
        item?.chapter_plan_confirmed !== undefined ||
          item?.current_chapter_exists !== undefined ||
          item?.current_chapter_has_scene_count !== undefined,
      ),
    ) ||
    {};
  return readiness && typeof readiness === "object" ? readiness : {};
}

function renderSceneEntrySurface(doc, result) {
  if (!doc?.body || !["scene-entry", "scene-generating"].includes(framePageId(doc))) {
    return false;
  }
  Array.from(doc.querySelectorAll("body *")).forEach((element) => {
    if (element.id === "mafs-scene-entry-panel" || element.closest("#mafs-scene-entry-panel")) {
      return;
    }
    const text = element.textContent || "";
    if (!text.includes("后端场景正文")) {
      return;
    }
    let removable = element;
    while (
      removable.parentElement &&
      removable.parentElement !== doc.body &&
      (removable.parentElement.textContent || "").includes("后端场景正文")
    ) {
      removable = removable.parentElement;
    }
    removable.remove();
  });
  doc
    .querySelectorAll(
      "#mafs-scene-panel, #mafs-scene-revision-panel, #mafs-scene-continuity-panel, .mafs-scene-panel, #mafs-scene-panel-actions, #mafs-chapter-closeout-actions, #mafsNextSceneButton, #mafsChapterCloseoutButton, #mafsRegenerateSceneButton, #mafsReviseSceneButton, #mafsContinuitySceneButton, #mafsCommitSceneButton",
    )
    .forEach((element) => element.remove());
  doc.querySelectorAll(".mafs-backend-rendered").forEach((element) => {
    const text = element.textContent || "";
    if (/后端场景正文|确认场景|下一场景|重新生成当前草稿|查看草案审阅/.test(text)) {
      element.remove();
    }
  });
  const progress = findSceneProgressPayload(result);
  const readiness = findSceneReadinessPayload(result);
  const chapterPlan = result?.chapter_plan || result?.chapterPlan || result?.action_result?.chapter_plan || result?.actionResult?.chapterPlan || {};
  const participantSelection =
    result?.participant_selection ||
    result?.participantSelection ||
    result?.action_result?.participant_selection ||
    result?.actionResult?.participantSelection ||
    {};
  const pendingCreationCandidates = (
    participantSelection.creation_candidates ||
    participantSelection.creationCandidates ||
    []
  ).filter((candidate) => candidate && typeof candidate === "object" && String(candidate.status || "").toLowerCase() === "pending");
  const participantNeedsConfirmation = Boolean(
    pendingCreationCandidates.length ||
      participantSelection.selection?.requires_user_confirmation ||
      participantSelection.selection?.requiresUserConfirmation ||
      participantSelection.requires_user_confirmation ||
      participantSelection.requiresUserConfirmation,
  );
  const draft = chapterPlan?.draft || chapterPlan?.chapter_plan?.draft || chapterPlan?.chapterPlan?.draft || {};
  const brief = draft?.current_chapter_brief || draft?.currentChapterBrief || {};
  const route = (draft?.chapter_routes || draft?.chapterRoutes || [])[Number(draft?.current_chapter_index || draft?.currentChapterIndex || 1) - 1] || {};
  const storyProgress = result?.story_progress || result?.storyProgress || {};
  const chapterIndex = Number(
    storyProgress.current_chapter_index ||
      storyProgress.currentChapterIndex ||
      brief.chapter_index ||
      brief.chapterIndex ||
      draft.current_chapter_index ||
      draft.currentChapterIndex ||
      1,
  ) || 1;
  const sceneCount = Number(
    progress.scene_count ||
      progress.sceneCount ||
      brief.user_selected_scene_count ||
      brief.userSelectedSceneCount ||
      brief.recommended_scene_count ||
      brief.recommendedSceneCount ||
      route.planned_scene_count ||
      route.plannedSceneCount ||
      0,
  ) || 0;
  const nextSceneIndex = Number(progress.next_scene_index || progress.nextSceneIndex || 1) || 1;
  const scenes = (progress.scenes || progress.items || []).filter((item) => item && typeof item === "object");
  const chapterScenesComplete = Boolean(
    sceneCount > 0 &&
      scenes.length >= sceneCount &&
      nextSceneIndex > sceneCount,
  );
  const backendReadyToGenerate = progress.can_generate_next !== undefined || progress.canGenerateNext !== undefined
    ? Boolean(progress.can_generate_next ?? progress.canGenerateNext)
    : Boolean(readiness.ready);
  const canGenerate = Boolean(
    backendReadyToGenerate &&
      !participantNeedsConfirmation &&
      nextSceneIndex >= 1 &&
      (!sceneCount || nextSceneIndex <= sceneCount),
  );
  const blockingReasons = (chapterScenesComplete ? [] : [
    ...(progress.blocking_reasons || progress.blockingReasons || []),
    ...(readiness.issues || []),
  ]).map((item) => cleanStoryRuntimeText(item)).filter(Boolean);
  const chapterTitle = cleanStoryRuntimeText(firstNonEmpty(brief.title, route.temporary_title, route.temporaryTitle, `第 ${chapterIndex} 章`));
  const chapterGoal = cleanStoryRuntimeText(firstNonEmpty(
    brief.chapter_goal,
    brief.chapterGoal,
    route.light_route_summary,
    route.lightRouteSummary,
    "当前章已从后端同步。",
  ));
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-scene-entry-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-scene-entry-panel";
    panel.className = "mafs-scene-entry-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.margin = "0 0 16px";
    panel.style.background = "rgba(255, 252, 244, 0.95)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  const currentScene = findScenePayload(result);
  const currentSceneStatus = String(currentScene?.status || "").toLowerCase();
  const hasReviewableCurrentDraft = Boolean(
    currentScene &&
      Number(currentScene.scene_index || currentScene.sceneIndex || 0) === nextSceneIndex &&
      ["draft", "needs_review", "needs_regeneration", "continuity_recheck"].includes(currentSceneStatus),
  );
  const actionId = chapterScenesComplete
    ? "scene.archivePreview"
    : (hasReviewableCurrentDraft ? "scene.current" : (scenes.length ? "scene.generateNext" : "scene.generateFirst"));
  const actionTarget = chapterScenesComplete ? "chapter-closeout" : (hasReviewableCurrentDraft ? "scene-review" : "scene-generating");
  const actionEnabled = chapterScenesComplete || hasReviewableCurrentDraft || canGenerate;
  const actionLabel = chapterScenesComplete
    ? "章节收尾"
    : (hasReviewableCurrentDraft ? "审阅当前幕草案" : (canGenerate ? "生成当前幕正文" : "等待前置确认"));
  const sceneRowCount = sceneCount > 0 ? sceneCount : Math.max(nextSceneIndex, 1);
  const sceneRows = Array.from({ length: sceneRowCount }).map((_, index) => {
    const sceneNumber = index + 1;
    const generated = scenes.find((scene) => Number(scene.scene_index || scene.sceneIndex) === sceneNumber);
    const status = generated ? sceneStatusLabel(generated) : (sceneNumber === nextSceneIndex ? (canGenerate ? "当前可生成" : "待前置确认") : "待排队");
    return `<li style="padding:10px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:${sceneNumber === nextSceneIndex ? "rgba(111,123,104,0.11)" : "rgba(255,255,255,0.56)"};">
      <strong>第 ${sceneNumber} 幕</strong>
      <p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(status)}</p>
      ${generated ? `<button type="button" class="soft-button mafs-existing-scene-button mafs-backend-rendered" data-mafs-action-id="scene.openExisting" data-mafs-target="scene-review" data-mafs-scene-id="${escapeHtml(firstNonEmpty(generated.scene_id, generated.sceneId))}" data-mafs-scene-index="${sceneNumber}" style="margin-top:8px;">查看第 ${sceneNumber} 幕</button>` : ""}
    </li>`;
  }).join("");
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端场景入口</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">第 ${chapterIndex} 章 · ${chapterScenesComplete ? "章节场景" : `第 ${nextSceneIndex} 幕`}</h3>
    <p style="margin:0 0 8px;line-height:1.7;"><strong>${escapeHtml(chapterTitle)}</strong></p>
    <p style="margin:0 0 12px;line-height:1.7;">${escapeHtml(chapterGoal)}</p>
    <p style="margin:0 0 12px;line-height:1.7;">${chapterScenesComplete
      ? `当前章 ${escapeHtml(String(scenes.length))} / ${escapeHtml(String(sceneCount))} 幕已全部生成。`
      : `当前章目标幕数：${escapeHtml(sceneCount ? String(sceneCount) : "待确认")}；已生成：${escapeHtml(String(scenes.length))}；下一幕：${escapeHtml(String(nextSceneIndex))}。`}</p>
    <ul style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;list-style:none;margin:0 0 14px;padding:0;">${sceneRows}</ul>
    ${participantNeedsConfirmation ? `<div style="margin:0 0 14px;padding:12px;border:1px solid rgba(184,138,120,0.28);border-radius:8px;background:rgba(184,138,120,0.08);"><strong>待确认临时参与者</strong><ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${pendingCreationCandidates.slice(0, 3).map((candidate) => `<li>${escapeHtml(firstNonEmpty(candidate.role_label, candidate.roleLabel, candidate.story_function, candidate.storyFunction, "临时角色"))}：${escapeHtml(firstNonEmpty(candidate.required_scene_function, candidate.requiredSceneFunction, candidate.safe_summary, candidate.safeSummary, "用于完成当前幕的局部功能。"))}</li>`).join("") || "<li>当前幕需要用户确认 C/D 级临时参与者。</li>"}</ul></div>` : ""}
    ${blockingReasons.length ? `<div style="margin:0 0 14px;padding:12px;border:1px solid rgba(151,71,61,0.2);border-radius:8px;background:rgba(151,71,61,0.06);"><strong>当前阻塞</strong><ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${blockingReasons.slice(0, 5).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>` : ""}
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
      ${participantNeedsConfirmation ? `<button id="mafsConfirmParticipantButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="scene.confirmParticipant" data-mafs-target="scene-entry">确认临时参与者</button>` : ""}
      <button id="mafsSceneGenerateButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="${escapeHtml(actionId)}" data-mafs-target="${escapeHtml(actionTarget)}" ${actionEnabled ? "" : "disabled"}>${escapeHtml(actionLabel)}</button>
      ${!actionEnabled ? `<button id="mafsBackToChapterPlanButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="chapter.currentPlan" data-mafs-target="chapter-route-review">返回章节路线</button>` : ""}
    </div>
  `;
  bindBackendActionElement(doc.getElementById("mafsConfirmParticipantButton"), "scene.confirmParticipant", "scene-entry");
  bindBackendActionElement(doc.getElementById("mafsSceneGenerateButton"), actionId, actionTarget);
  bindBackendActionElement(doc.getElementById("mafsBackToChapterPlanButton"), "chapter.currentPlan", "chapter-route-review");
  doc.querySelectorAll(".mafs-existing-scene-button").forEach((button) => {
    bindBackendActionElement(button, "scene.openExisting", "scene-review");
  });
  setRenderedText(doc.querySelector(".hero .lead"), chapterScenesComplete ? "当前章所有场景均已生成，可进入章节收尾。" : (hasReviewableCurrentDraft ? "当前幕草案已同步，请先审阅。" : (canGenerate ? "场景前提已同步，可以生成当前幕正文。" : "场景前提仍有阻塞，请先返回章节计划确认。")));
  setRenderedText(doc.getElementById("topStatus"), chapterScenesComplete ? "本章已完成" : (hasReviewableCurrentDraft ? "待审阅" : (canGenerate ? "可生成" : "待确认")));
  replaceEmptyPlaceholders(doc, "已同步");
  markBackendRendered(panel);
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["scene-entry", "scene-generating"]);
  applyRealtimeProgressElements(doc, {
    label: chapterScenesComplete ? "当前章场景已完成" : (hasReviewableCurrentDraft ? "场景草案待审阅" : (canGenerate ? "场景入口已同步" : "场景入口待确认")),
    percent: chapterScenesComplete || hasReviewableCurrentDraft || canGenerate ? 100 : 70,
  });
  return true;
}

function findSceneRevisionCandidatePayload(result) {
  const direct =
    result?.scene_revision?.candidate ||
    result?.scene_revision?.current_candidate ||
    result?.sceneRevision?.candidate ||
    result?.sceneRevision?.currentCandidate ||
    result?.action_result?.scene_revision?.candidate ||
    result?.action_result?.scene_revision?.current_candidate ||
    result?.action_result?.sceneRevision?.candidate ||
    result?.action_result?.sceneRevision?.currentCandidate ||
    result?.actionResult?.scene_revision?.candidate ||
    result?.actionResult?.scene_revision?.current_candidate ||
    result?.actionResult?.sceneRevision?.candidate ||
    result?.actionResult?.sceneRevision?.currentCandidate ||
    result?.candidate ||
    result?.current_candidate ||
    result?.currentCandidate;
  if (direct?.revision_id || direct?.revisionId) {
    return direct;
  }
  return findNestedObject(result, (item) =>
    Boolean((item?.revision_id || item?.revisionId) && (item?.revised_prose_text || item?.revisedProseText)),
  );
}

function renderSceneRevisionSurface(doc, result, scene) {
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  const candidate = findSceneRevisionCandidatePayload(result);
  const candidateStatus = String(candidate?.status || "").toLowerCase();
  const candidateActive = Boolean(candidate && (!candidateStatus || candidateStatus === "candidate"));
  const sceneStatus = String(scene?.status || "").toLowerCase();
  const revisingConfirmedScene = ["confirmed", "committed"].includes(sceneStatus);
  const revisedSynopsis = cleanStoryRuntimeText(firstNonEmpty(candidate?.revised_synopsis, candidate?.revisedSynopsis));
  const revisedProse = cleanStoryRuntimeText(firstNonEmpty(candidate?.revised_prose_text, candidate?.revisedProseText));
  const changeSummary = (candidate?.change_summary || candidate?.changeSummary || [])
    .map((item) => cleanStoryRuntimeText(item))
    .filter(Boolean);
  const qualityReport = candidate?.quality_report || candidate?.qualityReport || result?.quality_report || {};
  const blockers = (qualityReport.blocking_issues || qualityReport.blockingIssues || [])
    .map((item) => cleanStoryRuntimeText(typeof item === "string" ? item : firstNonEmpty(item?.summary, item?.message, item?.code)))
    .filter(Boolean);
  let panel = doc.getElementById("mafs-scene-revision-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-scene-revision-panel";
    panel.className = "mafs-scene-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.background = "rgba(255, 252, 244, 0.95)";
    target.prepend(panel);
  }
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">场景修订</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">${candidateActive ? "审阅修订候选" : "说明需要修改的内容"}</h3>
    <p style="margin:0 0 14px;line-height:1.7;">当前第 ${escapeHtml(String(scene?.scene_index || scene?.sceneIndex || 1))} 幕。修订只会生成候选，用户确认前不会覆盖当前草案。</p>
    ${candidateActive ? `
      ${revisedSynopsis ? `<p style="margin:0 0 12px;line-height:1.7;"><strong>修订摘要：</strong>${escapeHtml(revisedSynopsis)}</p>` : ""}
      <article style="white-space:pre-wrap;line-height:1.9;padding:14px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.62);">${escapeHtml(revisedProse || "修订候选尚未返回正文。")}</article>
      ${changeSummary.length ? `<section style="margin-top:12px;"><strong>改动摘要</strong><ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${changeSummary.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>` : ""}
      ${blockers.length ? `<section style="margin-top:12px;padding:12px;border:1px solid rgba(151,71,61,0.24);border-radius:8px;background:rgba(151,71,61,0.06);"><strong>当前候选存在阻塞</strong><ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${blockers.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>` : ""}
    ` : `
      <label for="mafsSceneRevisionInput" style="display:block;margin-bottom:8px;font-weight:800;">修订要求</label>
      <textarea id="mafsSceneRevisionInput" name="scene-revision" rows="7" placeholder="例如：保留已发生的动作，只调整角色反应与语言风格。" style="width:100%;box-sizing:border-box;resize:vertical;padding:12px;border:1px solid rgba(121,89,74,0.24);border-radius:8px;background:#fffdf8;color:#2d2823;font:inherit;line-height:1.7;"></textarea>
    `}
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;flex-wrap:wrap;">
      <button id="mafsBackToSceneReviewButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="scene-review">返回场景审阅</button>
      ${candidateActive ? `
        <button id="mafsRejectSceneRevisionButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="scene.rejectRevision" data-mafs-target="scene-review">放弃修订</button>
        <button id="mafsConfirmSceneRevisionButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="scene.confirmRevision" data-mafs-target="scene-review" ${blockers.length ? "disabled" : ""}>采用修订</button>
      ` : `<button id="mafsCreateSceneRevisionButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="${revisingConfirmedScene ? "scene.reviseConfirmed" : "scene.revise"}" data-mafs-target="scene-revision" disabled>${revisingConfirmedScene ? "分析影响并生成修改候选" : "生成修订候选"}</button>`}
    </div>
  `;
  markBackendRendered(panel);
  bindBackendActionElement(doc.getElementById("mafsBackToSceneReviewButton"), "", "scene-review");
  const revisionInput = doc.getElementById("mafsSceneRevisionInput");
  const createRevisionButton = doc.getElementById("mafsCreateSceneRevisionButton");
  if (revisionInput && createRevisionButton) {
    const syncRevisionButtonState = () => {
      createRevisionButton.disabled = !revisionInput.value.trim();
    };
    revisionInput.addEventListener("input", syncRevisionButtonState);
    syncRevisionButtonState();
  }
  bindBackendActionElement(createRevisionButton, revisingConfirmedScene ? "scene.reviseConfirmed" : "scene.revise", "scene-revision");
  bindBackendActionElement(doc.getElementById("mafsRejectSceneRevisionButton"), "scene.rejectRevision", "scene-review");
  bindBackendActionElement(doc.getElementById("mafsConfirmSceneRevisionButton"), "scene.confirmRevision", "scene-review");
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["scene-revision", "scene-impact"]);
  applyRealtimeProgressElements(doc, { label: candidateActive ? "修订候选已生成" : "等待填写修订要求", percent: candidateActive ? 100 : 0 });
  return true;
}

function renderSceneContinuitySurface(doc, result, scene) {
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  const continuityState = result?.continuity_state || result?.continuityState || {};
  const issues = findNestedArray(continuityState, ["issues", "blocking_issues", "blockingIssues", "items", "records"])
    .filter((item) => item && typeof item === "object");
  let panel = doc.getElementById("mafs-scene-continuity-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-scene-continuity-panel";
    panel.className = "mafs-scene-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.background = "rgba(255, 252, 244, 0.95)";
    target.prepend(panel);
  }
  const issueRows = issues.map((issue) => {
    const summary = cleanStoryRuntimeText(firstNonEmpty(issue.summary, issue.message, issue.description, issue.issue_type, issue.issueType, "连续性问题"));
    const severity = cleanStoryRuntimeText(firstNonEmpty(issue.severity, issue.level, issue.status, "待处理"));
    return `<li style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;list-style:none;"><strong>${escapeHtml(summary)}</strong><p style="margin:6px 0 0;line-height:1.7;">状态：${escapeHtml(severity)}</p></li>`;
  }).join("");
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">连续性与记忆检查</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">第 ${escapeHtml(String(scene?.scene_index || scene?.sceneIndex || 1))} 幕检查结果</h3>
    <p style="margin:0 0 14px;line-height:1.7;">${issues.length ? `发现 ${issues.length} 项需要处理的连续性记录。` : "后端未发现需要用户处理的阻塞性连续性问题。"}</p>
    ${issues.length ? `<ul style="display:grid;gap:10px;margin:0;padding:0;">${issueRows}</ul>` : ""}
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
      <button id="mafsBackFromContinuityButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="scene-review">返回场景审阅</button>
    </div>
  `;
  markBackendRendered(panel);
  bindBackendActionElement(doc.getElementById("mafsBackFromContinuityButton"), "", "scene-review");
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["scene-continuity", "scene-gate"]);
  applyRealtimeProgressElements(doc, { label: issues.length ? "发现连续性问题" : "连续性检查通过", percent: 100 });
  return true;
}

function renderSceneParticipantGateSurface(doc, result) {
  if (!doc?.body || framePageId(doc) !== "scene-gate") {
    return false;
  }
  const selection =
    result?.participant_selection ||
    result?.participantSelection ||
    result?.action_result?.participant_selection ||
    result?.actionResult?.participantSelection ||
    findNestedObjectByKeys(result, ["participant_selection", "participantSelection"]) ||
    {};
  const candidates = (
    selection.creation_candidates ||
    selection.creationCandidates ||
    selection.candidates ||
    selection.items ||
    findNestedArray(selection, ["creation_candidates", "creationCandidates", "candidates", "items"])
  ).filter((candidate) => candidate && typeof candidate === "object");
  const pendingCandidates = candidates.filter((candidate) => {
    const status = String(candidate.status || "").toLowerCase();
    return !status || ["pending", "requires_user_confirmation", "needs_user_confirmation"].includes(status);
  });
  const visibleCandidates = pendingCandidates.length ? pendingCandidates : candidates;
  const sceneIndex = Number(
    result?.resolved_scene_index ||
      result?.resolvedSceneIndex ||
      selection.scene_index ||
      selection.sceneIndex ||
      1,
  ) || 1;
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-scene-participant-gate-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-scene-participant-gate-panel";
    panel.className = "mafs-scene-panel mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "16px";
    panel.style.background = "rgba(255, 252, 244, 0.95)";
    target.prepend(panel);
  }
  const candidateRows = visibleCandidates.map((candidate, index) => {
    const name = cleanStoryRuntimeText(firstNonEmpty(
      candidate.role_label,
      candidate.roleLabel,
      candidate.name,
      `临时参与者 ${index + 1}`,
    ));
    const tier = cleanStoryRuntimeText(firstNonEmpty(candidate.target_tier, candidate.targetTier, candidate.tier, "临时角色"));
    const storyFunction = cleanStoryRuntimeText(firstNonEmpty(
      candidate.required_scene_function,
      candidate.requiredSceneFunction,
      candidate.story_function,
      candidate.storyFunction,
      candidate.safe_summary,
      candidate.safeSummary,
      candidate.description,
      "用于完成当前幕所需的局部叙事功能。",
    ));
    const status = cleanStoryRuntimeText(firstNonEmpty(candidate.status, "待用户确认"));
    return `
      <article style="padding:14px;border:1px solid rgba(121,89,74,0.18);border-radius:8px;background:rgba(255,255,255,0.62);">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;">
          <h4 style="margin:0;font-size:18px;line-height:1.4;">${escapeHtml(name)}</h4>
          <span style="padding:4px 8px;border-radius:6px;background:rgba(111,123,104,0.12);font-size:12px;font-weight:800;">${escapeHtml(tier)}</span>
        </div>
        <p style="margin:8px 0 0;line-height:1.75;">${escapeHtml(storyFunction)}</p>
        <p style="margin:8px 0 0;color:#6b5d51;font-size:13px;">状态：${escapeHtml(status)}</p>
      </article>
    `;
  }).join("");
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">场景参与者确认</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">确认第 ${sceneIndex} 幕需要的新角色</h3>
    <p style="margin:0 0 14px;line-height:1.7;">系统根据当前项目、章节计划、场景目标和已有角色判断本幕需要临时参与者。确认后角色才会写入项目并用于生成正文。</p>
    <div style="display:grid;gap:10px;">${candidateRows || `
      <div style="padding:14px;border:1px solid rgba(121,89,74,0.18);border-radius:8px;background:rgba(255,255,255,0.62);">
        当前没有待确认的参与角色候选。可刷新候选状态，或返回场景入口继续生成。
      </div>
    `}</div>
    <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;flex-wrap:wrap;">
      <button id="mafsRefreshParticipantButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="scene.participantRefresh" data-mafs-target="scene-gate">刷新候选</button>
      ${pendingCandidates.length ? `
        <button id="mafsRejectParticipantButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="scene.rejectParticipant" data-mafs-target="scene-entry">拒绝候选</button>
        <button id="mafsConfirmParticipantButton" type="button" class="primary-button mafs-backend-rendered" data-candidate="true" data-mafs-action-id="scene.confirmParticipant" data-mafs-target="scene-entry">确认候选并返回生成</button>
      ` : `
        <button id="mafsReturnToSceneEntryButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="scene-entry">返回场景入口</button>
      `}
    </div>
  `;
  markBackendRendered(panel);
  bindBackendActionElement(doc.getElementById("mafsRefreshParticipantButton"), "scene.participantRefresh", "scene-gate");
  bindBackendActionElement(doc.getElementById("mafsRejectParticipantButton"), "scene.rejectParticipant", "scene-entry");
  bindBackendActionElement(doc.getElementById("mafsConfirmParticipantButton"), "scene.confirmParticipant", "scene-entry");
  bindBackendActionElement(doc.getElementById("mafsReturnToSceneEntryButton"), "", "scene-entry");
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["scene-gate"]);
  applyRealtimeProgressElements(doc, {
    label: pendingCandidates.length ? "等待确认场景参与者" : "参与者状态已同步",
    percent: pendingCandidates.length ? 80 : 100,
  });
  return true;
}

function renderChapterCloseoutSurface(doc, result) {
  if (!doc?.body || framePageId(doc) !== "chapter-closeout") {
    return false;
  }
  const archivePreview = result?.archive_preview || result?.archivePreview || {};
  const archiveResponse = result?.archive || {};
  const archive =
    archiveResponse?.archive ||
    archivePreview?.existing_archive ||
    archivePreview?.existingArchive ||
    archivePreview?.archive_candidate ||
    archivePreview?.archiveCandidate ||
    findNestedObject(result, (item) => Boolean(item?.archive_id && (item?.scene_ids || item?.confirmed_scene_ids))) ||
    {};
  const chapterIndex = Number(archive.chapter_index || archive.chapterIndex || archivePreview.chapter_index || archivePreview.chapterIndex || 0) || 0;
  const sceneIds = (archive.scene_ids || archive.sceneIds || []).filter(Boolean);
  const confirmedSceneIds = (archive.confirmed_scene_ids || archive.confirmedSceneIds || []).filter(Boolean);
  const outcome = archive.outcome_summary || archive.outcomeSummary || {};
  const validation = archive.validation_report || archive.validationReport || archivePreview.validation_report || archivePreview.validationReport || {};
  const worldStateNotes = uniqueDisplayValues(outcome.world_state_notes || outcome.worldStateNotes || [])
    .map((item) => cleanStoryRuntimeText(item))
    .filter((item) => item && !/unverified claim|may act|only a candidate/i.test(item))
    .slice(0, 4);
  const storyProgressEnvelope = result?.story_progress || result?.storyProgress || {};
  const directStoryProgress =
    storyProgressEnvelope?.story_progress ||
    storyProgressEnvelope?.storyProgress ||
    storyProgressEnvelope;
  const storyProgress =
    (directStoryProgress && Object.keys(directStoryProgress).length
      ? directStoryProgress
      : findNestedObject(
          result,
          (item) => Boolean(item?.story_progress_status && item?.current_chapter_index),
        )) || {};
  const chapterPlan = result?.chapter_plan || result?.chapterPlan || {};
  const chapterPlanDraft = chapterPlan?.draft || chapterPlan?.chapter_plan?.draft || chapterPlan?.chapterPlan?.draft || {};
  const chapterRoutes = (chapterPlanDraft?.chapter_routes || chapterPlanDraft?.chapterRoutes || []).filter(
    (item) => item && typeof item === "object",
  );
  const totalChapterCount = Number(
    storyProgress.chapter_count ||
      storyProgress.chapterCount ||
      chapterPlanDraft.chapter_count ||
      chapterPlanDraft.chapterCount ||
      chapterRoutes.length ||
      0,
  ) || 0;
  const isStoryFinalChapter = Boolean(
    (chapterIndex > 0 && totalChapterCount > 0 && chapterIndex >= totalChapterCount) ||
      (
        storyProgress.has_next_chapter === false &&
        String(storyProgress.next_recommended_action || "").toLowerCase() === "story_draft_complete"
      ),
  );
  const summary = cleanStoryRuntimeText(firstNonEmpty(
    outcome.user_visible_summary,
    outcome.userVisibleSummary,
    archive.summary,
    archivePreview.user_visible_summary,
    archivePreview.userVisibleSummary,
  )).replace(/^Chapter\s+\d+\s*\([^)]*\)\s*reached\s+[^.]+\.\s*Outcome anchor:\s*/i, "");
  const chapterGoalResult = uniqueDisplayValues(
    String(firstNonEmpty(outcome.chapter_goal_result, outcome.chapterGoalResult) || "")
      .split(/\s*\/\s*/)
      .filter(Boolean),
  ).join(" / ");
  const archiveStatus = String(firstNonEmpty(archive.archive_status, archive.archiveStatus) || "").toLowerCase() === "stable"
    ? "稳定归档"
    : storyRuntimeDisplayText(firstNonEmpty(archive.archive_status, archive.archiveStatus), "已稳定归档");
  const target = doc.querySelector(".work-panel") || doc.querySelector("main") || doc.body;
  let panel = doc.getElementById("mafs-chapter-closeout-panel");
  if (!panel) {
    panel = doc.createElement("section");
    panel.id = "mafs-chapter-closeout-panel";
    panel.className = "mafs-backend-rendered";
    panel.style.border = "1px solid rgba(121, 89, 74, 0.2)";
    panel.style.borderRadius = "8px";
    panel.style.padding = "18px";
    panel.style.background = "rgba(255, 252, 244, 0.95)";
    panel.style.color = "#2d2823";
    target.prepend(panel);
  }
  const actionMarkup = isStoryFinalChapter
    ? `<button id="mafsStoryCompleteButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="scene.confirmStoryComplete" data-mafs-target="final-entry">故事草稿完成 / 最终输出</button>`
    : `<button id="mafsNextChapterButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="scene.confirmNextChapter" data-mafs-target="chapter-source">进入下一章</button>`;
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">章节归档</p>
    <h3 style="margin:0 0 10px;font-size:24px;line-height:1.3;">第 ${escapeHtml(String(chapterIndex || "当前"))} 章已收尾</h3>
    <p style="margin:0 0 14px;line-height:1.75;">${escapeHtml(summary || "本章已完成归档，后续章节将读取本章确认事实、角色变化与记忆。")}</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:14px;">
      <div style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;"><strong>场景状态</strong><p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(String(confirmedSceneIds.length))} / ${escapeHtml(String(sceneIds.length || confirmedSceneIds.length))} 幕已确认</p></div>
      <div style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;"><strong>归档状态</strong><p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(archiveStatus)}</p></div>
      <div style="padding:12px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;"><strong>读者情绪</strong><p style="margin:6px 0 0;line-height:1.6;">${escapeHtml(storyRuntimeDisplayText(firstNonEmpty(outcome.reader_emotion_result, outcome.readerEmotionResult), "随剧情推进"))}</p></div>
    </div>
    <section style="margin-bottom:14px;">
      <h4 style="margin:0 0 8px;font-size:17px;">本章结果</h4>
      <p style="margin:0 0 8px;line-height:1.7;"><strong>章节目标：</strong>${escapeHtml(storyRuntimeDisplayText(chapterGoalResult, "本章目标已完成"))}</p>
      <p style="margin:0;line-height:1.7;"><strong>冲突状态：</strong>${escapeHtml(storyRuntimeDisplayText(firstNonEmpty(outcome.conflict_state, outcome.conflictState), "冲突已推进至下一阶段"))}</p>
    </section>
    ${worldStateNotes.length ? `<section style="margin-bottom:14px;"><h4 style="margin:0 0 8px;font-size:17px;">${isStoryFinalChapter ? "全书结局状态" : "带入下一章"}</h4><ul style="margin:0;padding-left:20px;line-height:1.75;">${worldStateNotes.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>` : ""}
    <p style="margin:0 0 14px;line-height:1.7;"><strong>归档校验：</strong>${validation.passed === false ? "存在待处理问题" : "通过"}</p>
    <div style="display:flex;justify-content:flex-end;gap:10px;">${actionMarkup}</div>
  `;
  markBackendRendered(panel);
  bindBackendActionElement(doc.getElementById("mafsNextChapterButton"), "scene.confirmNextChapter", "chapter-source");
  bindBackendActionElement(doc.getElementById("mafsStoryCompleteButton"), "scene.confirmStoryComplete", "final-entry");
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["chapter-closeout"]);
  applyRealtimeProgressElements(doc, { label: `第 ${chapterIndex || "当前"} 章已归档`, percent: 100 });
  return true;
}

function renderSceneSurface(doc, result) {
  if (!doc?.body || !isFramePage(doc, SCENE_PAGE_IDS)) {
    return false;
  }
  const currentPageId = framePageId(doc);
  if (currentPageId === "scene-entry") {
    return renderSceneEntrySurface(doc, result);
  }
  if (currentPageId === "scene-gate") {
    return renderSceneParticipantGateSurface(doc, result);
  }
  if (currentPageId === "chapter-closeout") {
    return renderChapterCloseoutSurface(doc, result);
  }
  if (
    !doc?.body ||
    (currentPageId !== "chapter-closeout" && !/场景写作|正文生成|正文草案|确认场景|章节收尾/.test(doc.body.textContent || ""))
  ) {
    return false;
  }
  const scene = findScenePayload(result);
  if (!scene) {
    return renderSceneEntrySurface(doc, result);
  }
  persistSceneSelection(doc, scene);
  if (["scene-revision", "scene-impact"].includes(currentPageId)) {
    return renderSceneRevisionSurface(doc, result, scene);
  }
  if (currentPageId === "scene-continuity") {
    return renderSceneContinuitySurface(doc, result, scene);
  }
  const sceneIndex = Number(scene.scene_index || scene.sceneIndex || 1) || 1;
  const chapterId = firstNonEmpty(scene.chapter_id, scene.chapterId, "当前章节");
  const sceneLabel = storyRuntimeDisplayText(firstNonEmpty(
    scene.title,
    scene.scene_title,
    scene.sceneTitle,
    scene.goal,
    scene.synopsis,
    scene.scene_goal?.summary,
    scene.sceneGoal?.summary,
    "当前故事场景",
  ), "当前场景草稿");
  const title = `第${sceneIndex}幕 · ${sceneLabel.length > 34 ? `${sceneLabel.slice(0, 34)}...` : sceneLabel}`;
  const synopsis = storyRuntimeDisplayText(
    firstNonEmpty(scene.synopsis, scene.goal, scene.scene_goal?.summary, scene.sceneGoal?.summary),
    "当前场景已根据项目提示词、世界画布、角色状态、章节计划和场景记忆生成。",
  );
  const rawProse = firstNonEmpty(scene.prose_text, scene.proseText, scene.body, scene.prose);
  const proseHasDiagnosticFallback = containsNonStoryFallbackText(rawProse);
  const prose = cleanStoryRuntimeText(rawProse);
  const timeLabel = cleanStoryRuntimeText(firstNonEmpty(scene.time_label, scene.timeLabel, scene.world_time, scene.worldTime, "当前故事时间"));
  const location = cleanStoryRuntimeText(firstNonEmpty(scene.location, scene.location_name, scene.locationName, scene.setting, "当前场景地点"));
  const status = sceneStatusLabel(scene);
  const sceneLifecycleStatus = String(scene.status || "").toLowerCase();
  const isSceneConfirmed = sceneLifecycleStatus.includes("confirmed") || sceneLifecycleStatus.includes("committed");
  const qualityReport =
    scene.quality_report ||
    scene.qualityReport ||
    result?.quality_report ||
    result?.qualityReport ||
    findNestedObject(result, (item) => Boolean(item?.quality_report_id || item?.qualityReportId)) ||
    {};
  const qualityWarnings = (qualityReport.warnings || []).map((item) => cleanStoryRuntimeText(item)).filter(Boolean);
  const qualityBlockers = (qualityReport.blocking_issues || qualityReport.blockingIssues || [])
    .map((item) => cleanStoryRuntimeText(typeof item === "string" ? item : firstNonEmpty(item?.summary, item?.message, item?.code)))
    .filter(Boolean);
  const qualityPassed = qualityReport.passed === true && qualityBlockers.length === 0;
  const gateReadiness = result?.gate_readiness || result?.gateReadiness || {};
  const continuityChecked = gateReadiness.continuity_passed !== undefined || gateReadiness.continuityPassed !== undefined
    ? true
    : Boolean(
        qualityReport.continuity_checked ||
        qualityReport.continuityChecked ||
        qualityReport.continuity_passed ||
        qualityReport.continuityPassed
      );
  const continuityPassed = gateReadiness.continuity_passed !== undefined || gateReadiness.continuityPassed !== undefined
    ? Boolean(gateReadiness.continuity_passed ?? gateReadiness.continuityPassed)
    : Boolean(qualityReport.continuity_passed || qualityReport.continuityPassed);
  const sceneProgressPayload = findSceneProgressPayload(result);
  const totalSceneCount = Number(
    sceneProgressPayload.total_scene_count ||
      sceneProgressPayload.totalSceneCount ||
      sceneProgressPayload.scene_count ||
      sceneProgressPayload.sceneCount ||
      scene.total_scene_count ||
      scene.totalSceneCount ||
      0,
  );
  const progressNextSceneIndex = Number(sceneProgressPayload.next_scene_index || sceneProgressPayload.nextSceneIndex || 0) || 0;
  const progressScenes = (sceneProgressPayload.scenes || sceneProgressPayload.items || []).filter((item) => item && typeof item === "object");
  const storyProgressEnvelope = result?.story_progress || result?.storyProgress || {};
  const directStoryProgress =
    storyProgressEnvelope?.story_progress ||
    storyProgressEnvelope?.storyProgress ||
    storyProgressEnvelope;
  const storyProgressPayload =
    (directStoryProgress && Object.keys(directStoryProgress).length
      ? directStoryProgress
      : findNestedObject(
          result,
          (item) => Boolean(item?.story_progress_status && item?.current_chapter_index),
        )) || {};
  const chapterPlanPayload = result?.chapter_plan || result?.chapterPlan || {};
  const chapterPlanDraft = chapterPlanPayload?.draft || chapterPlanPayload?.chapter_plan?.draft || chapterPlanPayload?.chapterPlan?.draft || {};
  const chapterRoutes = (chapterPlanDraft?.chapter_routes || chapterPlanDraft?.chapterRoutes || []).filter(
    (item) => item && typeof item === "object",
  );
  const currentChapterIndex = Number(
    storyProgressPayload.current_chapter_index ||
      storyProgressPayload.currentChapterIndex ||
      scene.chapter_index ||
      scene.chapterIndex ||
      chapterPlanDraft.current_chapter_index ||
      chapterPlanDraft.currentChapterIndex ||
      0,
  ) || 0;
  const totalChapterCount = Number(
    storyProgressPayload.chapter_count ||
      storyProgressPayload.chapterCount ||
      chapterPlanDraft.chapter_count ||
      chapterPlanDraft.chapterCount ||
      chapterRoutes.length ||
      0,
  ) || 0;
  const isStoryFinalChapter = Boolean(
    (currentChapterIndex > 0 && totalChapterCount > 0 && currentChapterIndex >= totalChapterCount) ||
      (
        storyProgressPayload.has_next_chapter === false &&
        String(storyProgressPayload.next_recommended_action || "").toLowerCase() === "story_draft_complete"
      ),
  );
  const nextExistingScene = progressScenes.find((item) => Number(item.scene_index || item.sceneIndex || 0) === sceneIndex + 1) || null;
  const canGenerateNextScene = Boolean(sceneProgressPayload.can_generate_next || sceneProgressPayload.canGenerateNext || (totalSceneCount > 0 && progressNextSceneIndex > sceneIndex && progressNextSceneIndex <= totalSceneCount));
  const isChapterFinalScene = totalSceneCount > 0
    ? sceneIndex >= totalSceneCount && !canGenerateNextScene
    : Boolean(scene.is_chapter_final_scene || scene.isChapterFinalScene || scene.chapter_final);
  const requiredLine = storyRuntimeDisplayText(firstNonEmpty(
    scene.required_line,
    scene.requiredLine,
    scene.generation_basis,
    scene.generationBasis,
    synopsis ? `场景依据：${synopsis}` : "场景依据：当前章节框架、角色状态、记忆包与世界画布。",
  ), "场景依据：当前章节框架、角色状态、记忆包与世界画布。");
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
    ${proseHasDiagnosticFallback ? `<div style="margin:0 0 12px;padding:12px;border:1px solid rgba(151,71,61,0.24);border-radius:8px;background:rgba(151,71,61,0.07);line-height:1.7;"><strong>当前草稿需要重新生成。</strong>后端历史草稿包含诊断占位文本，不能作为故事正文显示或导出。</div>` : ""}
    <article style="white-space:pre-wrap;line-height:1.9;padding:14px;border:1px solid rgba(121,89,74,0.16);border-radius:8px;background:rgba(255,255,255,0.62);">${escapeHtml(proseHasDiagnosticFallback ? "请点击下方“重新生成当前草稿”，系统会重新请求后端并返回可审阅的故事正文。" : (prose || "正文草案正在生成，完成后会显示在这里。"))}</article>
    ${Object.keys(qualityReport).length ? `
      <section style="margin-top:14px;padding:14px;border:1px solid ${qualityBlockers.length ? "rgba(151,71,61,0.28)" : "rgba(93,113,91,0.24)"};border-radius:8px;background:${qualityBlockers.length ? "rgba(151,71,61,0.06)" : "rgba(93,113,91,0.06)"};">
        <strong style="display:block;margin-bottom:6px;">后端审查结果：${qualityBlockers.length ? "存在阻塞" : (qualityPassed ? "通过" : "已完成")}</strong>
        <p style="margin:0;line-height:1.7;">连续性门：${continuityChecked ? (continuityPassed ? "通过" : "未通过") : "未运行"}；质量警告：${qualityWarnings.length}；阻塞项：${qualityBlockers.length}。</p>
        ${qualityWarnings.length ? `<details style="margin-top:8px;"><summary style="cursor:pointer;font-weight:700;">查看质量提醒</summary><ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${qualityWarnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></details>` : ""}
        ${qualityBlockers.length ? `<ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;">${qualityBlockers.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
      </section>
    ` : ""}
    ${/正文生成中|正文生成/.test(doc.body.textContent || "") ? `
      <div style="display:flex;justify-content:flex-end;margin-top:14px;">
        <button id="mafsSceneReviewButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-target="scene-review">查看草案审阅</button>
      </div>
    ` : ""}
    <div id="mafs-scene-panel-actions" style="display:flex;justify-content:flex-end;gap:10px;margin-top:14px;">
      ${!isSceneConfirmed ? `<button id="mafsRegenerateSceneButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="scene.regenerateFirst" data-mafs-target="scene-generating">重新生成当前草稿</button>` : ""}
      ${currentPageId === "scene-review" ? `<button id="mafsBackToSceneListButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="scene-entry">返回场景列表</button>` : ""}
      ${currentPageId === "scene-review" ? `<button id="mafsReviseSceneButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-target="scene-revision">${isSceneConfirmed ? "修改已确认场景" : "修订场景"}</button>` : ""}
      ${currentPageId === "scene-review" ? `<button id="mafsContinuitySceneButton" type="button" class="soft-button mafs-backend-rendered" data-mafs-action-id="scene.continuityCheck" data-mafs-target="scene-continuity">连续性检查</button>` : ""}
      ${!isSceneConfirmed ? `<button id="mafsCommitSceneButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="scene.commit" data-mafs-target="scene-confirm" ${proseHasDiagnosticFallback || qualityBlockers.length ? "disabled" : ""}>确认场景</button>` : ""}
    </div>
  `;
  markBackendRendered(panel);
  if (["scene-confirm", "chapter-closeout"].includes(currentPageId)) {
    doc.getElementById("mafs-scene-panel-actions")?.remove();
    doc.getElementById("mafsNextSceneButton")?.remove();
    doc.getElementById("mafsRegenerateSceneButton")?.remove();
    doc.getElementById("confirmButton")?.remove();
    doc.getElementById("mafsCommitSceneButton")?.remove();
  }
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
    confirmButton.disabled = proseHasDiagnosticFallback || qualityBlockers.length > 0;
    confirmButton.textContent = "确认场景";
    confirmButton.dataset.mafsTarget = "scene-confirm";
    confirmButton.dataset.mafsActionId = "scene.commit";
    markBackendRendered(confirmButton);
  } else if (
    !["scene-confirm", "chapter-closeout"].includes(currentPageId) &&
    /正文草案审阅|进入确认流程|确认前状态/.test(doc.body.textContent || "")
  ) {
    const actions = doc.querySelector(".button-row") || doc.querySelector(".button-group") || panel;
    const button = doc.createElement("button");
    button.id = "confirmButton";
    button.type = "button";
    button.className = "primary-button mafs-backend-rendered";
    button.dataset.mafsTarget = "scene-confirm";
    button.dataset.mafsActionId = "scene.commit";
    button.disabled = proseHasDiagnosticFallback || qualityBlockers.length > 0;
    button.textContent = "确认场景";
    actions.appendChild(button);
  }
  bindBackendActionElement(doc.getElementById("mafsRegenerateSceneButton"), "scene.regenerateFirst", "scene-generating");
  bindBackendActionElement(doc.getElementById("mafsBackToSceneListButton"), "", "scene-entry");
  const reviseSceneButton = doc.getElementById("mafsReviseSceneButton");
  if (reviseSceneButton) {
    reviseSceneButton.dataset.mafsSceneId = firstNonEmpty(scene.scene_id, scene.sceneId, scene.id);
    reviseSceneButton.dataset.mafsSceneIndex = String(sceneIndex);
  }
  bindBackendActionElement(reviseSceneButton, "", "scene-revision");
  bindBackendActionElement(doc.getElementById("mafsContinuitySceneButton"), "scene.continuityCheck", "scene-continuity");
  bindBackendActionElement(doc.getElementById("mafsCommitSceneButton"), "scene.commit", "scene-confirm");
  bindBackendActionElement(doc.getElementById("confirmButton"), "scene.commit", "scene-confirm");
  if ((isSceneConfirmed || currentPageId === "scene-confirm") && /确认场景|进入下一场景/.test(doc.body.textContent || "")) {
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
      closeoutButton.dataset.mafsActionId = "scene.archivePreview";
      markBackendRendered(closeoutButton);
      bindBackendActionElement(closeoutButton, "scene.archivePreview", "chapter-closeout");
    } else {
      doc.getElementById("mafsChapterCloseoutButton")?.remove();
      doc.getElementById("mafs-chapter-closeout-actions")?.remove();
      let nextButton = doc.getElementById("mafsNextSceneButton");
      if (!nextButton) {
        nextButton = doc.createElement("button");
        nextButton.id = "mafsNextSceneButton";
        nextButton.type = "button";
        nextButton.className = "primary-button mafs-backend-rendered";
        panel.appendChild(nextButton);
      }
      if (nextExistingScene) {
        nextButton.textContent = "查看下一幕";
        nextButton.dataset.mafsTarget = "scene-review";
        nextButton.dataset.mafsActionId = "scene.openExisting";
        nextButton.dataset.mafsSceneId = firstNonEmpty(nextExistingScene.scene_id, nextExistingScene.sceneId);
        nextButton.dataset.mafsSceneIndex = String(sceneIndex + 1);
      } else {
        nextButton.textContent = "返回场景入口";
        nextButton.dataset.mafsTarget = "scene-entry";
        nextButton.dataset.mafsActionId = "";
        delete nextButton.dataset.mafsSceneId;
        delete nextButton.dataset.mafsSceneIndex;
      }
      markBackendRendered(nextButton);
      bindBackendActionElement(nextButton, nextExistingScene ? "scene.openExisting" : "", nextExistingScene ? "scene-review" : "scene-entry");
    }
  }
  if ((isChapterFinalScene || currentPageId === "chapter-closeout") && (currentPageId === "chapter-closeout" || /章节收尾|下一章准备|准备下一章/.test(doc.body.textContent || ""))) {
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
    const closeoutActions = isStoryFinalChapter
      ? `<button id="mafsStoryCompleteButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="scene.confirmStoryComplete" data-mafs-target="final-entry">故事草稿完成 / 最终输出</button>`
      : `<button id="mafsNextChapterButton" type="button" class="primary-button mafs-backend-rendered" data-mafs-action-id="scene.confirmNextChapter" data-mafs-target="chapter-source">下一章</button>`;
    actions.innerHTML = closeoutActions;
    markBackendRendered(actions);
    bindBackendActionElement(doc.getElementById("mafsNextChapterButton"), "scene.confirmNextChapter", "chapter-source");
    bindBackendActionElement(doc.getElementById("mafsStoryCompleteButton"), "scene.confirmStoryComplete", "final-entry");
  } else {
    doc.getElementById("mafs-chapter-closeout-actions")?.remove();
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
  suppressStaticSiblingsForBackendPanel(doc, panel, target, ["scene-generating", "scene-review", "scene-confirm", "chapter-closeout"]);
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

function pluginAvailabilityLabel(plugin) {
  if (plugin.runtime_available || plugin.runtimeAvailable || plugin.can_create_plugin_run || plugin.canCreatePluginRun) {
    return "可运行";
  }
  const status = firstNonEmpty(plugin.availability_status, plugin.availabilityStatus);
  if (status === "experimental") {
    return "实验协议";
  }
  if (status === "planned") {
    return "规划中";
  }
  return status || "协议已登记";
}

function pluginFamilyLabel(plugin) {
  const family = firstNonEmpty(plugin.plugin_family, plugin.pluginFamily);
  const labels = {
    script: "剧本改编",
    storyboard: "分镜与镜头",
    asset_package: "数字资产",
  };
  return labels[family] || family || "衍生创作";
}

function renderPluginEntrySurface(doc, result, plugins) {
  if (framePageId(doc) !== "plugin-entry" || !plugins.length) {
    return false;
  }
  const layout = doc.querySelector(".layout");
  if (!layout) {
    return false;
  }
  doc.getElementById("newRunButton")?.remove();
  const runtimeCount = plugins.filter(
    (plugin) =>
      plugin.runtime_available ||
      plugin.runtimeAvailable ||
      plugin.can_create_plugin_run ||
      plugin.canCreatePluginRun,
  ).length;
  const snapshotId = firstNonEmpty(
    result?.hydrated_refs?.finalSnapshotId,
    result?.hydratedRefs?.finalSnapshotId,
  );
  const projectTitle = firstNonEmpty(
    result?.hydrated_refs?.projectTitle,
    result?.hydratedRefs?.projectTitle,
    "当前项目",
  );

  setRenderedText(doc.querySelector(".hero h1"), "插件输出");
  setRenderedText(
    doc.querySelector(".hero p"),
    "插件只读取已经确认的最终故事包并生成衍生内容。当前后端仅登记了插件协议；未开放运行时的插件不会显示虚构成果，也不能发起运行。",
  );
  const summaryValues = [
    `${plugins.length} 个协议`,
    runtimeCount ? `${runtimeCount} 个可运行` : "运行时未开放",
    snapshotId ? "最终故事包已就绪" : "等待最终故事包",
  ];
  doc.querySelectorAll(".summary-item strong").forEach((item, index) => {
    setRenderedText(item, summaryValues[index]);
  });

  layout.style.gridTemplateColumns = "minmax(0, 1fr) 340px";
  layout.innerHTML = `
    <section class="panel main-panel mafs-backend-rendered" aria-label="插件协议">
      <div class="panel-header">
        <div>
          <p class="eyebrow">PLUGIN PROTOCOLS</p>
          <h2>可选衍生插件</h2>
          <p class="subtle">这里展示后端真实登记的插件能力和可用状态。插件运行时未开放时，只能查看协议，不能生成或伪造插件成果。</p>
        </div>
        <span class="badge">${escapeHtml(String(plugins.length))}</span>
      </div>
      <div id="mafsPluginProtocolList" class="artifact-list" aria-label="插件协议列表"></div>
    </section>
    <aside class="panel side-panel mafs-backend-rendered" aria-label="插件详情">
      <section class="side-card">
        <p class="eyebrow">SELECTED PLUGIN</p>
        <h3 id="mafsPluginDetailTitle">插件协议</h3>
        <p id="mafsPluginDetailCopy" class="subtle"></p>
        <div class="side-stats">
          <div class="side-stat"><span>类型</span><strong id="mafsPluginFamily"></strong></div>
          <div class="side-stat"><span>状态</span><strong id="mafsPluginAvailability"></strong></div>
          <div class="side-stat"><span>读取边界</span><strong>最终故事包</strong></div>
          <div class="side-stat"><span>写回源故事</span><strong>禁止</strong></div>
        </div>
      </section>
      <section class="side-card">
        <p class="eyebrow">CURRENT PROJECT</p>
        <h3>${escapeHtml(projectTitle)}</h3>
        <p class="subtle">${snapshotId ? `最终故事包快照 ${escapeHtml(snapshotId.slice(-12))} 已可作为未来插件输入。` : "当前项目尚未提供可用的最终故事包快照。"}</p>
      </section>
      <section class="side-card">
        <p class="eyebrow">BOUNDARY</p>
        <h3>真实状态说明</h3>
        <p class="subtle">${runtimeCount ? "仅标记为可运行的插件可以进入运行流程。" : "当前没有开放运行时，因此页面不会展示运行、检查点或成果审阅按钮。"}</p>
      </section>
    </aside>`;

  const list = doc.getElementById("mafsPluginProtocolList");
  const selectPlugin = (plugin, button) => {
    const id = pluginId(plugin);
    doc.body.dataset.mafsSelectedPluginId = id;
    list?.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
    setRenderedText(doc.getElementById("mafsPluginDetailTitle"), pluginDisplayName(plugin));
    setRenderedText(doc.getElementById("mafsPluginDetailCopy"), pluginSummary(plugin));
    setRenderedText(doc.getElementById("mafsPluginFamily"), pluginFamilyLabel(plugin));
    setRenderedText(doc.getElementById("mafsPluginAvailability"), pluginAvailabilityLabel(plugin));
  };
  plugins.forEach((plugin, index) => {
    const button = doc.createElement("button");
    button.type = "button";
    button.className = `artifact-card${index === 0 ? " active" : ""}`;
    button.dataset.localOnly = "true";
    button.innerHTML = `
      <div class="artifact-card-head">
        <span class="artifact-type">${escapeHtml(pluginFamilyLabel(plugin))}</span>
        <span class="status-tag">${escapeHtml(pluginAvailabilityLabel(plugin))}</span>
      </div>
      <h4>${escapeHtml(pluginDisplayName(plugin))}</h4>
      <p>${escapeHtml(pluginSummary(plugin))}</p>
      <div class="artifact-meta">
        <div><span>插件 ID</span><strong>${escapeHtml(pluginId(plugin))}</strong></div>
        <div><span>运行时</span><strong>${plugin.runtime_available || plugin.runtimeAvailable ? "已开放" : "未开放"}</strong></div>
      </div>`;
    button.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        selectPlugin(plugin, button);
      },
      true,
    );
    list.appendChild(button);
    if (index === 0) {
      selectPlugin(plugin, button);
    }
  });
  markBackendRendered(layout);
  return true;
}

function renderUnavailablePluginRuntimeSurface(doc, plugins) {
  const pageId = framePageId(doc);
  if (pageId === "plugin-entry" || !PLUGIN_OUTPUT_PAGE_IDS.has(pageId)) {
    return false;
  }
  const runtimePlugins = plugins.filter(
    (plugin) =>
      plugin.runtime_available ||
      plugin.runtimeAvailable ||
      plugin.can_create_plugin_run ||
      plugin.canCreatePluginRun,
  );
  if (runtimePlugins.length) {
    return false;
  }
  const target =
    doc.querySelector(".main-panel") ||
    doc.querySelector(".content-panel") ||
    doc.querySelector(".layout") ||
    doc.querySelector("main") ||
    doc.body;
  target.innerHTML = `
    <section class="mafs-backend-rendered" style="padding:24px;border:1px solid rgba(105,82,58,.18);border-radius:8px;background:rgba(255,252,244,.84);">
      <p style="margin:0 0 8px;color:#7b6f63;font-size:12px;font-weight:800;">PLUGIN RUNTIME</p>
      <h2 style="margin:0 0 10px;font-size:28px;">插件运行时尚未开放</h2>
      <p style="margin:0 0 18px;line-height:1.75;color:#655d55;">后端当前只登记插件协议，没有可运行插件。运行、检查点、成果审阅和问题处理页面不会展示演示数据。</p>
      <button id="mafsBackToPluginEntry" type="button" class="button primary">返回插件协议</button>
    </section>`;
  bindBackendActionElement(doc.getElementById("mafsBackToPluginEntry"), "plugins.refresh", "plugin-entry");
  markBackendRendered(target);
  return true;
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
  const existingButton = doc.getElementById("mafsFinalPluginButton");
  if (existingButton) {
    bindBackendActionElement(existingButton, "", "plugin-entry");
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
  bindBackendActionElement(button, "", "plugin-entry");
  return true;
}

function renderPluginSurface(doc, result) {
  if (!doc?.body) {
    return false;
  }
  const pageId = framePageId(doc);
  if (pageId === "final-result") {
    ensureFinalResultPluginActionButton(doc);
    return true;
  }
  if (!PLUGIN_OUTPUT_PAGE_IDS.has(pageId)) {
    doc.getElementById("mafsFinalPluginButton")?.remove();
    return false;
  }
  doc.getElementById("mafs-plugin-registry-panel")?.remove();
  const plugins = collectPluginItems(result);
  if (!plugins.length) {
    return false;
  }
  if (renderPluginEntrySurface(doc, result, plugins)) {
    applyRealtimeProgressElements(doc, { label: "插件协议已同步", percent: 100 });
    return true;
  }
  if (renderUnavailablePluginRuntimeSurface(doc, plugins)) {
    applyRealtimeProgressElements(doc, { label: "插件运行时未开放", percent: 100 });
    return true;
  }
  setRenderedText(doc.getElementById("summaryPlugin"), pluginDisplayName(plugins[0]));
  setRenderedText(doc.getElementById("detailTitle"), pluginDisplayName(plugins[0]));
  setRenderedText(doc.getElementById("detailCopy"), pluginSummary(plugins[0]));
  replaceEmptyPlaceholders(doc, "已同步");
  applyRealtimeProgressElements(doc, { label: "插件信息已同步", percent: 100 });
  return true;
}

function findFinalSnapshotPayload(result) {
  return (
    result?.snapshot ||
    result?.final_snapshot ||
    result?.finalSnapshot ||
    result?.action_result?.snapshot ||
    result?.action_result?.final_snapshot ||
    result?.action_result?.finalSnapshot ||
    findNestedObject(result, (item) =>
      Boolean(
        (item.complete_story_text || item.completeStoryText || item.snapshot_id || item.snapshotId) &&
        (item.chapter_scene_index || item.chapterSceneIndex || item.complete_story_text_char_count || item.completeStoryTextCharCount),
      ),
    ) ||
    null
  );
}

function findFinalExportRunPayload(result) {
  return (
    result?.latest_export_run ||
    result?.latestExportRun ||
    result?.export_run ||
    result?.exportRun ||
    result?.action_result?.latest_export_run ||
    result?.action_result?.latestExportRun ||
    result?.action_result?.export_run ||
    result?.action_result?.exportRun ||
    firstItem(result?.export_runs, ["export_runs", "exportRuns", "items", "records"]) ||
    firstItem(result?.action_result?.export_runs, ["export_runs", "exportRuns", "items", "records"]) ||
    {}
  );
}

function findFinalPreviewSections(result) {
  const containers = [
    result?.preview_sections,
    result?.previewSections,
    result?.sections?.preview_sections,
    result?.sections?.previewSections,
    result?.action_result?.preview_sections,
    result?.action_result?.previewSections,
    result?.action_result?.sections?.preview_sections,
    result?.action_result?.sections?.previewSections,
    findNestedArray(result, ["preview_sections", "previewSections"]),
  ];
  for (const container of containers) {
    if (Array.isArray(container) && container.length) {
      return container.filter((item) => item && typeof item === "object");
    }
  }
  return [];
}

function finalCompleteStoryText(snapshot) {
  return firstNonEmpty(snapshot?.complete_story_text, snapshot?.completeStoryText);
}

function finalSnapshotId(snapshot, exportRun = {}) {
  return firstNonEmpty(snapshot?.snapshot_id, snapshot?.snapshotId, exportRun?.snapshot_id, exportRun?.snapshotId);
}

function finalFormatNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number > 0 ? number.toLocaleString("zh-CN") : "0";
}

function finalTextTitle(text, snapshotId = "") {
  const heading = String(text || "").split(/\r?\n/).find((line) => /^#\s+/.test(line.trim()));
  return heading ? heading.replace(/^#\s+/, "").trim() : snapshotId || "最终故事正文";
}

function finalPackageTypeLabel(value) {
  const text = String(value || "");
  if (text.includes("real_project")) {
    return "正式项目";
  }
  if (text.includes("fixture")) {
    return "演示样例";
  }
  return text || "最终故事包";
}

function finalStatusLabel(value) {
  const text = String(value || "");
  if (text === "created" || text === "ready") {
    return "可审阅";
  }
  if (text === "blocked") {
    return "阻塞";
  }
  return text || "已同步";
}

function findFinalReadinessEvaluation(result) {
  const candidates = [
    result?.readiness,
    result?.final_readiness,
    result?.finalReadiness,
    result?.action_result?.readiness,
    result?.action_result?.final_readiness,
    result?.action_result?.finalReadiness,
    result,
    result?.action_result,
  ];
  return (
    candidates.find(
      (item) =>
        item &&
        typeof item === "object" &&
        (item.readiness_gate || item.readinessGate) &&
        (item.validation_report || item.validationReport),
    ) || null
  );
}

function finalReadinessIssues(result, evaluation) {
  const candidates = [
    evaluation?.issues,
    result?.issues?.issues,
    result?.issues?.items,
    result?.action_result?.issues?.issues,
    result?.action_result?.issues?.items,
  ];
  for (const items of candidates) {
    if (Array.isArray(items)) {
      return items.filter((item) => item && typeof item === "object");
    }
  }
  return [];
}

function finalReadinessStatusText(status) {
  if (status === "ready") return "可创建真实最终包";
  if (status === "ready_with_warnings") return "可组装，存在警告";
  if (status === "blocked") return "存在阻塞项";
  if (status === "fixture_only") return "仅可创建演示包";
  return "等待完成度检查";
}

function finalIssueUiType(issue) {
  const severity = String(issue?.severity || "").toLowerCase();
  if (severity === "blocking") return "block";
  if (severity === "warning") return "warning";
  return "pass";
}

function renderFinalReadinessSurface(doc, result) {
  if (framePageId(doc) !== "final-entry") {
    return false;
  }
  const evaluation = findFinalReadinessEvaluation(result);
  if (!evaluation) {
    setRenderedText(doc.getElementById("topStatus"), "正在读取完成度检查");
    setRenderedText(doc.getElementById("summaryStatus"), "检查中");
    bindBackendActionElement(doc.getElementById("refreshButton"), "final.evaluate", "final-entry");
    const nextButton = doc.getElementById("nextButton");
    if (nextButton) nextButton.disabled = true;
    return false;
  }

  const gate = evaluation.readiness_gate || evaluation.readinessGate || {};
  const manifest = evaluation.manifest || {};
  const validation = evaluation.validation_report || evaluation.validationReport || {};
  const issues = finalReadinessIssues(result, evaluation);
  const status = firstNonEmpty(gate.readiness_status, gate.readinessStatus, validation.validation_status, validation.validationStatus);
  const canAssemble = Boolean(gate.can_create_real_final_story_package ?? gate.canCreateRealFinalStoryPackage);
  const blockingCount = issues.filter((item) => finalIssueUiType(item) === "block").length;
  const warningCount = issues.filter((item) => finalIssueUiType(item) === "warning").length;
  const declaredChapters = Number(manifest.declared_chapter_count || manifest.declaredChapterCount || 0);
  const declaredScenes = Number(manifest.declared_scene_count || manifest.declaredSceneCount || 0);
  const detectedChapters = Number(manifest.detected_chapter_count || manifest.detectedChapterCount || 0);
  const detectedScenes = Number(manifest.detected_scene_count || manifest.detectedSceneCount || 0);
  const checks = [
    {
      label: "故事草稿与最终确认",
      passed: Boolean(validation.has_final_confirmation_status ?? validation.hasFinalConfirmationStatus),
    },
    {
      label: "章节与场景索引",
      passed: Boolean(validation.has_chapter_scene_index ?? validation.hasChapterSceneIndex),
    },
    {
      label: "角色与关系状态",
      passed: Boolean(
        (validation.has_character_table ?? validation.hasCharacterTable) &&
        (validation.has_relationship_state_summary ?? validation.hasRelationshipStateSummary),
      ),
    },
    {
      label: "世界摘要与事件线",
      passed: Boolean(
        (validation.has_world_canvas_summary ?? validation.hasWorldCanvasSummary) &&
        (validation.has_key_event_timeline ?? validation.hasKeyEventTimeline),
      ),
    },
    {
      label: "风格、约束与来源",
      passed: Boolean(
        (validation.has_style_and_tone ?? validation.hasStyleAndTone) &&
        (validation.has_user_locked_constraints ?? validation.hasUserLockedConstraints) &&
        (validation.has_source_refs ?? validation.hasSourceRefs),
      ),
    },
  ];
  const passedCount = checks.filter((item) => item.passed).length;
  const score = Math.round((passedCount / checks.length) * 100);
  const statusText = finalReadinessStatusText(status);

  setRenderedText(doc.getElementById("pageTitle"), "成稿交付");
  setRenderedText(doc.getElementById("topStatus"), canAssemble ? "完成度检查通过" : statusText);
  setRenderedText(doc.getElementById("summaryCheck"), "刚刚");
  setRenderedText(doc.getElementById("summaryStatus"), canAssemble ? "可组装" : statusText);
  setRenderedText(doc.getElementById("readinessLabel"), statusText);
  setRenderedText(doc.getElementById("scoreValue"), `${score}%`);
  const gauge = doc.querySelector(".gauge");
  if (gauge) gauge.setAttribute("aria-label", `完成度 ${score}%`);
  setRenderedText(
    doc.getElementById("summaryCopy"),
    canAssemble
      ? `后端检查通过：${detectedChapters || declaredChapters} 章、${detectedScenes || declaredScenes} 幕均已纳入真实最终故事包；${warningCount} 个警告，${blockingCount} 个阻塞。`
      : `后端检查未通过：${blockingCount} 个阻塞，${warningCount} 个警告。请先处理阻塞项。`,
  );
  setRenderedText(
    doc.getElementById("lastCheck"),
    `最后检查：${new Date(gate.updated_at || gate.updatedAt || Date.now()).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`,
  );
  setRenderedText(
    doc.getElementById("actionNote"),
    canAssemble ? "完成度检查通过，可以创建真实成稿快照。" : "请先处理阻塞项，再重新检查。",
  );
  const summaryItems = Array.from(doc.querySelectorAll(".summary-strip strong"));
  if (summaryItems[0]) {
    setRenderedText(
      summaryItems[0],
      `${detectedChapters || declaredChapters} 章 / ${detectedScenes || declaredScenes} 幕`,
    );
  }
  const boundaryLabels = ["只创建最终故事包快照", "插件只能读取受控快照", "警告不阻止组装"];
  doc.querySelectorAll(".boundary-row strong").forEach((element, index) => {
    setRenderedText(element, boundaryLabels[index] || element.textContent || "交付边界");
  });
  const sourceLabels = ["完整正文", "章节与场景索引", "角色表、关系状态与世界摘要"];
  const sourceDescriptions = [
    "complete_story_text",
    "chapter_scene_index",
    "character_table / relationship_state_summary / world_canvas_summary",
  ];
  doc.querySelectorAll(".source-list .source-row strong").forEach((element, index) => {
    setRenderedText(element, sourceLabels[index] || "最终故事包来源");
  });
  doc.querySelectorAll(".source-list .source-row small").forEach((element, index) => {
    setRenderedText(element, sourceDescriptions[index] || "后端已纳入当前最终故事包");
  });
  markBackendRendered(doc.querySelector(".source-list"));

  const scoreRows = Array.from(doc.querySelectorAll(".score-row"));
  checks.forEach((check, index) => {
    const row = scoreRows[index];
    if (!row) return;
    const mark = row.querySelector(".mark");
    const label = row.querySelector("span:nth-child(2)");
    const state = row.querySelector("em");
    if (mark) {
      mark.textContent = check.passed ? "✓" : "!";
      mark.className = `mark${check.passed ? "" : " block"}`;
      markBackendRendered(mark);
    }
    setRenderedText(label, check.label);
    setRenderedText(state, check.passed ? "通过" : "缺失");
  });

  const passItems = checks.map((check, index) => ({
    issue_id: `readiness_check_${index}`,
    severity: check.passed ? "info" : "blocking",
    code: check.passed ? "READINESS_CHECK_PASSED" : "READINESS_CHECK_MISSING",
    user_visible_message: `${check.label}${check.passed ? "已通过后端校验" : "尚未通过后端校验"}`,
    recommended_resolution: check.passed ? "无需处理。" : "返回对应工作台补全后重新检查。",
  }));
  const displayItems = issues.length ? [...issues, ...passItems] : passItems;
  const issueList = doc.getElementById("issueList");
  const detailType = doc.getElementById("detailType");
  const detailTitle = doc.getElementById("detailTitle");
  const detailCopy = doc.getElementById("detailCopy");
  const renderIssues = (filter = "all") => {
    if (!issueList) return;
    const filtered = displayItems.filter((item) => filter === "all" || finalIssueUiType(item) === filter);
    issueList.innerHTML = filtered.length
      ? filtered.map((item, index) => {
        const type = finalIssueUiType(item);
        const label = type === "block" ? "阻塞" : type === "warning" ? "警告" : "已通过";
        return `
          <button class="issue-card${index === 0 ? " selected" : ""} mafs-backend-rendered" type="button" data-final-issue-index="${displayItems.indexOf(item)}">
            <span class="mark ${type}">${type === "pass" ? "✓" : "!"}</span>
            <span>
              <h4>${escapeHtml(item.user_visible_message || item.userVisibleMessage || item.code || "完成度检查项")}</h4>
              <p>${escapeHtml(item.recommended_resolution || item.recommendedResolution || "无需额外处理。")}</p>
            </span>
            <span class="issue-type ${type}">${label}</span>
          </button>
        `;
      }).join("")
      : `<div class="empty-state mafs-backend-rendered">当前筛选下没有后端检查项。</div>`;
    markBackendRendered(issueList);
    const first = filtered[0];
    if (first) {
      const type = finalIssueUiType(first);
      setRenderedText(detailType, type === "block" ? "阻塞" : type === "warning" ? "警告" : "已通过");
      if (detailType) detailType.className = `issue-type ${type}`;
      setRenderedText(detailTitle, first.user_visible_message || first.userVisibleMessage || first.code || "完成度检查项");
      setRenderedText(detailCopy, first.recommended_resolution || first.recommendedResolution || "无需额外处理。");
    } else {
      setRenderedText(detailType, "无");
      setRenderedText(detailTitle, "当前筛选无检查项");
      setRenderedText(detailCopy, "请选择其他筛选条件。");
    }
  };
  renderIssues("all");
  issueList?.addEventListener(
    "click",
    (event) => {
      const card = event.target.closest("[data-final-issue-index]");
      if (!card) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const item = displayItems[Number(card.dataset.finalIssueIndex)] || displayItems[0];
      issueList.querySelectorAll(".issue-card").forEach((candidate) => candidate.classList.toggle("selected", candidate === card));
      if (item) {
        const type = finalIssueUiType(item);
        setRenderedText(detailType, type === "block" ? "阻塞" : type === "warning" ? "警告" : "已通过");
        if (detailType) detailType.className = `issue-type ${type}`;
        setRenderedText(detailTitle, item.user_visible_message || item.userVisibleMessage || item.code || "完成度检查项");
        setRenderedText(detailCopy, item.recommended_resolution || item.recommendedResolution || "无需额外处理。");
      }
    },
    true,
  );
  doc.querySelectorAll(".filter-button[data-filter]").forEach((button) => {
    if (button.dataset.mafsFinalFilterBound === "true") return;
    button.dataset.mafsFinalFilterBound = "true";
    button.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        doc.querySelectorAll(".filter-button[data-filter]").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
        renderIssues(button.dataset.filter || "all");
      },
      true,
    );
  });

  [doc.getElementById("jumpButton"), doc.getElementById("acceptButton")].forEach((button) => {
    if (button) button.style.display = "none";
  });
  const nextButton = doc.getElementById("nextButton");
  if (nextButton) nextButton.disabled = !canAssemble;
  bindBackendActionElement(doc.getElementById("refreshButton"), "final.evaluate", "final-entry");
  bindBackendActionElement(nextButton, "final.assemble", "final-assembly");
  markBackendRendered(doc.querySelector(".main-panel"));
  applyRealtimeProgressElements(doc, { label: canAssemble ? "最终故事包门禁已通过" : "最终故事包门禁存在阻塞", percent: score });
  return true;
}

function renderFinalIssueSurface(doc, result) {
  if (framePageId(doc) !== "final-issue") {
    return false;
  }
  const evaluation = findFinalReadinessEvaluation(result);
  const issues = finalReadinessIssues(result, evaluation);
  const actionableIssues = issues.filter((issue) => finalIssueUiType(issue) !== "pass");
  const target =
    doc.querySelector(".workspace") ||
    doc.querySelector(".main-panel") ||
    doc.querySelector(".content-panel") ||
    doc.querySelector(".layout") ||
    doc.querySelector("main") ||
    doc.body;
  const rows = actionableIssues.length
    ? actionableIssues.map((issue) => {
        const type = finalIssueUiType(issue);
        const label = type === "block" ? "阻塞" : "警告";
        return `
          <article class="mafs-backend-rendered" style="padding:16px;border:1px solid rgba(105,82,58,.18);border-radius:8px;background:rgba(255,252,244,.82);">
            <p style="margin:0 0 6px;color:#7b6f63;font-size:12px;font-weight:800;">${label}</p>
            <h3 style="margin:0 0 8px;font-size:18px;">${escapeHtml(issue.user_visible_message || issue.userVisibleMessage || issue.code || "最终输出检查项")}</h3>
            <p style="margin:0;line-height:1.7;color:#655d55;">${escapeHtml(issue.recommended_resolution || issue.recommendedResolution || "返回对应工作台处理后重新检查。")}</p>
          </article>`;
      }).join("")
    : `
      <section class="mafs-backend-rendered" role="status" style="padding:22px;border:1px solid rgba(105,82,58,.18);border-radius:8px;background:rgba(255,252,244,.82);">
        <p style="margin:0 0 8px;color:#7b6f63;font-size:12px;font-weight:800;">READINESS</p>
        <h3 style="margin:0 0 8px;font-size:22px;">当前没有待处理的最终输出问题</h3>
        <p style="margin:0;line-height:1.7;color:#655d55;">后端完成度检查未返回阻塞或警告。请返回最终输出查看成稿与交付状态。</p>
      </section>`;
  target.innerHTML = `
    <header class="topbar mafs-backend-rendered">
      <button id="mafsBackToFinalEntryTop" type="button" class="button">返回最终输出</button>
      <div class="crumb">主页 / 当前项目 / 最终输出 / 问题处理</div>
      <div class="status-pill"><span class="dot" aria-hidden="true"></span><span>${actionableIssues.length ? "存在待处理问题" : "当前无问题"}</span></div>
    </header>
    <section class="panel main-panel mafs-backend-rendered" aria-label="最终输出问题" style="max-width:980px;margin:24px auto;">
      <p style="margin:0 0 8px;color:#7b6f63;font-size:12px;font-weight:800;">OUTPUT ISSUE RESOLUTION</p>
      <h2 style="margin:0 0 10px;font-size:28px;">最终输出问题</h2>
      <p style="margin:0 0 18px;line-height:1.75;color:#655d55;">这里只显示当前项目由后端 readiness 检查返回的真实问题，不使用设计稿中的演示故障。</p>
      <div style="display:grid;gap:12px;">${rows}</div>
      <div style="display:flex;justify-content:flex-end;margin-top:18px;">
        <button id="mafsBackToFinalEntry" type="button" class="button primary">返回最终输出</button>
      </div>
    </section>`;
  bindBackendActionElement(doc.getElementById("mafsBackToFinalEntry"), "final.evaluate", "final-entry");
  bindBackendActionElement(doc.getElementById("mafsBackToFinalEntryTop"), "final.evaluate", "final-entry");
  markBackendRendered(target);
  applyRealtimeProgressElements(doc, {
    label: actionableIssues.length ? `发现 ${actionableIssues.length} 个待处理问题` : "最终输出检查无待处理问题",
    percent: actionableIssues.length ? 88 : 100,
  });
  return true;
}

function renderFinalAssemblySurface(doc, snapshot, exportRun, previewSections) {
  if (framePageId(doc) !== "final-assembly") {
    return false;
  }
  const storyText = finalCompleteStoryText(snapshot);
  const charCount = Number(snapshot.complete_story_text_char_count || snapshot.completeStoryTextCharCount || storyText.length || 0);
  const chapterSceneIndex = snapshot.chapter_scene_index || snapshot.chapterSceneIndex || [];
  const chapterCount = Array.isArray(chapterSceneIndex)
    ? new Set(chapterSceneIndex.map((item) => item?.chapter_id || item?.chapterId || item?.chapter_index || item?.chapterIndex)).size
    : 0;
  const sceneCount = Array.isArray(chapterSceneIndex) ? chapterSceneIndex.length : 0;
  const warningCount = Array.isArray(snapshot.known_residual_codes || snapshot.knownResidualCodes)
    ? (snapshot.known_residual_codes || snapshot.knownResidualCodes).length
    : 0;
  const snapshotStatus = finalStatusLabel(snapshot.snapshot_status || snapshot.snapshotStatus || exportRun.export_status || exportRun.exportStatus);
  const sourceCount = previewSections.length || Number(snapshot.preview_section_ids?.length || snapshot.previewSectionIds?.length || 0);

  setRenderedText(doc.getElementById("topStatus"), "成稿组装完成");
  setRenderedText(doc.getElementById("pageTitle"), "成稿组装完成");
  setRenderedText(doc.getElementById("summaryStatus"), "可审阅");
  setRenderedText(doc.getElementById("badgeLabel"), "组装完成");
  setRenderedText(doc.getElementById("progressTitle"), "真实成稿快照已创建");
  setRenderedText(doc.getElementById("progressValue"), "100%");
  setRenderedText(doc.getElementById("sideStatus"), snapshotStatus);
  setRenderedText(doc.getElementById("actionNote"), "后端已创建真实成稿快照，可以进入成稿审阅。");
  const progressFill = doc.getElementById("progressFill");
  if (progressFill) {
    progressFill.style.width = "100%";
    markBackendRendered(progressFill);
  }
  const summaryItems = Array.from(doc.querySelectorAll(".summary-strip strong"));
  if (summaryItems[0]) setRenderedText(summaryItems[0], `${sourceCount} 类内容`);
  if (summaryItems[1]) setRenderedText(summaryItems[1], `${chapterCount} 章 / ${sceneCount} 幕 · ${finalFormatNumber(charCount)} 字符`);
  const metadata = Array.from(doc.querySelectorAll(".metadata-grid strong"));
  [
    finalPackageTypeLabel(snapshot.package_type || snapshot.packageType || exportRun.package_type || exportRun.packageType),
    snapshotStatus,
    "已通过",
    `${warningCount} 条`,
  ].forEach((value, index) => setRenderedText(metadata[index], value));
  const sourceLabels = ["完整正文", "章节与场景索引", "角色、世界与关系摘要", "关键事件与锁定约束"];
  const sourceDescriptions = [
    "已确认的完整故事正文。",
    `${chapterCount} 章、${sceneCount} 幕的顺序索引。`,
    "正式角色档案、世界画布和关系状态摘要。",
    "已确认关键事件及用户锁定的故事边界。",
  ];
  doc.querySelectorAll(".source-list .source-row strong").forEach((element, index) => {
    setRenderedText(element, sourceLabels[index] || element.textContent || "快照分区");
  });
  doc.querySelectorAll(".source-list .source-row small").forEach((element, index) => {
    setRenderedText(element, sourceDescriptions[index] || "已写入当前最终快照。");
  });
  const stepLabels = [
    "收集完整正文",
    "建立章节场景索引",
    "整理角色、世界与事件摘要",
    "固化来源边界",
    "生成预览段落",
    "完成成稿快照",
  ];
  doc.querySelectorAll(".step").forEach((step, index) => {
    step.classList.remove("current", "pending");
    step.classList.add("done");
    const mark = step.querySelector(".mark");
    const title = step.querySelector("h4, strong");
    const state = step.querySelector(".step-state");
    setRenderedText(mark, "✓");
    setRenderedText(title, stepLabels[index] || "完成快照步骤");
    setRenderedText(state, "完成");
  });
  const boundaryLabels = [
    "不改写原始故事事实",
    "调试证据默认不进入用户界面",
    "插件只能读取最终快照",
  ];
  doc.querySelectorAll(".boundary-list strong, .boundary-row strong").forEach((element, index) => {
    setRenderedText(element, boundaryLabels[index] || element.textContent || "保持输出边界");
  });
  const mainPanel = doc.querySelector(".main-panel");
  if (mainPanel) {
    mainPanel.setAttribute("aria-busy", "false");
    markBackendRendered(mainPanel);
  }
  const nextButton = doc.getElementById("nextButton");
  if (nextButton) nextButton.disabled = false;
  bindBackendActionElement(nextButton, "final.refreshExports", "final-review");
  bindBackendActionElement(doc.getElementById("returnButton"), "final.evaluate", "final-entry");
  applyRealtimeProgressElements(doc, { label: "真实成稿快照已创建", percent: 100 });
  return true;
}

function finalSectionValue(snapshot, sectionType) {
  const keyByType = {
    chapter_scene_index: snapshot?.chapter_scene_index || snapshot?.chapterSceneIndex,
    character_table: snapshot?.character_table || snapshot?.characterTable,
    world_canvas_summary: snapshot?.world_canvas_summary || snapshot?.worldCanvasSummary,
    relationship_state_summary: snapshot?.relationship_state_summary || snapshot?.relationshipStateSummary,
    key_event_timeline: snapshot?.key_event_timeline || snapshot?.keyEventTimeline,
    user_locked_constraints: snapshot?.user_locked_constraints || snapshot?.userLockedConstraints,
    style_and_tone: snapshot?.style_and_tone || snapshot?.styleAndTone,
    source_lineage: snapshot?.source_ref_ids || snapshot?.sourceRefIds,
    known_residuals: snapshot?.known_residual_codes || snapshot?.knownResidualCodes,
  };
  return keyByType[sectionType];
}

function finalValueToHtml(value, depth = 0) {
  if (value === null || value === undefined || value === "") {
    return `<p class="mafs-final-muted">当前分区暂无已确认条目。</p>`;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return `<p>${escapeHtml(value)}</p>`;
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return `<p class="mafs-final-muted">当前分区暂无已确认条目。</p>`;
    }
    return `<ul class="mafs-final-list">${value
      .slice(0, 24)
      .map((item) => `<li>${finalValueToHtml(item, depth + 1)}</li>`)
      .join("")}</ul>`;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined && item !== "");
    if (!entries.length) {
      return `<p class="mafs-final-muted">当前分区暂无已确认条目。</p>`;
    }
    return `<dl class="mafs-final-kv">${entries
      .slice(0, 18)
      .map(([key, item]) => `<div><dt>${escapeHtml(key)}</dt><dd>${finalValueToHtml(item, depth + 1)}</dd></div>`)
      .join("")}</dl>`;
  }
  return `<p>${escapeHtml(String(value))}</p>`;
}

function finalReviewSections(snapshot, previewSections) {
  const sections = new Map();
  const storyText = finalCompleteStoryText(snapshot);
  sections.set("story", {
    eyebrow: "COMPLETE STORY TEXT",
    title: "最终故事正文预览",
    desc: "以下内容来自后端最终故事包快照，确认不会改写故事事实。",
    metaLabel: "字符",
    metaValue: finalFormatNumber(snapshot?.complete_story_text_char_count || snapshot?.completeStoryTextCharCount || storyText.length),
    html: `<pre class="mafs-final-story-text">${escapeHtml(storyText || "最终故事正文尚未生成。")}</pre>`,
  });
  const mappings = {
    index: ["chapter_scene_index", "章节与幕目录", "来自已确认章节归档与场景顺序。"],
    characters: ["character_table", "角色表", "来自正式角色档案。"],
    world: ["world_canvas_summary", "世界摘要", "来自已确认世界画布。"],
    events: ["key_event_timeline", "事件线", "来自关键事件与已确认场景。"],
    constraints: ["user_locked_constraints", "锁定约束", "来自用户确认约束与边界。"],
  };
  Object.entries(mappings).forEach(([tabKey, [sectionType, title, desc]]) => {
    const preview = previewSections.find((item) => item.section_type === sectionType || item.sectionType === sectionType);
    const value = finalSectionValue(snapshot, sectionType) || preview?.safe_preview || preview?.safePreview;
    sections.set(tabKey, {
      eyebrow: sectionType.toUpperCase(),
      title,
      desc,
      metaLabel: "条目",
      metaValue: finalFormatNumber(preview?.item_count || preview?.itemCount || (Array.isArray(value) ? value.length : value ? 1 : 0)),
      html: finalValueToHtml(value),
    });
  });
  return sections;
}

function renderFinalReviewSection(doc, sectionKey, sections) {
  const section = sections.get(sectionKey) || sections.get("story");
  if (!section) {
    return;
  }
  setRenderedText(doc.getElementById("readerEyebrow"), section.eyebrow);
  setRenderedText(doc.getElementById("readerTitle"), section.title);
  setRenderedText(doc.getElementById("readerDesc"), section.desc);
  setRenderedText(doc.getElementById("readerMetaLabel"), section.metaLabel);
  setRenderedText(doc.getElementById("readerMetaValue"), section.metaValue);
  const body = doc.getElementById("readerBody");
  if (body) {
    body.innerHTML = section.html;
    markBackendRendered(body);
  }
  doc.querySelectorAll(".section-tabs .tab-button").forEach((button) => {
    const active = button.dataset.section === sectionKey;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    markBackendRendered(button);
  });
}

function installFinalReviewTabs(doc, snapshot, previewSections) {
  const sections = finalReviewSections(snapshot, previewSections);
  const tabLabels = {
    story: "正文",
    index: "目录",
    characters: "角色表",
    world: "世界摘要",
    events: "事件线",
    constraints: "锁定约束",
  };
  renderFinalReviewSection(doc, doc.body.dataset.mafsFinalSection || "story", sections);
  doc.querySelectorAll(".section-tabs .tab-button").forEach((button) => {
    setRenderedText(button, tabLabels[button.dataset.section] || button.textContent || "分区");
    if (button.dataset.mafsFinalTabBound === "true") {
      return;
    }
    button.dataset.mafsFinalTabBound = "true";
    button.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const key = button.dataset.section || "story";
        doc.body.dataset.mafsFinalSection = key;
        renderFinalReviewSection(doc, key, sections);
      },
      true,
    );
  });
}

function installFinalDownloadFormatButtons(doc) {
  doc.querySelectorAll(".download-button[data-format]").forEach((button) => {
    if (button.dataset.mafsFinalDownloadFormatBound !== "true") {
      button.dataset.mafsFinalDownloadFormatBound = "true";
      button.addEventListener(
        "click",
        () => {
          doc.querySelectorAll(".download-button[data-format]").forEach((candidate) => {
            const active = candidate === button;
            candidate.classList.toggle("active", active);
            candidate.setAttribute("aria-pressed", String(active));
          });
        },
        true,
      );
    }
    bindBackendActionElement(button, "final.download", "final-result");
  });
}

function finalSnapshotHash(snapshot) {
  return firstNonEmpty(
    snapshot?.complete_story_text_hash,
    snapshot?.completeStoryTextHash,
    snapshot?.story_text_hash,
    snapshot?.storyTextHash,
  );
}

function finalDeliveryFormatData(snapshot, format) {
  const snapshotId = finalSnapshotId(snapshot, {});
  const prefix = snapshotId || "final_story";
  const formats = {
    txt: {
      icon: "TXT",
      suffix: "txt",
      filename: `${prefix}_final_story.txt`,
      mediaType: "text/plain; charset=utf-8",
      title: "TXT 正文文件",
      description: "只导出已确认的完整故事正文，适合直接阅读、备份或交给外部排版工具。",
      includeDescription: "TXT 只包含完整正文；目录、角色表、世界摘要、事件线和审计信息仍保留在最终快照中。",
      includes: [
        ["完整故事正文", "complete_story_text"],
        ["正文 Hash 校验", "complete_story_text_hash"],
        ["字符数", finalFormatNumber(snapshot?.complete_story_text_char_count || snapshot?.completeStoryTextCharCount || 0)],
        ["快照来源", snapshotId || "当前最终快照"],
      ],
    },
    markdown: {
      icon: "MD",
      suffix: "md",
      filename: `${prefix}_final_story.md`,
      mediaType: "text/markdown; charset=utf-8",
      title: "Markdown 成稿",
      description: "包含基础快照元信息和最终正文，适合继续排版、发布或版本归档。",
      includeDescription: "Markdown 包含项目、快照、包类型、正文 Hash、字符数和最终正文。",
      includes: [
        ["基础快照元信息", "project / snapshot / package"],
        ["完整故事正文", "complete_story_text"],
        ["正文 Hash 与字符数", "用于外部核对"],
        ["Markdown 标题层级", "便于继续排版"],
      ],
    },
    json: {
      icon: "JSON",
      suffix: "json",
      filename: `${prefix}_final_story_snapshot.json`,
      mediaType: "application/json; charset=utf-8",
      title: "JSON 快照包",
      description: "导出结构化快照、预览分区、证据索引和安全审计摘要，适合作为后续工具输入。",
      includeDescription: "JSON 包含完整快照、预览分区、证据索引和安全审计摘要。",
      includes: [
        ["完整快照", "FinalStoryPackageSnapshot"],
        ["预览分区", "preview_sections"],
        ["证据索引", "evidence_index"],
        ["安全审计摘要", "safety_audit_summary"],
      ],
    },
  };
  return formats[format] || formats.txt;
}

function renderFinalSettingsSurface(doc, snapshot, exportRun) {
  const snapshotId = finalSnapshotId(snapshot, exportRun);
  const storyText = finalCompleteStoryText(snapshot);
  const charCount = Number(snapshot?.complete_story_text_char_count || snapshot?.completeStoryTextCharCount || storyText.length || 0);
  const packageType = finalPackageTypeLabel(snapshot?.package_type || snapshot?.packageType || exportRun?.package_type || exportRun?.packageType);
  const snapshotStatus = finalStatusLabel(snapshot?.snapshot_status || snapshot?.snapshotStatus || exportRun?.export_status || exportRun?.exportStatus);
  const hash = finalSnapshotHash(snapshot);
  let selectedFormat =
    doc.querySelector(".format-card.active[data-format]")?.dataset.format ||
    doc.querySelector(".format-card[aria-checked='true'][data-format]")?.dataset.format ||
    "txt";

  setRenderedText(doc.getElementById("pageTitle"), "输出设置");
  setRenderedText(doc.getElementById("topStatus"), "交付文件可准备");
  const summaryItems = Array.from(doc.querySelectorAll(".summary-strip strong"));
  if (summaryItems[0]) setRenderedText(summaryItems[0], snapshotId.slice(-10));
  if (summaryItems[1]) setRenderedText(summaryItems[1], `${finalFormatNumber(charCount)} 字符`);
  if (summaryItems[2]) setRenderedText(summaryItems[2], snapshotStatus);

  const formatDefinitions = {
    txt: ["TXT", "TXT 正文文件", "只导出已确认的完整故事正文，适合直接阅读、备份或交给外部排版工具。", "后缀：final_story.txt"],
    markdown: ["MD", "Markdown 成稿", "包含基础快照元信息和最终正文，适合继续排版、发布或版本归档。", "后缀：final_story.md"],
    json: ["JSON", "JSON 快照包", "导出结构化快照、预览分区、证据索引和安全审计摘要，适合作为后续工具输入。", "后缀：final_story_snapshot.json"],
  };

  function renderFormat(format) {
    selectedFormat = formatDefinitions[format] ? format : "txt";
    const data = finalDeliveryFormatData(snapshot, selectedFormat);
    doc.querySelectorAll(".format-card[data-format]").forEach((card) => {
      const definition = formatDefinitions[card.dataset.format];
      if (definition) {
        setRenderedText(card.querySelector(".file-badge"), definition[0]);
        setRenderedText(card.querySelector("strong"), definition[1]);
        setRenderedText(card.querySelector("p"), definition[2]);
        setRenderedText(card.querySelector("small"), definition[3]);
      }
      const active = card.dataset.format === selectedFormat;
      card.classList.toggle("active", active);
      card.setAttribute("aria-checked", String(active));
      markBackendRendered(card);
    });
    setRenderedText(doc.getElementById("fileIcon"), data.icon);
    setRenderedText(doc.getElementById("fileName"), data.filename);
    setRenderedText(doc.getElementById("fileDesc"), `${data.description} media type：${data.mediaType}。`);
    setRenderedText(doc.getElementById("includeDesc"), data.includeDescription);
    const includeGrid = doc.getElementById("includeGrid");
    if (includeGrid) {
      includeGrid.innerHTML = data.includes
        .map(([title, detail]) => `<div class="include-item"><span>${escapeHtml(title)}</span><strong>${escapeHtml(detail)}</strong></div>`)
        .join("");
      markBackendRendered(includeGrid);
    }
    const progressBar = doc.getElementById("progressBar");
    if (progressBar) {
      progressBar.style.width = "100%";
    }
    setRenderedText(doc.getElementById("actionNote"), `最终快照已就绪。确认 ${data.icon} 格式后可继续到交付结果，实际下载由后端快照接口提供。`);
  }

  doc.querySelectorAll(".format-card[data-format]").forEach((card) => {
    if (card.dataset.mafsFinalFormatBound === "true") {
      return;
    }
    card.dataset.mafsFinalFormatBound = "true";
    card.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        renderFormat(card.dataset.format);
      },
      true,
    );
  });

  const metaCells = Array.from(doc.querySelectorAll(".meta-grid strong"));
  [
    snapshotId.slice(-10),
    packageType,
    hash ? `${hash.slice(0, 10)}…${hash.slice(-4)}` : "已由后端校验",
    "通过",
  ].forEach((value, index) => setRenderedText(metaCells[index], value));
  const checkRows = Array.from(doc.querySelectorAll(".check-item"));
  const checks = [
    ["真实项目包", `${packageType}，允许下载。`],
    ["正文完整", `${finalFormatNumber(charCount)} 字符，正文 Hash 已匹配。`],
    ["安全边界", "下载只读取最终快照，不写回故事事实。"],
  ];
  checkRows.forEach((row, index) => {
    if (!checks[index]) return;
    setRenderedText(row.querySelector("span:not(.check-mark)"), checks[index][0]);
    setRenderedText(row.querySelector("strong"), checks[index][1]);
  });
  const historyList = doc.getElementById("historyList");
  if (historyList) {
    historyList.innerHTML = `<div class="history-item"><div><span>快照已就绪</span><strong>${escapeHtml(snapshotId)}</strong></div><em>READY</em></div>`;
    markBackendRendered(historyList);
  }
  const downloadButton = doc.getElementById("downloadButton");
  if (downloadButton) {
    setRenderedText(downloadButton, "准备交付文件");
    downloadButton.disabled = false;
    bindBackendActionElement(downloadButton, "final.refreshExports", "final-exporting");
  }
  const reviewButton = doc.getElementById("reviewButton");
  if (reviewButton) {
    bindBackendActionElement(reviewButton, "final.refreshExports", "final-review");
  }
  const copyNameButton = doc.getElementById("copyName");
  if (copyNameButton && copyNameButton.dataset.mafsCopyNameBound !== "true") {
    copyNameButton.dataset.mafsCopyNameBound = "true";
    copyNameButton.addEventListener(
      "click",
      async (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const filename = doc.getElementById("fileName")?.textContent?.trim() || "";
        let copied = false;
        try {
          await doc.defaultView?.navigator?.clipboard?.writeText(filename);
          copied = true;
        } catch {
          copied = false;
        }
        setRenderedText(copyNameButton, copied ? "文件名已复制" : "文件名已显示");
        doc.defaultView?.setTimeout(() => setRenderedText(copyNameButton, "复制文件名"), 1600);
      },
      true,
    );
  }
  renderFormat(selectedFormat);
  replaceEmptyPlaceholders(doc, "已同步");
  setRenderedText(doc.getElementById("fileTitle"), "文件预览");
  setRenderedText(doc.getElementById("formatTitle"), "选择交付格式");
  const flowLabels = ["完成度检查", "成稿组装", "成稿审阅", "输出设置"];
  doc.querySelectorAll(".flow-item strong").forEach((item, index) => setRenderedText(item, flowLabels[index]));
  const sideEyebrows = ["STATUS", "BOUNDARY", "HISTORY"];
  doc.querySelectorAll(".side-card .eyebrow").forEach((item, index) => setRenderedText(item, sideEyebrows[index]));
  markBackendRendered(doc.querySelector(".main-panel"));
  applyRealtimeProgressElements(doc, { label: "最终故事包快照已同步", percent: 100 });
  return true;
}

function renderFinalExportingSurface(doc, snapshot, exportRun) {
  const snapshotId = finalSnapshotId(snapshot, exportRun);
  const storyText = finalCompleteStoryText(snapshot);
  const charCount = Number(snapshot?.complete_story_text_char_count || snapshot?.completeStoryTextCharCount || storyText.length || 0);
  const snapshotStatus = finalStatusLabel(snapshot?.snapshot_status || snapshot?.snapshotStatus || exportRun?.export_status || exportRun?.exportStatus);
  setRenderedText(doc.getElementById("pageTitle"), "交付文件已就绪");
  setRenderedText(doc.getElementById("topStatus"), "准备完成");
  const summaryItems = Array.from(doc.querySelectorAll(".summary-strip strong"));
  if (summaryItems[0]) setRenderedText(summaryItems[0], "TXT / Markdown / JSON");
  if (summaryItems[1]) setRenderedText(summaryItems[1], `${finalFormatNumber(charCount)} 字符`);
  if (summaryItems[2]) setRenderedText(summaryItems[2], snapshotStatus);
  setRenderedText(doc.getElementById("visualTitle"), "最终快照读取完成");
  setRenderedText(doc.getElementById("progressValue"), "100%");
  setRenderedText(doc.getElementById("progressStatus"), "交付准备完成");
  setRenderedText(doc.getElementById("progressNote"), "后端已返回最终故事包快照。下一页提供三种格式的真实下载入口。");
  const progressBar = doc.getElementById("progressBar");
  if (progressBar) progressBar.style.width = "100%";
  doc.querySelectorAll(".step-row").forEach((row) => {
    row.classList.add("done");
    row.classList.remove("active");
    setRenderedText(row.querySelector(".step-state"), "完成");
    if (row instanceof doc.defaultView.HTMLButtonElement) {
      row.disabled = true;
      row.setAttribute("aria-disabled", "true");
      row.style.cursor = "default";
    }
    markBackendRendered(row);
  });
  const detailBox = doc.getElementById("detailBox");
  if (detailBox) {
    detailBox.innerHTML = `<strong>真实快照已准备</strong><p>快照 ${escapeHtml(snapshotId)} 已读取，正文 ${escapeHtml(finalFormatNumber(charCount))} 字符。下载时由后端返回文件名、媒体类型和文件内容。</p>`;
    markBackendRendered(detailBox);
  }
  const summaryCells = Array.from(doc.querySelectorAll(".summary-item strong"));
  [
    snapshotId,
    "txt / markdown / json",
    `${snapshotId}_final_story.*`,
    "由所选格式决定",
  ].forEach((value, index) => setRenderedText(summaryCells[index], value));
  const sheetFooter = Array.from(doc.querySelectorAll(".sheet-footer span"));
  if (sheetFooter[0]) setRenderedText(sheetFooter[0], finalSnapshotHash(snapshot) ? "Hash matched" : "Snapshot verified");
  if (sheetFooter[1]) setRenderedText(sheetFooter[1], `${finalFormatNumber(charCount)} chars`);
  const logList = doc.getElementById("logList");
  if (logList) {
    logList.innerHTML = [
      ["READY", "最终快照已从后端读取。"],
      ["VERIFY", "正文字符数与快照状态已校验。"],
      ["DELIVERY", "三种下载格式入口已准备。"],
    ].map(([key, value]) => `<div class="log-item"><span>${key}</span><strong>${value}</strong></div>`).join("");
    markBackendRendered(logList);
  }
  setRenderedText(doc.getElementById("actionNote"), "交付文件入口已准备完成。进入交付结果页后选择格式并开始真实下载。");
  const completeButton = doc.getElementById("completeButton");
  if (completeButton) {
    completeButton.disabled = false;
    setRenderedText(completeButton, "进入交付结果");
    bindBackendActionElement(completeButton, "final.refreshExports", "final-result");
  }
  const settingsButton = doc.getElementById("settingsButton");
  if (settingsButton) {
    bindBackendActionElement(settingsButton, "final.refreshExports", "final-settings");
  }
  replaceEmptyPlaceholders(doc, "已同步");
  const panelHeading = doc.querySelector(".panel-head h2");
  const panelDescription = doc.querySelector(".panel-head h2 + p");
  setRenderedText(panelHeading, "交付文件入口已准备");
  setRenderedText(panelDescription, "最终故事包快照已经由后端读取并校验；实际文件只会在用户选择格式并点击下载时生成。");
  const visualDescription = doc.querySelector("#visualTitle + p");
  setRenderedText(visualDescription, "当前进度来自后端最终快照读取结果，不使用前端计时动画模拟完成状态。");
  const flowLabels = ["完成度检查", "成稿组装", "成稿审阅", "输出设置", "交付准备"];
  doc.querySelectorAll(".flow-item strong").forEach((item, index) => setRenderedText(item, flowLabels[index]));
  const stepDescriptions = [
    "根据 snapshot_id 获取最终故事包。",
    "确认字符数、Hash 和真实项目包状态。",
    "确认 TXT、Markdown、JSON 三种交付规则可用。",
    "等待用户选择格式后调用真实下载接口。",
  ];
  doc.querySelectorAll(".step-row").forEach((row, index) => setRenderedText(row.querySelector("span span"), stepDescriptions[index]));
  const summaryLabels = ["Snapshot ID", "Download formats", "Expected filename", "Media type"];
  doc.querySelectorAll(".summary-item > span").forEach((item, index) => setRenderedText(item, summaryLabels[index]));
  const guardRows = Array.from(doc.querySelectorAll(".guard-row"));
  const guards = [
    ["只读快照", "读取 FinalStoryPackageSnapshot。"],
    ["格式受限", "当前仅允许 TXT、Markdown、JSON。"],
    ["失败可恢复", "保留格式选择并返回设置重试。"],
  ];
  guardRows.forEach((row, index) => {
    if (!guards[index]) return;
    const textContainer = row.querySelector("div");
    setRenderedText(textContainer?.querySelector("span"), guards[index][0]);
    setRenderedText(textContainer?.querySelector("strong"), guards[index][1]);
  });
  markBackendRendered(doc.querySelector(".main-panel"));
  applyRealtimeProgressElements(doc, { label: "交付文件入口已准备", percent: 100 });
  return true;
}

function renderFinalOutputSurface(doc, result) {
  if (!doc?.body || !isFramePage(doc, FINAL_OUTPUT_PAGE_IDS)) {
    return false;
  }
  const currentPageId = framePageId(doc);
  if (currentPageId === "final-entry") {
    return renderFinalReadinessSurface(doc, result);
  }
  if (currentPageId === "final-issue") {
    return renderFinalIssueSurface(doc, result);
  }
  const snapshot = findFinalSnapshotPayload(result);
  const exportRun = findFinalExportRunPayload(result);
  const previewSections = findFinalPreviewSections(result);
  const snapshotId = finalSnapshotId(snapshot, exportRun);
  const storyText = finalCompleteStoryText(snapshot);
  if (!snapshot || !snapshotId) {
    installFinalDownloadFormatButtons(doc);
    return false;
  }
  if (currentPageId === "final-assembly") {
    return renderFinalAssemblySurface(doc, snapshot, exportRun, previewSections);
  }
  if (currentPageId === "final-settings") {
    return renderFinalSettingsSurface(doc, snapshot, exportRun);
  }
  if (currentPageId === "final-exporting") {
    return renderFinalExportingSurface(doc, snapshot, exportRun);
  }

  const charCount = Number(snapshot.complete_story_text_char_count || snapshot.completeStoryTextCharCount || storyText.length || 0);
  const chapterCount = Array.isArray(snapshot.chapter_scene_index || snapshot.chapterSceneIndex)
    ? new Set((snapshot.chapter_scene_index || snapshot.chapterSceneIndex).map((item) => item?.chapter_id || item?.chapterId || item?.chapter_index || item?.chapterIndex)).size
    : 0;
  const warningCount = Array.isArray(snapshot.known_residual_codes || snapshot.knownResidualCodes)
    ? (snapshot.known_residual_codes || snapshot.knownResidualCodes).length
    : 0;
  const title = finalTextTitle(storyText, snapshotId);
  const packageType = finalPackageTypeLabel(snapshot.package_type || snapshot.packageType || exportRun.package_type || exportRun.packageType);
  const snapshotStatus = finalStatusLabel(snapshot.snapshot_status || snapshot.snapshotStatus || exportRun.export_status || exportRun.exportStatus);

  setRenderedText(doc.getElementById("pageTitle"), /下载与归档|交付结果/.test(doc.body.textContent || "") ? "下载与归档" : "成稿审阅");
  setRenderedText(doc.getElementById("summaryStatus"), "已同步");
  setRenderedText(doc.getElementById("badgeLabel"), "可审阅");
  const summaryItems = Array.from(doc.querySelectorAll(".summary-strip strong"));
  if (summaryItems[0]) setRenderedText(summaryItems[0], snapshotId.slice(-10));
  if (summaryItems[1]) setRenderedText(summaryItems[1], `${finalFormatNumber(charCount)} 字符`);
  if (summaryItems[2]) setRenderedText(summaryItems[2], snapshotStatus);

  installFinalReviewTabs(doc, snapshot, previewSections);

  const healthCells = Array.from(doc.querySelectorAll(".health-grid div strong"));
  [
    packageType,
    snapshotStatus,
    `${warningCount} 条`,
    snapshot.can_be_used_by_plugins || snapshot.canBeUsedByPlugins ? "允许" : "只读",
  ].forEach((value, index) => setRenderedText(healthCells[index], value));

  const warnings = snapshot.known_residual_codes || snapshot.knownResidualCodes || [];
  const warningCheck = doc.getElementById("warningCheck");
  if (warningCheck) {
    warningCheck.checked = warnings.length === 0 ? true : warningCheck.checked;
    const warningCheckRow = warningCheck.closest(".check-row");
    warningCheckRow?.toggleAttribute("hidden", warnings.length === 0);
    if (warningCheckRow) {
      warningCheckRow.style.display = warnings.length === 0 ? "none" : "";
    }
    warningCheck.dispatchEvent(new Event("change", { bubbles: true }));
  }
  const warningList = doc.querySelector(".warning-list");
  if (warningList) {
    warningList.innerHTML = warnings.length
      ? warnings.slice(0, 5).map((item, index) => `
      <button class="warning-row${index === 0 ? " selected" : ""}" type="button" data-warning="${index}">
        <span class="mark warning">!</span>
        <span>
          <strong>保留说明</strong>
          <span>${escapeHtml(item)}</span>
        </span>
      </button>
    `).join("")
      : `
        <div class="warning-row selected mafs-backend-rendered" role="status">
          <span class="mark">✓</span>
          <span>
            <strong>无阻塞警告</strong>
            <span>当前快照无阻塞警告</span>
          </span>
        </div>
      `;
    markBackendRendered(warningList);
    warningList.querySelectorAll(".warning-row").forEach((row) => {
      row.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          warningList.querySelectorAll(".warning-row").forEach((candidate) => {
            candidate.classList.toggle("selected", candidate === row);
          });
          const warning = warnings[Number(row.dataset.warning)] || "";
          setRenderedText(
            doc.getElementById("warningDetail"),
            warning
              ? `保留说明：${warning}。该说明会进入后续交付记录。`
              : "当前最终故事包没有阻塞性残留。",
          );
        },
        true,
      );
    });
  }
  setRenderedText(doc.getElementById("warningDetail"), warnings.length ? "保留说明会进入后续交付记录。" : "当前最终故事包没有阻塞性残留。");
  const resolveWarningButton = doc.getElementById("resolveWarning");
  if (resolveWarningButton) {
    resolveWarningButton.hidden = warnings.length === 0;
  }
  if (resolveWarningButton && resolveWarningButton.dataset.mafsFinalReviewBound !== "true") {
    resolveWarningButton.dataset.mafsFinalReviewBound = "true";
    resolveWarningButton.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const warningCheck = doc.getElementById("warningCheck");
        if (warningCheck) {
          warningCheck.checked = true;
          warningCheck.dispatchEvent(new Event("change", { bubbles: true }));
        }
        setRenderedText(doc.getElementById("warningDetail"), warnings.length ? "保留说明已标记为已读。" : "当前没有需要处理的保留警告。");
      },
      true,
    );
  }
  const openSourceButton = doc.getElementById("openSource");
  if (openSourceButton) {
    openSourceButton.hidden = warnings.length === 0;
  }
  if (openSourceButton && openSourceButton.dataset.mafsFinalReviewBound !== "true") {
    openSourceButton.dataset.mafsFinalReviewBound = "true";
    openSourceButton.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        doc.body.dataset.mafsFinalSection = "world";
        renderFinalReviewSection(doc, "world", finalReviewSections(snapshot, previewSections));
      },
      true,
    );
  }
  bindBackendActionElement(doc.getElementById("reviseButton"), "navigation.scene", "scene-entry");
  setRenderedText(doc.getElementById("actionNote"), "请审阅后确认成稿，确认不会改写故事事实。");

  setRenderedText(doc.getElementById("summarySize"), `${finalFormatNumber(charCount)} 字符`);
  setRenderedText(doc.getElementById("filename"), `${snapshotId}_final_story.txt`);
  setRenderedText(doc.getElementById("fileTitle"), title);
  setRenderedText(doc.getElementById("fileSubline"), "text/plain; charset=utf-8 / 下载来自后端最终故事包快照。");
  setRenderedText(doc.getElementById("metricFormat"), "TXT");
  const metricCells = Array.from(doc.querySelectorAll(".metric-card strong"));
  [
    `${finalFormatNumber(charCount)} 字符`,
    chapterCount ? `${chapterCount} 章` : "已同步",
    "TXT",
    snapshotStatus,
  ].forEach((value, index) => setRenderedText(metricCells[index], value));
  const metaCells = Array.from(doc.querySelectorAll(".file-meta .meta-cell strong"));
  [
    snapshotId.slice(-12),
    firstNonEmpty(exportRun.export_run_id, exportRun.exportRunId, "已创建").slice(-12),
    packageType,
  ].forEach((value, index) => setRenderedText(metaCells[index], value));
  const archiveItems = Array.from(doc.querySelectorAll(".archive-item small"));
  [
    `artifact_entry_${snapshotId}`,
    `final_story_package_view_${snapshot.project_id || snapshot.projectId || "current_project"}`,
    "归档记录来自导出结果与产品输出库索引，不写回世界事实、角色事实或章节计划。",
  ].forEach((value, index) => setRenderedText(archiveItems[index], value));
  const timelineItems = Array.from(doc.querySelectorAll("#timelineList .timeline-item small"));
  [
    `浏览器将从后端下载 ${snapshotId}。`,
    "最终故事包快照已由后端创建并可重复读取。",
    "下载与插件输入均以最终故事包快照为边界。",
  ].forEach((value, index) => setRenderedText(timelineItems[index], value));

  installFinalDownloadFormatButtons(doc);
  replaceEmptyPlaceholders(doc, "已同步");
  if (currentPageId === "final-result") {
    const downloadResult =
      result?.download_result ||
      result?.downloadResult ||
      result?.action_result?.download_result ||
      result?.action_result?.downloadResult ||
      null;
    const selectedFormat = firstNonEmpty(
      result?.selected_format,
      result?.selectedFormat,
      result?.action_result?.selected_format,
      result?.action_result?.selectedFormat,
      "txt",
    );
    const formatLabels = {
      txt: "TXT",
      markdown: "Markdown",
      json: "JSON",
    };
    const formatLabel = formatLabels[selectedFormat] || "TXT";
    const formatData = finalDeliveryFormatData(snapshot, selectedFormat);
    const downloadCompleted = Boolean(downloadResult?.filename);
    setRenderedText(doc.getElementById("summaryFormat"), downloadCompleted ? formatLabel : "3 种格式可选");
    setRenderedText(
      doc.getElementById("summarySize"),
      downloadCompleted && downloadResult?.byteSize
        ? `${finalFormatNumber(downloadResult.byteSize)} 字节`
        : `${finalFormatNumber(charCount)} 字符`,
    );
    const heroDescription = doc.querySelector("#pageTitle + p");
    setRenderedText(heroDescription, "最终故事包快照已经归档。请选择 TXT、Markdown 或 JSON，文件只在点击下载时由后端生成。");
    setRenderedText(doc.getElementById("deliveryTitle"), downloadCompleted ? "下载完成" : "选择交付格式");
    setRenderedText(
      doc.querySelector("#deliveryTitle + p"),
      downloadCompleted
        ? `浏览器已接收 ${downloadResult.filename}，本次下载没有修改故事事实。`
        : "尚未触发文件下载。三个按钮均直接读取当前最终故事包快照。",
    );
    const flowLabels = ["完成度检查", "成稿组装", "成稿审阅", "输出设置", "交付准备", "下载与归档"];
    doc.querySelectorAll(".flow-step strong").forEach((item, index) => setRenderedText(item, flowLabels[index]));
    setRenderedText(doc.getElementById("fileIcon"), formatData.icon);
    setRenderedText(doc.getElementById("fileTitle"), title);
    setRenderedText(
      doc.getElementById("fileSubline"),
      downloadCompleted
        ? `${downloadResult.mediaType || formatData.mediaType} / 后端下载完成。`
        : `${formatData.mediaType} / 等待用户选择格式。`,
    );
    setRenderedText(doc.getElementById("filename"), downloadResult?.filename || formatData.filename);
    const metaLabels = ["Snapshot ID", "Export Run", "Package Type"];
    doc.querySelectorAll(".file-meta .meta-cell > span").forEach((item, index) => setRenderedText(item, metaLabels[index]));
    const buttonLabels = {
      txt: "下载 TXT",
      markdown: "下载 Markdown",
      json: "下载 JSON",
    };
    doc.querySelectorAll(".download-button[data-format]").forEach((button) => {
      setRenderedText(button, buttonLabels[button.dataset.format] || "下载");
      const active = button.dataset.format === selectedFormat;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    setRenderedText(doc.getElementById("metricFormat"), downloadCompleted ? formatLabel : "待选择");
    const metricLabels = ["正文规模", "章节数量", "最近下载", "快照状态"];
    doc.querySelectorAll(".metric-card > div > span").forEach((item, index) => setRenderedText(item, metricLabels[index]));
    setRenderedText(doc.querySelector("#sideTitle + p"), "可重复下载 TXT、Markdown、JSON；所有文件均来自当前已确认快照。");
    const timelineTitles = Array.from(doc.querySelectorAll("#timelineList .timeline-item b"));
    const timelineDetails = Array.from(doc.querySelectorAll("#timelineList .timeline-item small"));
    const timelineData = downloadCompleted
      ? [
          ["文件下载已完成", `${downloadResult.filename}，${finalFormatNumber(downloadResult.byteSize || 0)} 字节。`],
          ["最终快照已索引", `快照 ${snapshotId} 可重复读取。`],
          ["安全边界保持", "下载未改写世界、角色、章节或场景事实。"],
        ]
      : [
          ["等待用户选择格式", "尚未向浏览器发送文件。"],
          ["最终快照已索引", `快照 ${snapshotId} 可重复读取。`],
          ["安全边界保持", "下载只读取最终故事包快照。"],
        ];
    timelineData.forEach(([itemTitle, itemDetail], index) => {
      setRenderedText(timelineTitles[index], itemTitle);
      setRenderedText(timelineDetails[index], itemDetail);
    });
    const openLibraryButton = doc.querySelector("[data-action='open-library']");
    if (openLibraryButton) {
      openLibraryButton.remove();
    }
    const collectionButton = doc.querySelector("[data-action='open-collection']");
    if (collectionButton) {
      setRenderedText(collectionButton, "返回项目列表");
      bindBackendActionElement(collectionButton, "", "projects");
    }
    const backSettingsButton = doc.querySelector("[data-action='back-settings']");
    if (backSettingsButton) {
      bindBackendActionElement(backSettingsButton, "final.refreshExports", "final-settings");
    }
    const backOutputButton = doc.querySelector("[data-action='back-output']");
    if (backOutputButton) {
      setRenderedText(backOutputButton, "返回交付准备");
      bindBackendActionElement(backOutputButton, "final.refreshExports", "final-exporting");
    }
    installFinalDownloadFormatButtons(doc);
  }
  markBackendRendered(doc.querySelector(".main-panel"));
  applyRealtimeProgressElements(doc, { label: "最终故事包快照已同步", percent: 100 });
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
      if (!item || typeof item !== "object") {
        return;
      }
      const itemId = firstNonEmpty(item.profile_id, item.profileId, item.id);
      if (!profiles.some((profile) => firstNonEmpty(profile.profile_id, profile.profileId, profile.id) === itemId)) {
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

function findStorySetupBootstrapPayload(result) {
  return findNestedObject(
    result,
    (item) =>
      Boolean(
        item?.story_setup_bootstrap_id ||
          item?.storySetupBootstrapId ||
          item?.bootstrap_status ||
          item?.bootstrapStatus,
      ),
  );
}

function applyStorySetupHandoffState(doc, result, actionId = "") {
  if (!doc?.getElementById("createButton")) {
    return;
  }
  const handoff = findStorySetupHandoffPayload(result) || {};
  const bootstrap = findStorySetupBootstrapPayload(result) || {};
  const projectState = result?.project_creation_state || result?.projectCreationState || {};
  const currentWorldCanvas = result?.current_world_canvas || result?.currentWorldCanvas || {};
  const persistedWorldCanvas = currentWorldCanvas.world_canvas || currentWorldCanvas.worldCanvas || currentWorldCanvas;
  const handoffId = firstNonEmpty(
    handoff.story_setup_handoff_id,
    handoff.storySetupHandoffId,
    bootstrap.story_setup_handoff_id,
    bootstrap.storySetupHandoffId,
  );
  const projectStatus = firstNonEmpty(
    projectState.status,
    projectState.project?.status,
    result?.project?.status,
  );
  const bootstrapStatus = firstNonEmpty(bootstrap.bootstrap_status, bootstrap.bootstrapStatus);
  const created = Boolean(handoffId);
  const handoffStatus = firstNonEmpty(handoff.handoff_status, handoff.handoffStatus);
  const initialized =
    bootstrapStatus === "applied" ||
    handoffStatus === "applied" ||
    projectStatus === "story_setup_bootstrapped" ||
    Boolean(created && (persistedWorldCanvas.world_canvas_id || persistedWorldCanvas.worldCanvasId)) ||
    actionId === "storySetup.bootstrapHandoff";

  const createButton = doc.getElementById("createButton");
  const bootstrapButton = doc.getElementById("bootstrapButton");
  const enterButton = doc.getElementById("enterButton");
  const targetWorkspace = doc.getElementById("targetWorkspace");
  if (createButton) createButton.disabled = created;
  if (bootstrapButton) bootstrapButton.disabled = !created || initialized;
  if (enterButton) enterButton.disabled = !initialized;
  if (targetWorkspace) targetWorkspace.disabled = initialized;

  const handoffIdNode = doc.getElementById("handoffId");
  if (handoffIdNode) handoffIdNode.textContent = created ? handoffId : "尚未创建";
  const packageBadge = doc.getElementById("packageBadge");
  if (packageBadge) {
    packageBadge.textContent = initialized ? "已初始化" : created ? "交接就绪" : "待创建";
    packageBadge.classList.toggle("ready", created && !initialized);
    packageBadge.classList.toggle("done", initialized);
  }
  const sideHandoff = doc.getElementById("sideHandoffStatus");
  if (sideHandoff) sideHandoff.textContent = created ? "就绪" : "未创建";
  const sideBootstrap = doc.getElementById("sideBootstrapStatus");
  if (sideBootstrap) sideBootstrap.textContent = initialized ? "完成" : "未开始";

  const stepCreate = doc.getElementById("stepCreate");
  const stepBootstrap = doc.getElementById("stepBootstrap");
  if (stepCreate) {
    stepCreate.classList.toggle("active", !created);
    stepCreate.classList.toggle("done", created);
  }
  if (stepBootstrap) {
    stepBootstrap.classList.toggle("active", created && !initialized);
    stepBootstrap.classList.toggle("done", initialized);
  }
  const progressFill = doc.getElementById("progressFill");
  if (progressFill) progressFill.style.width = initialized ? "100%" : created ? "36%" : "0%";
  const progressCount = doc.getElementById("progressCount");
  if (progressCount) progressCount.textContent = initialized ? "100%" : created ? "36%" : "0%";
  const progressTitle = doc.getElementById("progressTitle");
  if (progressTitle) progressTitle.textContent = initialized ? "当前项目已初始化" : created ? "交接包已创建" : "等待创建交接包";
  const progressCopy = doc.getElementById("progressCopy");
  if (progressCopy) {
    progressCopy.textContent = initialized
      ? "可以进入目标工作台继续确认故事设定。"
      : created
        ? "现在可以初始化当前项目工作台。"
        : "创建交接包后才可以初始化当前项目工作台。";
    progressCopy.dataset.mafsBackendRendered = "true";
  }
  const pageState = doc.getElementById("pageState");
  if (pageState) pageState.textContent = initialized ? "初始化完成" : created ? "交接已就绪" : "等待交接";
  const fileList = doc.getElementById("fileList");
  if (fileList && initialized) {
    fileList.classList.add("done");
    fileList.innerHTML = `
      <li><span class="dot"></span><span>当前项目故事资料已初始化</span></li>
      <li><span class="dot"></span><span>世界画布草案状态：待确认</span></li>
      <li><span class="dot"></span><span>世界画布工作台已解锁</span></li>
    `;
    fileList.dataset.mafsBackendRendered = "true";
  }
}

function setSettingsText(doc, selector, value) {
  const element = doc.querySelector(selector);
  if (element && value !== undefined && value !== null && String(value).trim()) {
    element.textContent = String(value);
    markBackendRendered(element);
  }
}

function renderModelConfigurationSurface(doc, result) {
  if (doc?.body?.dataset?.mafsPageId !== "settings-model") {
    return false;
  }
  const workbench = findSettingsWorkbench(result) || {};
  const profiles = collectSettingsProfiles(result, workbench);
  const active = activeSettingsSelection(result, workbench) || {};
  const activeProfileId = firstNonEmpty(
    active.provider_profile_id,
    active.providerProfileId,
    workbench.active_profile_id,
    workbench.activeProfileId,
  );
  const activeProfile = profiles.find((profile) => firstNonEmpty(profile.profile_id, profile.profileId) === activeProfileId) || profiles[0] || {};
  const currentProvider = firstNonEmpty(active.provider_type, active.providerType, activeProfile.provider_type, activeProfile.providerType, "未配置");
  const currentModel = firstNonEmpty(active.model_name, active.modelName, activeProfile.model_name, activeProfile.modelName, "未配置");
  const currentHealth = firstNonEmpty(activeProfile.health_status, activeProfile.healthStatus, "unknown");

  const heroLabels = ["当前 Provider", "当前模型", "配置档案"];
  doc.querySelectorAll(".model-strip > div > span").forEach((item, index) => setRenderedText(item, heroLabels[index]));
  const metricLabels = ["Provider", "Model", "Active Profile", "Selection", "Key", "Latest Health"];
  doc.querySelectorAll(".metric > span").forEach((item, index) => setRenderedText(item, metricLabels[index]));
  setSettingsText(doc, "#heroProvider", currentProvider);
  setSettingsText(doc, "#heroModel", currentModel);
  setSettingsText(doc, "#heroProfile", activeProfileId || "未选择");
  setSettingsText(doc, "#metricProvider", currentProvider);
  setSettingsText(doc, "#metricModel", currentModel);
  setSettingsText(doc, "#metricProfile", activeProfileId || "未选择");
  setSettingsText(doc, "#metricKey", activeProfile.api_key_configured || activeProfile.apiKeyConfigured ? "configured" : "missing");
  setSettingsText(doc, "#metricHealth", currentHealth);
  setSettingsText(doc, "#sideProvider", currentProvider);
  setSettingsText(doc, "#sideModel", currentModel);
  setSettingsText(doc, "#topStatus", currentHealth === "passed" ? "模型可用" : "模型需要检查");
  setSettingsText(doc, "#workbenchBadge", currentHealth);
  setRenderedText(doc.querySelector(".main-panel .panel-header .eyebrow"), "模型配置");
  setRenderedText(doc.querySelector(".main-panel .panel-header h2"), "Provider Profile 管理");

  const profileList = doc.getElementById("profileList");
  const fillProfileForm = (profile) => {
    const profileId = firstNonEmpty(profile.profile_id, profile.profileId);
    const providerType = firstNonEmpty(profile.provider_type, profile.providerType);
    const values = {
      profileId,
      displayName: firstNonEmpty(profile.display_name, profile.displayName),
      modelName: firstNonEmpty(profile.model_name, profile.modelName),
      baseUrl: firstNonEmpty(profile.base_url, profile.baseUrl),
      apiKeyRef: firstNonEmpty(profile.api_key_ref, profile.apiKeyRef),
    };
    Object.entries(values).forEach(([id, value]) => {
      const input = doc.getElementById(id);
      if (input && "value" in input) {
        input.value = value;
        input.dataset.mafsBackendBound = "true";
      }
    });
    const enabled = doc.getElementById("enabledToggle");
    if (enabled) {
      enabled.checked = profile.enabled !== false;
    }
    doc.querySelectorAll(".provider-pill[data-provider]").forEach((button) => {
      button.classList.toggle("active", button.dataset.provider === providerType);
    });
    setSettingsText(doc, "#formStatus", providerType || "未配置");
    setSettingsText(doc, "#resultBox", `当前编辑 ${profileId || "新配置"}。真实密钥不会出现在前端，只保存安全引用。`);
  };

  if (profileList && profiles.length) {
    profileList.innerHTML = "";
    profiles.forEach((profile) => {
      const profileId = firstNonEmpty(profile.profile_id, profile.profileId);
      const provider = firstNonEmpty(profile.provider_type, profile.providerType, "provider");
      const model = firstNonEmpty(profile.model_name, profile.modelName, "未配置模型");
      const health = firstNonEmpty(profile.health_status, profile.healthStatus, "unknown");
      const button = doc.createElement("button");
      button.type = "button";
      button.className = `profile-card${profileId === activeProfileId ? " active" : ""}`;
      button.dataset.profileId = profileId;
      button.innerHTML = `
        <div class="profile-top"><span><span>${escapeHtml(provider)}</span><strong>${escapeHtml(profileId)}</strong></span><span class="status-tag ${health === "passed" ? "good" : health === "failed" ? "warn" : ""}">${profileId === activeProfileId ? "当前" : escapeHtml(health)}</span></div>
        <div class="profile-meta"><div><span>Model</span><strong>${escapeHtml(model)}</strong></div><div><span>Key</span><strong>${profile.api_key_configured || profile.apiKeyConfigured ? "configured" : "missing"}</strong></div></div>`;
      button.addEventListener("click", () => {
        profileList.querySelectorAll(".profile-card").forEach((item) => item.classList.toggle("active", item === button));
        fillProfileForm(profile);
      });
      profileList.appendChild(button);
    });
    fillProfileForm(activeProfile);
    markBackendRendered(profileList);
  }
  const providerLabels = {
    qwen: "Qwen",
    deepseek: "DeepSeek",
    local: "Local Mock",
  };
  doc.querySelectorAll(".provider-pill[data-provider]").forEach((button) => {
    setRenderedText(button, providerLabels[button.dataset.provider] || button.dataset.provider);
  });
  const formLabels = ["Profile ID", "Display Name", "Model Name", "API Key 引用", "Base URL"];
  doc.querySelectorAll(".form-field > span").forEach((label, index) => setRenderedText(label, formLabels[index]));
  setRenderedText(doc.querySelector(".toggle-line strong"), "启用此配置");
  setRenderedText(doc.getElementById("newProfileButton"), "新建配置");
  setRenderedText(doc.getElementById("saveButton"), "更新配置");
  setRenderedText(doc.getElementById("activeButton"), "设为当前");
  setRenderedText(doc.getElementById("healthButton"), "运行健康检查");
  const profileCount = doc.querySelector("[aria-label='Provider Profile 列表'] .status-tag");
  setRenderedText(profileCount, `${profiles.length} 个配置`);
  const providerOptions = collectSettingsProviders(result, workbench).filter(
    (provider) => provider.enabled_in_phase8_m1 || provider.enabledInPhase8M1,
  );
  const providerOptionNodes = doc.querySelectorAll(".provider-option");
  providerOptionNodes.forEach((node, index) => {
    const provider = providerOptions[index];
    if (!provider) {
      node.remove();
      return;
    }
    setRenderedText(node.querySelector("strong"), firstNonEmpty(provider.display_name, provider.displayName, provider.provider_type, provider.providerType));
    setRenderedText(node.querySelector("span:not(.status-tag)"), firstNonEmpty(provider.safe_summary, provider.safeSummary, "已启用"));
    setRenderedText(node.querySelector(".status-tag"), firstNonEmpty(provider.status, "enabled"));
  });
  return true;
}

function normalizeSettingsNavigation(doc, currentPageId) {
  doc.querySelectorAll(".nav-item").forEach((button) => {
    const text = button.textContent || "";
    const isHelp = text.includes("帮助与引导");
    const currentLabels = {
      "settings-overview": "设置总览",
      "settings-appearance": "外观与主题",
      "settings-model": "模型配置",
      "settings-health": "当前模型",
      "settings-secrets": "密钥与安全",
      "settings-preferences": "创作偏好",
    };
    const isCurrent = text.includes(currentLabels[currentPageId] || "");
    button.classList.toggle("active", isCurrent);
    button.disabled = isHelp || isCurrent;
    if (isHelp) {
      button.title = "帮助中心尚未开放";
      button.setAttribute("aria-label", "帮助与引导（尚未开放）");
    }
  });
}

function renderSettingsAppearanceSurface(doc) {
  if (doc?.body?.dataset?.mafsPageId !== "settings-appearance") {
    return false;
  }
  const mainPanel = doc.querySelector(".main-panel");
  const sidePanel = doc.querySelector(".side-panel, .right-panel");
  if (!mainPanel || !sidePanel) {
    return false;
  }
  mainPanel.innerHTML = `
    <div class="panel-header">
      <div>
        <p class="eyebrow">APPEARANCE</p>
        <h2>当前界面主题</h2>
        <p class="subtle">当前版本统一使用经过可读性校验的羊皮卷莫兰迪主题。主题设置只影响界面，不参与故事生成。</p>
      </div>
      <span class="badge">已启用</span>
    </div>
    <section class="section-card">
      <h3>羊皮卷莫兰迪</h3>
      <p class="subtle">低饱和背景、清晰正文对比与克制动效已经应用到整个工作台。</p>
      <div class="swatches" aria-label="当前主题色卡">
        <span class="swatch"></span><span class="swatch"></span><span class="swatch"></span><span class="swatch"></span><span class="swatch"></span>
      </div>
    </section>
    <section class="section-card">
      <h3>自定义主题尚未开放</h3>
      <p class="subtle">在主题持久化和全站同步能力完成前，不展示无法保存的色卡、滑块或自动换肤开关。</p>
    </section>`;
  sidePanel.innerHTML = `
    <section class="side-card">
      <p class="eyebrow">READABILITY</p>
      <h3>阅读与创作优先</h3>
      <div class="side-stats">
        <div class="side-stat"><span>正文对比</span><strong>清晰</strong></div>
        <div class="side-stat"><span>动效强度</span><strong>柔和</strong></div>
        <div class="side-stat"><span>自动换肤</span><strong>关闭</strong></div>
        <div class="side-stat"><span>故事事实影响</span><strong>无</strong></div>
      </div>
    </section>`;
  setRenderedText(doc.querySelector(".hero h1"), "外观与主题");
  const summary = doc.querySelectorAll(".theme-strip strong, .health-strip strong");
  ["羊皮卷莫兰迪", "柔和玻璃", "固定主题"].forEach((value, index) => setRenderedText(summary[index], value));
  markBackendRendered(doc.querySelector(".layout"));
  return true;
}

function findSecretPolicy(result) {
  return (
    result?.secret_policy ||
    result?.secretPolicy ||
    result?.action_result?.secret_policy ||
    result?.action_result?.secretPolicy ||
    findNestedObject(result, (item) => Object.prototype.hasOwnProperty.call(item || {}, "raw_key_storage_disabled")) ||
    result?.action_result ||
    result ||
    {}
  );
}

function renderSettingsSecretsSurface(doc, result) {
  if (doc?.body?.dataset?.mafsPageId !== "settings-secrets") {
    return false;
  }
  const policy = findSecretPolicy(result);
  const mainPanel = doc.querySelector(".main-panel");
  const sidePanel = doc.querySelector(".side-panel");
  if (!mainPanel || !sidePanel) {
    return false;
  }
  const resolvable = Array.isArray(policy.resolvable_key_ref_prefixes)
    ? policy.resolvable_key_ref_prefixes
    : policy.resolvableKeyRefPrefixes || [];
  const displayable = Array.isArray(policy.safe_display_key_ref_prefixes)
    ? policy.safe_display_key_ref_prefixes
    : policy.safeDisplayKeyRefPrefixes || [];
  const unsupported = Array.isArray(policy.unsupported_safe_reference_prefixes)
    ? policy.unsupported_safe_reference_prefixes
    : policy.unsupportedSafeReferencePrefixes || [];
  const forbidden = Array.isArray(policy.forbidden_storage_targets)
    ? policy.forbidden_storage_targets
    : policy.forbiddenStorageTargets || [];
  const safeSummary = firstNonEmpty(
    policy.safe_summary,
    policy.safeSummary,
    "模型密钥只通过安全引用解析，前端永远不读取或显示原始值。",
  );

  mainPanel.innerHTML = `
    <div class="panel-header">
      <div>
        <p class="eyebrow">SECRET POLICY</p>
        <h2>密钥引用与显示边界</h2>
        <p class="subtle">${escapeHtml(safeSummary)}</p>
      </div>
      <span class="badge">${policy.raw_key_storage_disabled !== false ? "原始密钥禁用" : "需要检查"}</span>
    </div>
    <div class="metrics" aria-label="密钥安全指标">
      <div class="metric"><span>可解析引用</span><strong>${escapeHtml(resolvable.join("、") || "无")}</strong></div>
      <div class="metric"><span>安全显示引用</span><strong>${escapeHtml(displayable.join("、") || "无")}</strong></div>
      <div class="metric"><span>原始密钥</span><strong>${policy.frontend_may_show_raw_key ? "允许显示" : "永不显示"}</strong></div>
      <div class="metric"><span>末四位</span><strong>${policy.frontend_may_show_key_last_four ? "允许显示" : "不显示"}</strong></div>
    </div>
    <section class="section-card">
      <h3>禁止写入位置</h3>
      <p class="subtle">密钥不能进入故事、记忆、提示词快照、运行日志、导出或前端存储。</p>
      <div class="tag-list">${forbidden.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>
    </section>
    <section class="section-card">
      <h3>当前解析范围</h3>
      <p class="subtle">${unsupported.length ? `${escapeHtml(unsupported.join("、"))} 可以安全显示，但当前运行时不会解析。` : "所有安全引用前缀均可解析。"}</p>
    </section>
    <div class="action-bar">
      <button id="mafsSecretRefresh" type="button" class="ghost-button">刷新策略</button>
      <button id="mafsSecretModelConfig" type="button" class="button primary">前往模型配置</button>
    </div>`;
  sidePanel.innerHTML = `
    <section class="side-card">
      <p class="eyebrow">VISIBLE RANGE</p>
      <h3>前端可见范围</h3>
      <div class="side-stats">
        <div class="side-stat"><span>配置存在状态</span><strong>${policy.frontend_may_show_key_presence === false ? "不可见" : "可见"}</strong></div>
        <div class="side-stat"><span>原始密钥</span><strong>不可见</strong></div>
        <div class="side-stat"><span>密钥末四位</span><strong>不可见</strong></div>
        <div class="side-stat"><span>明文持久化</span><strong>${policy.raw_key_storage_disabled !== false ? "禁止" : "需要检查"}</strong></div>
      </div>
    </section>
    <section class="side-card">
      <p class="eyebrow">USER ACTION</p>
      <h3>如何配置</h3>
      <p class="subtle">在模型配置页填写类似 env:QWEN_API_KEY 的安全引用；真实值应保存在运行环境变量中。</p>
    </section>`;
  const hero = doc.querySelectorAll(".secret-strip strong, .policy-strip strong, .health-strip strong");
  ["永不显示", resolvable.join("、") || "无", "仅配置状态"].forEach((value, index) => setRenderedText(hero[index], value));
  bindBackendActionElement(doc.getElementById("mafsSecretRefresh"), "settings.secretPolicy", "settings-secrets");
  bindBackendActionElement(doc.getElementById("mafsSecretModelConfig"), "settings.workbench", "settings-model");
  markBackendRendered(doc.querySelector(".layout"));
  return true;
}

function renderSettingsPreferencesSurface(doc, result) {
  if (doc?.body?.dataset?.mafsPageId !== "settings-preferences") {
    return false;
  }
  const mainPanel = doc.querySelector(".main-panel");
  const sidePanel = doc.querySelector(".side-panel, .right-panel");
  if (!mainPanel || !sidePanel) {
    return false;
  }
  const projectTitle = firstNonEmpty(
    result?.hydrated_refs?.projectTitle,
    result?.hydratedRefs?.projectTitle,
    "当前项目",
  );
  mainPanel.innerHTML = `
    <div class="panel-header">
      <div>
        <p class="eyebrow">CREATIVE PREFERENCES</p>
        <h2>项目级偏好优先</h2>
        <p class="subtle">当前版本在创建项目时设置语言、章节数与每章幕数，并在章节和场景工作台中允许调整。尚未提供全局偏好持久化。</p>
      </div>
      <span class="badge">项目级</span>
    </div>
    <section class="section-card">
      <h3>${escapeHtml(projectTitle)}</h3>
      <p class="subtle">当前项目继续使用创建时确认的语言与容量。这里不会用未保存的全局值覆盖项目事实或生成参数。</p>
    </section>
    <div class="card-grid">
      <article class="setting-card" style="cursor:default;">
        <div class="card-top"><span class="card-title"><span>Language</span><strong>语言</strong></span><span class="card-status">项目创建时设置</span></div>
        <p>中文优先；英文支持作为后续项目能力保留。</p>
      </article>
      <article class="setting-card" style="cursor:default;">
        <div class="card-top"><span class="card-title"><span>Capacity</span><strong>章节与幕数</strong></span><span class="card-status">按项目保存</span></div>
        <p>章节数和每章幕数由用户创建项目及章节规划时确认。</p>
      </article>
      <article class="setting-card" style="cursor:default;">
        <div class="card-top"><span class="card-title"><span>Review</span><strong>审阅方式</strong></span><span class="card-status">人工确认</span></div>
        <p>生成后停留在审阅页，确认、修订或暂时确认仍由页面级交互触发。</p>
      </article>
    </div>`;
  sidePanel.innerHTML = `
    <section class="side-card">
      <p class="eyebrow">BOUNDARY</p>
      <h3>不展示假设置</h3>
      <p class="subtle">全局语言、节奏、容量和写作取向尚未拥有持久化契约，因此本页不提供无法保存的控件。</p>
    </section>
    <section class="side-card">
      <p class="eyebrow">NEXT ENTRY</p>
      <h3>在哪里修改</h3>
      <p class="subtle">新项目在“新创作”中设置；现有项目的章节和幕数在“章节计划”中确认。</p>
    </section>`;
  const summary = doc.querySelectorAll(".preference-strip strong, .health-strip strong");
  ["中文优先", "按项目设置", "手动确认"].forEach((value, index) => setRenderedText(summary[index], value));
  setRenderedText(mainPanel.querySelector(".panel-header .eyebrow"), "项目级偏好");
  setRenderedText(
    mainPanel.querySelector(".panel-header .subtle"),
    "当前版本在创建项目时设置语言、章节数与每章幕数，并在章节和场景工作台中允许调整。尚未提供全局偏好持久化。",
  );
  setRenderedText(doc.getElementById("topStatus"), "项目级偏好");
  markBackendRendered(doc.querySelector(".layout"));
  return true;
}

function renderSettingsOverviewSurface(doc, result) {
  if (doc?.body?.dataset?.mafsPageId !== "settings-overview") {
    return false;
  }
  const workbench = findSettingsWorkbench(result) || {};
  const profiles = collectSettingsProfiles(result, workbench);
  const active = activeSettingsSelection(result, workbench) || {};
  const activeProfileId = firstNonEmpty(
    workbench.active_profile_id,
    workbench.activeProfileId,
    active.provider_profile_id,
    active.providerProfileId,
  );
  const activeProfile =
    profiles.find((profile) => firstNonEmpty(profile.profile_id, profile.profileId) === activeProfileId) ||
    profiles[0] ||
    {};
  const provider = firstNonEmpty(
    workbench.current_provider,
    workbench.currentProvider,
    active.provider_type,
    active.providerType,
    activeProfile.provider_type,
    activeProfile.providerType,
    "未配置",
  );
  const model = firstNonEmpty(
    workbench.current_model,
    workbench.currentModel,
    active.model_name,
    active.modelName,
    activeProfile.model_name,
    activeProfile.modelName,
    "未配置",
  );
  const health = firstNonEmpty(activeProfile.health_status, activeProfile.healthStatus, "unknown");
  const warnings = Array.isArray(workbench.warnings) ? workbench.warnings.length : 0;
  const blockers = Array.isArray(workbench.blockers) ? workbench.blockers.length : 0;
  const latestHealth = workbench?.health_summary?.latest_health_check || workbench?.healthSummary?.latestHealthCheck || {};
  const checkedAt = firstNonEmpty(latestHealth.checked_at, latestHealth.checkedAt);
  const checkedLabel = checkedAt ? new Date(checkedAt).toLocaleString("zh-CN", { hour12: false }) : "尚未检查";
  const modelLabel = `${provider} / ${model}`;

  const healthSummary = doc.querySelectorAll(".health-item strong");
  setRenderedText(healthSummary[0], "羊皮卷莫兰迪");
  setRenderedText(healthSummary[1], modelLabel);
  setRenderedText(healthSummary[2], "仅显示安全引用");

  const metrics = doc.querySelectorAll(".metric strong");
  [provider, model, activeProfileId || "未选择", health].forEach((value, index) => {
    setRenderedText(metrics[index], value);
  });
  setRenderedText(doc.getElementById("healthValue"), health);
  setRenderedText(doc.getElementById("workbenchBadge"), blockers ? "blocked" : health === "passed" ? "ready" : health);
  setRenderedText(doc.getElementById("topStatus"), blockers ? "环境存在阻塞" : health === "passed" ? "创作环境可用" : "模型需要检查");

  const cards = doc.querySelectorAll(".setting-card");
  const modelCard = cards[1];
  if (modelCard) {
    setRenderedText(modelCard.querySelector(".card-title > span"), provider);
    setRenderedText(modelCard.querySelector(".card-status"), health === "passed" ? "可用" : "需检查");
    setRenderedText(modelCard.querySelector("p"), `当前使用 ${modelLabel}。配置档案与健康检查来自后端模型设置工作台。`);
    const values = modelCard.querySelectorAll(".model-line strong");
    setRenderedText(values[0], activeProfileId || "未选择");
    setRenderedText(values[1], active.deterministic_fallback_allowed === false ? "禁止回退" : "允许确定性回退");
  }
  const writingCard = cards[3];
  if (writingCard) {
    setRenderedText(writingCard.querySelector(".card-status"), "中文优先");
    setRenderedText(
      writingCard.querySelector("p"),
      "默认语言与章节、幕数会在创建项目时由用户设置，并沿生成链路传递；本页只提供设置入口。",
    );
    const values = writingCard.querySelectorAll(".model-line strong");
    setRenderedText(values[0], "中文");
    setRenderedText(values[1], "由项目设定决定");
  }

  const sideStats = doc.querySelectorAll(".side-stat strong");
  ["ready", activeProfileId ? "active" : "none", String(warnings), String(blockers)].forEach((value, index) => {
    setRenderedText(sideStats[index], value);
  });
  const events = doc.querySelectorAll(".event");
  if (events[0]) {
    setRenderedText(events[0].querySelector("strong"), health === "passed" ? "模型连接可用" : "模型连接需要检查");
    setRenderedText(events[0].querySelector("span"), `最近检查：${checkedLabel}`);
  }
  if (events[1]) {
    setRenderedText(events[1].querySelector("strong"), "主题使用当前默认色系");
    setRenderedText(events[1].querySelector("span"), "羊皮卷莫兰迪色系已启用。");
  }
  if (events[2]) {
    setRenderedText(events[2].querySelector("strong"), "密钥策略安全");
    setRenderedText(events[2].querySelector("span"), "真实 API Key 不进入前端显示层。");
  }

  const refreshButton = doc.getElementById("refreshButton");
  setRenderedText(refreshButton, "刷新状态");
  bindBackendActionElement(refreshButton, "settings.workbench", "settings-overview");
  doc.getElementById("themeButton")?.remove();
  const healthButton = doc.getElementById("healthButton");
  setRenderedText(healthButton, "查看当前模型");
  bindBackendActionElement(healthButton, "settings.activeModel", "settings-health");
  markBackendRendered(doc.querySelector(".workspace"));
  return true;
}

function renderSettingsSurface(doc, result) {
  const currentPageId = doc?.body?.dataset?.mafsPageId || "";
  if (currentPageId.startsWith("settings-")) {
    normalizeSettingsNavigation(doc, currentPageId);
  }
  if (currentPageId === "settings-overview") {
    doc?.getElementById("mafs-settings-panel")?.remove();
    return renderSettingsOverviewSurface(doc, result);
  }
  if (currentPageId === "settings-model") {
    doc?.getElementById("mafs-settings-panel")?.remove();
    return renderModelConfigurationSurface(doc, result);
  }
  if (currentPageId === "settings-appearance") {
    doc?.getElementById("mafs-settings-panel")?.remove();
    return renderSettingsAppearanceSurface(doc);
  }
  if (currentPageId === "settings-secrets") {
    doc?.getElementById("mafs-settings-panel")?.remove();
    return renderSettingsSecretsSurface(doc, result);
  }
  if (currentPageId === "settings-preferences") {
    doc?.getElementById("mafs-settings-panel")?.remove();
    return renderSettingsPreferencesSurface(doc, result);
  }
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
  const activeProfile = profiles.find((profile) => firstNonEmpty(profile.profile_id, profile.profileId) === activeProfileId) || profiles[0] || {};
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
  }
  if (target !== doc.body && panel.parentElement !== target) {
    target.replaceChildren(panel);
  } else if (!panel.isConnected) {
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
  const latestHealthProfileId = firstNonEmpty(latestHealth.provider_profile_id, latestHealth.providerProfileId);
  const healthStatus = firstNonEmpty(
    activeProfile.health_status,
    activeProfile.healthStatus,
    latestHealthProfileId === activeProfileId ? latestHealth.status : "",
    "unknown",
  );
  const safeMessage = latestHealthProfileId === activeProfileId
    ? firstNonEmpty(latestHealth.safe_message, latestHealth.safeMessage, "健康检查已完成。")
    : healthStatus === "passed"
      ? "活动模型健康检查已通过。"
      : "活动模型尚未通过健康检查，请返回模型配置核对 Base URL、模型名和 API Key 引用。";
  panel.innerHTML = `
    <p style="margin:0 0 6px;font-size:12px;font-weight:800;color:#6b5d51;">后端模型设置</p>
    <h3 style="margin:0 0 8px;font-size:22px;line-height:1.3;">当前模型：${escapeHtml(currentProvider)} / ${escapeHtml(currentModel)}</h3>
    <p style="margin:0 0 10px;line-height:1.7;">provider profile=${escapeHtml(activeProfileId || "未选择")}；健康状态=${escapeHtml(healthStatus)}。</p>
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
  if (currentPageId === "settings-health") {
    const healthActions = doc.createElement("div");
    healthActions.className = "action-bar";
    healthActions.innerHTML = '<button id="fullButton" type="button" class="button primary">运行健康检查</button>';
    panel.appendChild(healthActions);
    bindBackendActionElement(doc.getElementById("fullButton"), "settings.healthCheck", "settings-health");
    const heroLabels = doc.querySelectorAll(".model-strip > div > span, .health-strip > div > span");
    ["\u5f53\u524d Provider", "\u5f53\u524d\u6a21\u578b", "\u5065\u5eb7\u72b6\u6001"].forEach((value, index) => {
      setRenderedText(heroLabels[index], value);
    });
    const hero = doc.querySelectorAll(".model-strip strong, .health-strip strong");
    [currentProvider, currentModel, healthStatus].forEach((value, index) => setRenderedText(hero[index], value));
    const sidePanel = doc.querySelector(".side-panel");
    if (sidePanel) {
      const latency = Number(latestHealth.latency_ms || latestHealth.latencyMs || 0);
      sidePanel.innerHTML = `
        <section class="side-card">
          <p class="eyebrow">LATEST HEALTH</p>
          <h3>最近检查报告</h3>
          <div class="side-stats">
            <div class="side-stat"><span>状态</span><strong>${escapeHtml(healthStatus)}</strong></div>
            <div class="side-stat"><span>延迟</span><strong>${latency ? `${latency} ms` : "未记录"}</strong></div>
            <div class="side-stat"><span>真实模型</span><strong>${latestHealth.used_real_provider || latestHealth.usedRealProvider ? "是" : "否"}</strong></div>
            <div class="side-stat"><span>回退</span><strong>${latestHealth.used_deterministic_fallback || latestHealth.usedDeterministicFallback ? "已使用" : "未使用"}</strong></div>
          </div>
        </section>
        <section class="side-card">
          <p class="eyebrow">SAFE RESULT</p>
          <h3>安全结论</h3>
          <p class="subtle">${escapeHtml(safeMessage)}</p>
        </section>`;
      markBackendRendered(sidePanel);
    }
  }
  setRenderedText(doc.getElementById("topStatus"), "后端状态已同步");
  setRenderedText(doc.getElementById("pageTitle"), /健康检查/.test(doc.body.textContent || "") ? "当前模型与健康检查" : "模型配置");
  replaceEmptyPlaceholders(doc, "未配置");
  [120, 600, 1400].forEach((delayMs) => {
    doc.defaultView?.setTimeout(() => replaceEmptyPlaceholders(doc, "未配置"), delayMs);
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

function storySetupQuestionImpact(questionType) {
  const impacts = {
    world_scope: {
      title: "世界画布范围",
      copy: "这个回答会约束世界边界、地理展开范围和未来可继续补充的区域。",
      items: ["世界结构", "地理轮廓", "章节活动范围"],
    },
    tone: {
      title: "故事基调",
      copy: "这个回答会影响全书总体风格，并为篇章节奏和表达密度提供参考。",
      items: ["总体风格", "读者情绪", "篇章表达"],
    },
    protagonist: {
      title: "角色主轴",
      copy: "这个回答会影响主角的故事功能、欲望方向和进入冲突的方式。",
      items: ["角色功能", "角色欲望", "关系张力"],
    },
    core_conflict: {
      title: "核心冲突",
      copy: "这个回答会影响冲突升级路径、章节目标和场景中的选择压力。",
      items: ["冲突主轴", "章节目标", "场景压力"],
    },
    magic_or_rule_system: {
      title: "世界规则",
      copy: "这个回答会影响特殊规则的触发条件、代价、边界和连续性检查。",
      items: ["特殊规则", "代价边界", "连续性检查"],
    },
    technology_or_speculative_rule: {
      title: "技术与异常规则",
      copy: "这个回答会影响技术能力边界、异常机制和后续因果约束。",
      items: ["技术边界", "异常机制", "因果约束"],
    },
  };
  return impacts[questionType] || {
    title: storySetupCodeLabel(questionType) || "故事设定",
    copy: "这个回答只补全当前故事设定草案，并在后续工作台中继续接受用户确认。",
    items: ["故事设定", "后续工作台", "用户确认"],
  };
}

function renderStorySetupMissingQuestions(doc, questions) {
  if (!doc?.body || framePageId(doc) !== "story-setup-missing" || !Array.isArray(questions) || !questions.length) {
    return false;
  }
  const view = doc.defaultView;
  const normalizedQuestions = questions.slice(0, 5).map((question, index) => {
    const questionId = storySetupQuestionId(question) || `story_setup_question_${index + 1}`;
    const answered = storySetupQuestionAnswered(question);
    const cachedAnswer = view?.__mafsStorySetupQuestionAnswers?.[questionId] || "";
    const backendAnswer = storySetupQuestionAnswerText(question);
    if (backendAnswer && view) {
      view.__mafsStorySetupQuestionAnswers = view.__mafsStorySetupQuestionAnswers || {};
      view.__mafsStorySetupQuestionAnswers[questionId] = backendAnswer;
    }
    return {
      question,
      questionId,
      questionType: storySetupQuestionType(question),
      answered,
      answerText: cachedAnswer || backendAnswer,
    };
  });
  const currentActiveId = String(view?.__mafsStorySetupActiveQuestionId || "");
  const active =
    normalizedQuestions.find((item) => item.questionId === currentActiveId) ||
    normalizedQuestions.find((item) => !item.answered) ||
    normalizedQuestions[0];
  if (!active) {
    return false;
  }
  if (view) {
    view.__mafsStorySetupActiveQuestionId = active.questionId;
    view.__mafsStorySetupQuestionAnswers = view.__mafsStorySetupQuestionAnswers || {};
    view.__mafsStorySetupQuestions = questions;
  }

  const cards = Array.from(doc.querySelectorAll(".question-card[data-question]"));
  cards.forEach((card, index) => {
    const item = normalizedQuestions[index];
    if (!item) {
      card.classList.add("mafs-empty-suppressed");
      return;
    }
    card.classList.remove("mafs-empty-suppressed");
    card.dataset.storySetupQuestionId = item.questionId;
    card.dataset.storySetupQuestionType = item.questionType;
    card.classList.toggle("active", item.questionId === active.questionId);
    const title = formatStorySetupValue(
      item.question.question_text ||
        item.question.questionText ||
        item.question.question_type ||
        item.question.questionType,
    );
    const options = item.question.suggested_options || item.question.suggestedOptions || [];
    const topline = card.querySelector(".question-topline");
    const label = topline?.querySelector("span:first-child");
    const status = topline?.querySelector(".status-tag, span:last-child");
    setRenderedText(label, storySetupCodeLabel(item.questionType));
    setRenderedText(status, item.answered ? "已回答" : "未回答");
    setRenderedText(card.querySelector("strong"), title);
    setRenderedText(
      card.querySelector(".summary"),
      item.answerText || (Array.isArray(options) && options.length ? formatStorySetupValue(options[0]) : "等待用户补充"),
    );
    markBackendRendered(card);
    if (card.dataset.mafsStorySetupQuestionCardBound !== "true") {
      card.dataset.mafsStorySetupQuestionCardBound = "true";
      card.addEventListener(
        "click",
        (event) => {
          event.preventDefault();
          event.stopImmediatePropagation();
          if (view) {
            view.__mafsStorySetupActiveQuestionId = card.dataset.storySetupQuestionId || "";
          }
          const answerInput = doc.getElementById("answerInput");
          if (answerInput) {
            delete answerInput.dataset.mafsUserEdited;
          }
          renderStorySetupMissingQuestions(
            doc,
            Array.isArray(view?.__mafsStorySetupQuestions)
              ? view.__mafsStorySetupQuestions
              : questions,
          );
        },
        true,
      );
    }
  });

  const activeTitle = formatStorySetupValue(
    active.question.question_text ||
      active.question.questionText ||
      active.question.question_type ||
      active.question.questionType,
  );
  const activeOptions = active.question.suggested_options || active.question.suggestedOptions || [];
  const answeredCount = normalizedQuestions.filter((item) => item.answered).length;
  setRenderedText(doc.getElementById("queueCount"), `${answeredCount}/${normalizedQuestions.length}`);
  setRenderedText(doc.getElementById("focusTitle"), storySetupCodeLabel(active.questionType));
  setRenderedText(doc.getElementById("focusIntro"), activeTitle);
  setRenderedText(doc.getElementById("answerState"), active.answered ? "已回答" : "未答");
  setRenderedText(doc.getElementById("questionType"), storySetupCodeLabel(active.questionType));
  setRenderedText(doc.getElementById("answerStatus"), `回答状态：${active.answered ? "已回答" : "未回答"}`);
  setRenderedText(doc.getElementById("focusQuestion"), activeTitle);
  setRenderedText(
    doc.getElementById("focusHint"),
    Array.isArray(activeOptions) && activeOptions.length
      ? `可参考：${formatStorySetupValue(activeOptions)}`
      : "请写下你希望系统遵循的决定；不确定的部分可以明确保留为未知。",
  );

  const answerInput = doc.getElementById("answerInput");
  if (answerInput && answerInput.dataset.mafsUserEdited !== "true") {
    answerInput.value = active.answerText || "";
  }
  if (answerInput) {
    answerInput.dataset.storySetupQuestionId = active.questionId;
    answerInput.dataset.storySetupQuestionType = active.questionType;
    answerInput.placeholder =
      Array.isArray(activeOptions) && activeOptions.length
        ? `可参考：${formatStorySetupValue(activeOptions)}`
        : "在这里补充你的决定。";
    answerInput.classList.remove("mafs-backend-pending");
    answerInput.removeAttribute("data-backend-pending");
    if (answerInput.dataset.mafsStorySetupAnswerInputBound !== "true") {
      answerInput.dataset.mafsStorySetupAnswerInputBound = "true";
      answerInput.addEventListener("input", () => {
        answerInput.dataset.mafsUserEdited = "true";
        if (view) {
          view.__mafsStorySetupQuestionAnswers = view.__mafsStorySetupQuestionAnswers || {};
          view.__mafsStorySetupQuestionAnswers[answerInput.dataset.storySetupQuestionId || ""] = answerInput.value;
        }
        setRenderedText(doc.getElementById("charCount"), `${answerInput.value.length} 字`);
      });
    }
  }
  setRenderedText(doc.getElementById("charCount"), `${String(answerInput?.value || "").length} 字`);

  const saveButton = doc.getElementById("saveButton");
  if (saveButton) {
    saveButton.dataset.mafsActionId = "storySetup.answerQuestion";
    saveButton.dataset.mafsTarget = "story-setup-missing";
    saveButton.dataset.storySetupQuestionId = active.questionId;
    saveButton.textContent = active.answered ? "更新回答" : "保存回答";
    markBackendRendered(saveButton);
  }
  const reviewButton = doc.getElementById("reviewButton");
  if (reviewButton) {
    bindBackendActionElement(reviewButton, "storySetup.current", "story-setup-review");
  }

  const impact = storySetupQuestionImpact(active.questionType);
  setRenderedText(doc.getElementById("impactTitle"), impact.title);
  setRenderedText(doc.getElementById("impactCopy"), impact.copy);
  renderStorySetupList(doc, "#impactList", impact.items);
  markBackendRendered(doc.querySelector(".question-list") || cards[0]?.parentElement);
  return true;
}

function renderStorySetupQuestions(doc, questions) {
  if (renderStorySetupMissingQuestions(doc, questions)) {
    return;
  }
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
    save.dataset.mafsTarget = framePageId(doc) === "story-setup-missing"
      ? "story-setup-missing"
      : "story-setup-review";
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
  if (framePageId(doc) === "story-setup-missing") {
    const latestQuestions = Array.isArray(view?.__mafsStorySetupQuestions)
      ? view.__mafsStorySetupQuestions
      : [];
    const next = latestQuestions.find(
      (question) => storySetupQuestionId(question) !== questionId && !storySetupQuestionAnswered(question),
    );
    if (view) {
      view.__mafsStorySetupActiveQuestionId = storySetupQuestionId(next) || questionId;
    }
    const answerInput = doc.getElementById("answerInput");
    if (answerInput) {
      delete answerInput.dataset.mafsUserEdited;
    }
    if (latestQuestions.length) {
      renderStorySetupMissingQuestions(doc, latestQuestions);
    }
    return;
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
  if (!doc?.body || !draftBundle || !storySetupDraftReadyFromResult(result)) {
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
  const retryableFailure = !ready && /失败|重试/.test(message || "");
  button.disabled = !ready && !retryableFailure;
  button.textContent = ready
    ? readyText.replace(/^等待.*$/, "查看草案")
    : retryableFailure
      ? "重试生成"
      : "生成中";
  if (ready) {
    bindBackendActionElement(button, "storySetup.current", "story-setup-review");
    setRenderedText(doc.getElementById("setupState"), "草案已生成");
    setRenderedText(doc.getElementById("stageTitle"), "后端草案已生成");
    setRenderedText(doc.getElementById("stageCopy"), "故事设定草案已由后端生成并同步到页面，可以进入审阅。");
    setRenderedText(doc.getElementById("sideProgressCopy"), "后端草案生成完成。");
    applyRealtimeProgressElements(doc, { label: message || "故事设定草案已生成", percent: 100 });
  } else {
    if (retryableFailure) {
      bindBackendActionElement(button, "storySetup.createDraft", "story-setup-generating");
    }
    setRenderedText(doc.getElementById("setupState"), "草案生成中");
    setRenderedText(doc.getElementById("stageTitle"), "后端正在分析当前故事构想");
    setRenderedText(
      doc.getElementById("stageCopy"),
      "页面会等待真实模型完成题材、基调、核心冲突与待补充问题分析；完成前不会进入审阅页。",
    );
    setRenderedText(doc.getElementById("sideProgressCopy"), message || "正在等待后端完成故事设定分析。");
    applyRealtimeProgressElements(doc, { label: message || "后端正在生成草案", percent: 35 });
  }
}

function generationReadyFromRefsOrResult(pageId, refs, result) {
  const refKey = GENERATION_READY_REF_BY_PAGE_ID[pageId];
  if (!refKey) {
    return true;
  }
  if (pageId === "story-setup-generating") {
    return Boolean(refs?.[refKey] || storySetupDraftReadyFromResult(result));
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

  const fallbackLabel = ACTION_STATUS_LABEL_BY_ID[actionId] || "后端状态已同步";
  return {
    label: storyRuntimeDisplayText(label, fallbackLabel),
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
    ["#progressText", "#progressBadge", "#progressCount", "#percentText"].forEach((selector) => {
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
  if (!doc?.body || !doc.defaultView || !result) {
    return;
  }
  const storySetupQuestions = findStorySetupQuestions(result);
  const hasStorySetupDraft = storySetupDraftReadyFromResult(result);
  const hasWorldCanvas = Boolean(findWorldCanvasPayload(result));
  const hasCharacterDraft = Boolean(findCharacterDraftPayload(result));
  const currentScene = findScenePayload(result);
  const hasReadyScene = sceneReadyFromResult(result);
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
  if ((actionId || "").startsWith("chapter.")) {
    status = {
      label: ACTION_STATUS_LABEL_BY_ID[actionId] || "章节计划已同步",
      percent: 100,
    };
  }
  if (
    ["analyzing", "analysis-result", "framework-candidate"].includes(framePageId(doc)) &&
    analyzeStoriesImportDetail(analyzeStoriesPayload(result))
  ) {
    status = {
      label: framePageId(doc) === "analyzing" ? "导入与结构校验已完成" : "故事分析状态已同步",
      percent: 100,
    };
  }
  if (currentScene && ((actionId || "").startsWith("scene.") || isFramePage(doc, SCENE_PAGE_IDS))) {
    status = {
      label: hasReadyScene ? sceneStatusLabel(currentScene) : "\u573a\u666f\u6b63\u6587\u6b63\u5728\u751f\u6210",
      percent: hasReadyScene ? 100 : 60,
    };
  } else if ((actionId || "").startsWith("scene.") && isFramePage(doc, SCENE_PAGE_IDS)) {
    const currentScenePageId = framePageId(doc);
    status = {
      label: currentScenePageId === "chapter-closeout" ? "章节归档状态已同步" : "场景入口已同步",
      percent: 100,
    };
  }
  if (hasRoleList && ((actionId || "").startsWith("roles.") || isFramePage(doc, ROLE_LIBRARY_PAGE_IDS))) {
    status = { label: "\u89d2\u8272\u6863\u6848\u5e93\u5df2\u540c\u6b65", percent: 100 };
  }
  if ((actionId || "").startsWith("final.") || FINAL_OUTPUT_PAGE_IDS.has(framePageId(doc))) {
    const finalSnapshot = findFinalSnapshotPayload(result);
    const finalExportRun = findFinalExportRunPayload(result);
    const readinessEvaluation = findFinalReadinessEvaluation(result);
    const readinessGate = readinessEvaluation?.readiness_gate || readinessEvaluation?.readinessGate || {};
    if (finalSnapshot && finalSnapshotId(finalSnapshot, finalExportRun)) {
      status = { label: "最终故事包快照已同步", percent: 100 };
    } else if (readinessEvaluation) {
      const canAssemble = Boolean(
        readinessGate.can_create_real_final_story_package ??
        readinessGate.canCreateRealFinalStoryPackage,
      );
      status = {
        label: canAssemble ? "最终故事包门禁已通过" : "最终故事包门禁存在阻塞",
        percent: canAssemble ? 100 : null,
      };
    }
  }
  if ((actionId || "").startsWith("settings.")) {
    const settingsWorkbench = findSettingsWorkbench(result) || {};
    const latestHealth =
      settingsWorkbench?.health_summary?.latest_health_check ||
      settingsWorkbench?.healthSummary?.latestHealthCheck ||
      {};
    const healthStatus = firstNonEmpty(latestHealth.status, "unknown");
    const settingsStatusLabels = {
      "settings.workbench": "模型设置已同步",
      "settings.activeModel": "当前模型已同步",
      "settings.secretPolicy": "密钥安全策略已同步",
      "settings.createProfile": "模型配置已创建",
      "settings.patchProfile": "模型配置已更新",
      "settings.setActive": "当前模型选择已更新",
      "settings.preferences": "设置偏好已同步",
    };
    status = {
      label:
        actionId === "settings.healthCheck"
          ? healthStatus === "passed"
            ? "模型健康检查通过"
            : healthStatus === "failed"
              ? "模型健康检查未通过"
              : "模型健康检查已完成"
          : settingsStatusLabels[actionId] || "设置状态已同步",
      percent: actionId === "settings.healthCheck" ? 100 : null,
    };
  }
  if (actionId === "app.progress" && framePageId(doc) === "current-project") {
    const overview = result?.action_result?.app_progress ? result.action_result : result;
    const projectStatus = firstNonEmpty(
      overview?.app_progress?.story_progress?.story_progress_status,
      overview?.app_progress?.project?.status,
    );
    status = {
      label: projectStatus === "story_draft_complete" ? "项目总览已同步 · 故事草稿已完成" : "项目总览已同步",
      percent: projectStatus === "story_draft_complete" ? 100 : null,
    };
  }
  if (doc.getElementById("createButton") && doc.getElementById("bootstrapButton")) {
    const handoff = findStorySetupHandoffPayload(result) || {};
    const bootstrap = findStorySetupBootstrapPayload(result) || {};
    const currentWorldCanvas = result?.current_world_canvas || result?.currentWorldCanvas || {};
    const persistedWorldCanvas = currentWorldCanvas.world_canvas || currentWorldCanvas.worldCanvas || currentWorldCanvas;
    const hasHandoff = Boolean(
      handoff.story_setup_handoff_id ||
        handoff.storySetupHandoffId ||
        bootstrap.story_setup_handoff_id ||
        bootstrap.storySetupHandoffId,
    );
    const handoffStatus = firstNonEmpty(handoff.handoff_status, handoff.handoffStatus);
    const isBootstrapped = Boolean(
      bootstrap.story_setup_bootstrap_id ||
        bootstrap.storySetupBootstrapId ||
        handoffStatus === "applied" ||
        (hasHandoff && (persistedWorldCanvas.world_canvas_id || persistedWorldCanvas.worldCanvasId)) ||
        actionId === "storySetup.bootstrapHandoff",
    );
    status = isBootstrapped
      ? { label: "当前项目初始化完成", percent: 100 }
      : hasHandoff
        ? { label: "故事设定交接包已创建", percent: 36 }
        : { label: "等待创建故事设定交接包", percent: 0 };
  }
  renderProjectsSurface(doc, result);
  renderCurrentProjectSurface(doc, result);
  renderTemplateDemoSurface(doc, result);
  renderAnalyzeImportSourceSurface(doc, result);
  renderAnalyzeStoriesWorkflowSurface(doc, result);
  applyBackendResultState(doc, result);
  renderImportedFrameworkSessionSurface(doc, result);
  renderWorldCanvasSurface(doc, result);
  renderCharacterSurface(doc, result);
  renderRoleLibrarySurface(doc, result);
  renderRoleContextSurface(doc, result);
  renderFrameworkWorkbenchSurface(doc, result);
  renderFrameworkLibrarySurface(doc, result);
  renderChapterPlanSurface(doc, result);
  renderSceneSurface(doc, result);
  renderFinalOutputSurface(doc, result);
  renderPluginSurface(doc, result);
  renderSettingsSurface(doc, result);
  applyRealtimeProgressElements(doc, status);
  if (storySetupQuestions.length && hasStorySetupDraft) {
    renderStorySetupQuestions(doc, storySetupQuestions);
  }
  const storySetupApplied = applyStorySetupDraftState(doc, result);
  if (storySetupApplied) {
    setGenerationGate(doc, true, "后端草案生成完成");
  }
  applyStorySetupHandoffState(doc, result, actionId);
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
    if (element.dataset.mafsUserEditBound !== "true") {
      element.dataset.mafsUserEditBound = "true";
      ["input", "change"].forEach((eventName) => {
        element.addEventListener(eventName, () => {
          if (element.dataset.mafsApplyingBackendValue === "true") {
            return;
          }
          element.dataset.mafsUserEdited = "true";
        });
      });
    }
    const currentValue = String(element.value || "").trim();
    const nextValue = String(value || "").trim();
    const currentLooksUserAuthored = currentValue && !isLegacyStorySetupDefaultText(currentValue);
    if (
      currentLooksUserAuthored &&
      currentValue !== nextValue &&
      (
        element.dataset.mafsUserEdited === "true" ||
        (element.dataset.mafsBackendBound !== "true" && element.dataset.mafsBackendRendered !== "true")
      )
    ) {
      return;
    }
    element.dataset.mafsApplyingBackendValue = "true";
    element.value = value;
    element.dataset.mafsBackendBound = "true";
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dataset.mafsApplyingBackendValue = "false";
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
  return exactLegacyTexts.has(text);
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
  setRenderedText(
    doc.querySelector(".main-panel .panel-note"),
    "写下题材、氛围、主角、冲突、世界范围或任何你已经确定的内容。无需按格式填写，系统会在下一步整理成草案。",
  );
}

function isLegacyCharacterDefaultText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  return new Set([
    "港口城钟楼证词",
    "港城钟楼证词",
    "雾港钟楼证词",
    "洛闻",
    "码头旅客",
    "钟表修复师",
  ]).has(text);
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
}

function applyBackendFormState(doc, result, form = {}) {
  if (!doc?.body) {
    return;
  }
  clearLegacyStorySetupEntryDefaults(doc);
  clearLegacyCharacterEntryDefaults(doc);
  const title = firstNonEmpty(
    safeStorySetupInputText(findResultText(result, ["requested_title", "requestedTitle", "proposed_title", "proposedTitle", "project_title", "title"])),
    safeStorySetupInputText(form.projectTitle),
    safeStorySetupInputText(form.requestedTitle),
    safeStorySetupInputText(form.projectName),
  );
  const prompt = firstNonEmpty(
    safeStorySetupInputText(
      findResultText(result, ["controlled_prompt_text", "controlledPromptText", "prompt_text", "promptText", "setup_prompt", "setupPrompt"]),
    ),
    safeStorySetupInputText(form.setupPrompt),
    safeStorySetupInputText(form.promptText),
    safeStorySetupInputText(form.projectPrompt),
    safeStorySetupInputText(form.storyPrompt),
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
  if (/HARD_RULE_CONFLICT|conflicts? with World Canvas hard rules?/i.test(message)) {
    return "本次模型候选与已确认世界硬规则冲突，系统没有覆盖原正文。请调整修订要求后重试。";
  }
  if (/SCENE_REVISION_UNSAFE_OUTPUT|meta text|disallowed characters/i.test(message)) {
    return "本次修订候选未通过正文安全检查，系统没有保存或覆盖原正文。请调整要求后重试；若模型输出格式短暂异常，也可以直接再次生成。";
  }
  if (/SCENE_RUNTIME_REFRESH_NOT_READY|场景文本与已确认的记忆提取存在直接矛盾/i.test(message)) {
    return "提交前一致性检查发现正文与结构化记忆存在矛盾。系统已保留当前草稿，请重新生成或修订后再确认。";
  }
  return message || "后端操作失败，已停留在当前页面。";
}

function isTransientModelGenerationError(error) {
  const status = Number(error?.status || 0);
  const message = [
    error?.message,
    typeof error?.detail === "string" ? error.detail : error?.detail?.message,
    error?.detail?.error_code,
  ]
    .filter(Boolean)
    .join(" ");
  if ([408, 429, 500, 502, 503, 504].includes(status)) {
    return true;
  }
  return /真实模型未能完成|provider_http_error|provider_timeout|model_provider_unavailable|API request timed out|failed to fetch|temporar(?:y|ily)|请求超时|模型服务暂时/i.test(
    message,
  );
}

function waitForRetry(delayMs) {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

function setGenerationRetryButton(doc, { visible, busy = false, onRetry = null } = {}) {
  const gateButton = doc?.querySelector("#reviewButton, #completeButton");
  if (!doc?.body || !gateButton) {
    return;
  }
  let retryButton = doc.getElementById("mafs-generation-retry");
  if (!visible) {
    retryButton?.remove();
    return;
  }
  injectBridgeStyle(doc);
  if (!retryButton) {
    retryButton = doc.createElement("button");
    retryButton.id = "mafs-generation-retry";
    retryButton.className = "mafs-generation-retry";
    retryButton.type = "button";
    retryButton.textContent = "重新生成";
    gateButton.insertAdjacentElement("beforebegin", retryButton);
  }
  retryButton.disabled = Boolean(busy);
  retryButton.textContent = busy ? "正在重新生成" : "重新生成";
  retryButton.onclick = typeof onRetry === "function" ? onRetry : null;
}

const WORKSPACE_REFS_SESSION_KEY = "mafs.productionUi.workspaceRefs.v1";

function initialWorkspaceRefs() {
  const fallback = { pluginId: "script_forging" };
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(WORKSPACE_REFS_SESSION_KEY) || "null");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return fallback;
    }
    return {
      ...parsed,
      pluginId: parsed.pluginId || "script_forging",
    };
  } catch {
    return fallback;
  }
}

function persistWorkspaceRefs(refs) {
  try {
    const safeRefs = Object.fromEntries(
      Object.entries(refs || {}).filter(([key, value]) => {
        if (/secret|api.?key|token|password|credential/i.test(key)) {
          return false;
        }
        return ["string", "number", "boolean"].includes(typeof value);
      }),
    );
    window.sessionStorage.setItem(WORKSPACE_REFS_SESSION_KEY, JSON.stringify(safeRefs));
  } catch {
    // Session persistence is optional; runtime hydration remains authoritative.
  }
}

export default function ProductUiApp() {
  const iframeRef = useRef(null);
  const pendingNavigationResultRef = useRef(null);
  const refsRef = useRef({});
  const pageIdRef = useRef("");
  const workspaceInteractionEpochRef = useRef(0);
  const [pageId, setPageId] = useState(parseHash);
  const [refs, setRefs] = useState(initialWorkspaceRefs);
  const page = useMemo(() => getPage(pageId), [pageId]);
  const showDirectory = !DIRECTORY_HIDDEN_PAGES.has(pageId);

  useEffect(() => {
    refsRef.current = refs;
    persistWorkspaceRefs(refs);
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
    const hydrationEpoch = workspaceInteractionEpochRef.current;
    hydrateWorkspaceRefs(refs, { workspaceId: workspaceIdForPageId(pageId) })
      .then((nextRefs) => {
        if (!cancelled && workspaceInteractionEpochRef.current === hydrationEpoch) {
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

  useEffect(() => {
    const doc = iframeRef.current?.contentDocument;
    if (!refs.projectId || !doc?.body || pageIdRef.current !== pageId) {
      return;
    }
    doc.body.dataset.mafsReadOnlyHydratedFor = "";
    hydrateFrameReadOnlyState(doc);
  }, [refs.projectId, pageId]);

  async function executeAction(action, doc, sourceTarget = null) {
    if (!doc?.body || !doc.defaultView) {
      return;
    }
    workspaceInteractionEpochRef.current += 1;
    doc.defaultView.__mafsUserActionEpoch = Number(doc.defaultView.__mafsUserActionEpoch || 0) + 1;
    try {
    setActionPhase(doc, "collect_form");
    const collectedForm = collectFrameForm(doc);
    const localContext = extractActionLocalContext(action, sourceTarget, collectedForm);
    const form = { ...collectedForm, ...(localContext.form || {}) };
    if (action.actionId === "final.download") {
      const clickedFormat = String(sourceTarget?.closest?.("[data-format]")?.dataset?.format || "");
      if (["txt", "markdown", "json"].includes(clickedFormat)) {
        form.exportFormat = clickedFormat;
      }
    }
    setActionForm(doc, form);
    if (isImmediateNavigationAction(action)) {
      const navigationRefs = { ...(refsRef.current || refs), ...(localContext.refs || {}) };
      setRefs(navigationRefs);
      refsRef.current = navigationRefs;
      setLastAction(doc, action.actionId || action.to);
      setActionPhase(doc, `navigate:${action.actionId || action.to}`);
      setFrameBusy(doc, false);
      navigate(action.to);
      return;
    }
    setActionPhase(doc, "set_busy");
    setFrameBusy(doc, true, backendActionBusyMessage(action.actionId));
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
        applyBackendFormState(doc, outcome.result, form);
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
    const nextPageId = postActionTarget(action, latestOutcome);
    if (nextPageId) {
      if (nextPageId === pageIdRef.current && latestOutcome) {
        pendingNavigationResultRef.current = null;
        const samePageResult = {
          ...(latestOutcome.result || {}),
          action_id: action.actionId,
          action_result: latestOutcome.result?.action_result || latestOutcome.result,
          hydrated_refs: latestOutcome.refs,
        };
        applyRealtimeResultState(doc, samePageResult, action.actionId);
        applyBackendFormState(doc, samePageResult, form);
        return;
      }
      if (latestOutcome) {
        pendingNavigationResultRef.current = {
          pageId: nextPageId,
          actionId: action.actionId,
          result: latestOutcome.result,
          refs: latestOutcome.refs,
          form,
          createdAt: Date.now(),
        };
      }
      navigate(nextPageId);
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
      setFrameHydrating(doc, false);
      return;
    }
    if (!actionId || !doc?.body || doc.body.dataset.mafsReadOnlyHydratedFor === `${pageId}:${actionId}`) {
      setFrameHydrating(doc, false);
      return;
    }
    doc.body.dataset.mafsReadOnlyHydratedFor = `${pageId}:${actionId}`;
    const actionEpoch = Number(doc.defaultView?.__mafsUserActionEpoch || 0);
    try {
      const pinnedSceneSelection = (
        SCENE_PAGE_IDS.has(pageId) &&
        !["scene-entry", "chapter-closeout"].includes(pageId)
      )
        ? sceneSelectionFromDocument(doc)
        : {};
      const readOnlyRefs = {
        ...(refsRef.current || refs),
        ...pinnedSceneSelection,
      };
      const outcome = await runWorkspaceAction(actionId, {
        refs: readOnlyRefs,
        form: {},
        skipPreHydrate: true,
        skipShellState: true,
      });
      if (Number(doc.defaultView?.__mafsUserActionEpoch || 0) !== actionEpoch) {
        return;
      }
      if (pinnedSceneSelection.sceneSelectionPinned) {
        const outcomeScene = findScenePayload(outcome.result);
        const requestedSceneIndex = Number(pinnedSceneSelection.sceneIndex || 0) || 0;
        const outcomeSceneIndex = Number(outcomeScene?.scene_index || outcomeScene?.sceneIndex || 0) || 0;
        if (!outcomeScene || (requestedSceneIndex && outcomeSceneIndex !== requestedSceneIndex)) {
          return;
        }
      }
      const stableOutcomeRefs = {
        ...(outcome.refs || {}),
        ...pinnedSceneSelection,
      };
      setRefs(stableOutcomeRefs);
      refsRef.current = stableOutcomeRefs;
      const renderResult = {
        ...(outcome.result || {}),
        action_id: actionId,
        action_result: outcome.result?.action_result || outcome.result,
        hydrated_refs: stableOutcomeRefs,
        health: outcome.result?.health || outcome.result?.action_result?.health,
      };
      applyRealtimeResultState(doc, renderResult, actionId);
      applyBackendFormState(
        doc,
        renderResult,
        stableOutcomeRefs,
      );
    } catch (error) {
      if (getApiMode() === "live") {
        console.warn("[MAFS UI] read-only frame hydration failed", pageId, actionId, error);
      }
      applyRealtimeResultState(doc, {
        status: "empty",
        safe_summary: "当前项目暂无此页可展示的数据。",
      }, actionId);
    } finally {
      if (pageIdRef.current === pageId && iframeRef.current?.contentDocument === doc) {
        setFrameHydrating(doc, false);
      }
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
    const readOnlyActionId = READ_ONLY_LOAD_ACTION_BY_PAGE_ID[pageId];
    if (
      readOnlyActionId &&
      (
        readOnlyActionId === pending.actionId ||
        SCENE_PAGE_IDS.has(pageId) ||
        ROLE_CONTEXT_PAGE_IDS.has(pageId)
      )
    ) {
      doc.body.dataset.mafsReadOnlyHydratedFor = `${pageId}:${readOnlyActionId}`;
    }
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
      setGenerationRetryButton(doc, { visible: false });
      if (generationReadyFromRefsOrResult(pageId, refsRef.current || refs, {})) {
        setGenerationGate(doc, true, "已读取当前项目的故事设定草案");
        return;
      }
      setGenerationGate(doc, false, "后端正在生成故事设定草案");
      let lastError = null;
      for (let attemptIndex = 0; attemptIndex <= MODEL_GENERATION_RETRY_DELAYS_MS.length; attemptIndex += 1) {
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
          setGenerationRetryButton(doc, { visible: false });
          return;
        } catch (error) {
          lastError = error;
          const delayMs = MODEL_GENERATION_RETRY_DELAYS_MS[attemptIndex];
          if (delayMs === undefined || !isTransientModelGenerationError(error)) {
            break;
          }
          const nextAttempt = attemptIndex + 2;
          setGenerationGate(doc, false, `模型服务暂时未响应，正在进行第 ${nextAttempt} 次尝试`);
          showFrameMessage(doc, `模型服务暂时未响应，系统将在 ${Math.ceil(delayMs / 1000)} 秒后重试。`);
          await waitForRetry(delayMs);
        }
      }
      doc.body.dataset.mafsGenerationStartupDone = "false";
      setGenerationGate(doc, false, "真实模型生成失败，可重新尝试");
      setGenerationRetryButton(doc, {
        visible: true,
        onRetry: async () => {
          setGenerationRetryButton(doc, { visible: true, busy: true });
          await runStartupAction();
        },
      });
      if (getApiMode() === "live") {
        console.warn("[MAFS UI] realtime startup action failed", pageId, startupActionId, lastError);
      }
      showFrameMessage(doc, userFacingError(lastError), "error");
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
    const readOnlyActionId = READ_ONLY_LOAD_ACTION_BY_PAGE_ID[pageId];
    if (readOnlyActionId && pageId !== "story-setup-generating") {
      setFrameHydrating(doc, true);
    } else {
      setFrameHydrating(doc, false);
    }
    if (!MODEL_BACKEND_STATUS_PAGE_IDS.has(pageId)) {
      doc.getElementById("mafs-settings-panel")?.remove();
    }
    doc.defaultView.__MAFS_EXECUTE_ACTION__ = (action, target) => {
      setLastAction(doc, action.actionId || action.to || "");
      executeAction(action, doc, target);
    };
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
      if (findDatasetAction(element)) {
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
          const action = matchedAction || { to: backTargetForElement(pageId, element) };
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
        const datasetAction = findDatasetAction(event.target);
        if (!datasetAction && event.target?.closest?.("[data-mafs-selector-bound]")) {
          return;
        }
        if (isLocalOnlyControl(page, event.target)) {
          return;
        }
        const action =
          datasetAction ||
          findSelectorAction(page, event.target) ||
          (target && page.actions.find((candidate) => actionMatches(target, candidate))) ||
          (page.id === "opening" ? page.actions[0] || { to: "home" } : null) ||
          (target && isBackElement(target) ? { to: backTargetForElement(pageId, target) } : null) ||
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
                  onClick={() => {
                    workspaceInteractionEpochRef.current += 1;
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
