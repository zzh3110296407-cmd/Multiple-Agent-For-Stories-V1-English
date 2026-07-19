import * as projectApi from "../../api/projectApi.js";
import { getAppProgress } from "../../api/appProgressApi.js";

const DEFAULT_API_MODE = import.meta.env.VITE_MAFS_API_MODE || "live";

function runtimeApiMode() {
  const search = globalThis.location?.search || "";
  const runtimeMode = new URLSearchParams(search).get("apiMode");
  return runtimeMode || DEFAULT_API_MODE;
}

function isLiveMode() {
  return runtimeApiMode() === "live";
}

function pickId(value, keys) {
  if (!value || typeof value !== "object") {
    return "";
  }
  for (const key of keys) {
    if (value[key]) {
      return value[key];
    }
  }
  for (const nestedKey of ["data", "result", "payload", "item", "record"]) {
    const nested = value[nestedKey];
    if (nested && typeof nested === "object") {
      const nestedId = pickId(nested, keys);
      if (nestedId) {
        return nestedId;
      }
    }
  }
  return "";
}

function firstItem(value, keys) {
  for (const key of keys) {
    const item = value?.[key];
    if (Array.isArray(item) && item.length) {
      return item[0];
    }
  }
  return null;
}

function firstIdFromList(value, keys, idKeys) {
  for (const key of keys) {
    const items = value?.[key];
    if (!Array.isArray(items) || !items.length) {
      continue;
    }
    for (const item of items) {
      if (typeof item === "string" && item) {
        return item;
      }
      const itemId = pickId(item, idKeys);
      if (itemId) {
        return itemId;
      }
    }
  }
  return "";
}

function pickFinalReadinessGateId(value) {
  return (
    pickId(value, ["readiness_gate_id", "readinessGateId", "gate_id", "id"]) ||
    pickId(value?.readiness_gate, ["readiness_gate_id", "readinessGateId", "gate_id", "id"]) ||
    pickId(value?.readinessGate, ["readiness_gate_id", "readinessGateId", "gate_id", "id"]) ||
    ""
  );
}

function compactObject(value) {
  return Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined && item !== null && item !== ""));
}

function sceneRecordFromCurrentScenePayload(currentScene) {
  if (!currentScene || typeof currentScene !== "object") {
    return {};
  }
  const record =
    currentScene.scene ||
    currentScene.current_scene ||
    currentScene.currentScene ||
    currentScene;
  return record && typeof record === "object" ? record : {};
}

function sceneRecordFromSurface(surface) {
  return sceneRecordFromCurrentScenePayload(surface?.current_scene || surface?.currentScene || surface);
}

function sameChapterScene(record, chapterId, sceneIndex = null) {
  if (!record || typeof record !== "object") {
    return false;
  }
  const recordSceneId = String(record.scene_id || record.sceneId || "").trim();
  const recordSceneIndex = Number(record.scene_index || record.sceneIndex || 0) || 0;
  if (!recordSceneId && recordSceneIndex <= 0) {
    return false;
  }
  const recordChapterId = String(record.chapter_id || record.chapterId || "").trim();
  const expectedChapterId = String(chapterId || "").trim();
  if (expectedChapterId && recordChapterId && recordChapterId !== expectedChapterId) {
    return false;
  }
  const expectedSceneIndex = Number(sceneIndex || 0) || 0;
  if (expectedSceneIndex > 0) {
    if (recordSceneIndex > 0 && recordSceneIndex !== expectedSceneIndex) {
      return false;
    }
  }
  return true;
}

function firstNonEmptyText(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function isDefaultProjectTitleText(value) {
  const normalized = String(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
  return new Set([
    "未命名故事",
    "未命名故事项目",
    "untitled story",
    "untitled story project",
  ]).has(normalized);
}

function firstUserProjectTitle(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text && !isDefaultProjectTitleText(text)) {
      return text;
    }
  }
  return "";
}

function chineseCountToInt(value) {
  const normalized = String(value || "").trim();
  if (/^\d+$/.test(normalized)) {
    return Number(normalized);
  }
  const digitMap = {
    一: 1,
    二: 2,
    两: 2,
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

function inferChapterCountFromText(text) {
  const source = String(text || "");
  const match = source.match(/([0-9一二两三四五六七八九十]{1,4})\s*章/);
  return match ? chineseCountToInt(match[1]) : 0;
}

function isInternalReferenceText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  const normalized = text.toLowerCase();
  if (/^story_setup_(prompt|intake|draft_bundle|handoff|decision|question)([:_\w-]*)?$/.test(normalized)) {
    return true;
  }
  if (/^(large_scope_suggestion|world_scope_to_confirm|tone_to_confirm|suspense|draft_suggestion|controlled_prompt)$/.test(normalized)) {
    return true;
  }
  return /^(story setup|draft initialized from story setup|project story premise is ready)\b/i.test(text);
}

function firstUserVisibleText(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text && !isInternalReferenceText(text)) {
      return text;
    }
  }
  return "";
}

function projectStoryPremiseText(response) {
  const premise = response?.premise || response?.project_story_premise || response?.projectStoryPremise || response || {};
  return firstUserVisibleText(
    premise.user_story_premise,
    premise.userStoryPremise,
    premise.safe_user_story_summary,
    premise.safeUserStorySummary,
    response?.safe_summary,
    response?.safeSummary,
  );
}

function mergeClientFormRefs(refs = {}, form = {}) {
  const promptText = firstNonEmptyText(form.setupPrompt, form.promptText, form.projectPrompt, form.storyPrompt);
  const projectTitle = firstUserProjectTitle(form.projectTitle, form.requestedTitle, form.projectName);
  const roleTier = normalizeRoleTier(form.roleTier, refs.roleTier);
  return compactObject({
    ...refs,
    setupPrompt: promptText || refs.setupPrompt,
    promptText: promptText || refs.promptText,
    projectPrompt: promptText || refs.projectPrompt,
    projectTitle: projectTitle || refs.projectTitle,
    requestedTitle: projectTitle || refs.requestedTitle,
    roleTier: roleTier || refs.roleTier,
    analyzeCandidateId: form.analyzeCandidateId || refs.analyzeCandidateId,
    importedEditSessionId: form.importedEditSessionId || refs.importedEditSessionId,
    importedActivationPlanId: form.importedActivationPlanId || refs.importedActivationPlanId,
  });
}

function requireRef(refs, key, label) {
  const value = refs[key];
  if (!value) {
    const error = new Error(`缺少 ${label}，请先完成上一阶段或从后端状态恢复。`);
    error.code = "MISSING_REF";
    throw error;
  }
  return value;
}

function isPlaceholderChapterId(value) {
  return /^chapter_\d{3}$/i.test(String(value || "").trim());
}

function preferRuntimeChapterId(candidate, fallback = "") {
  const value = String(candidate || "").trim();
  if (value && !isPlaceholderChapterId(value)) {
    return value;
  }
  const fallbackValue = String(fallback || "").trim();
  return fallbackValue && !isPlaceholderChapterId(fallbackValue) ? fallbackValue : "";
}

function updateRefsFromResult(refs, result) {
  const nestedActionResult = result?.action_result || result?.actionResult || {};
  const activeProject = result?.active_project_selection || result?.activeProjectSelection || {};
  const openedProject =
    result?.opened_project ||
    result?.openedProject ||
    nestedActionResult?.opened_project ||
    nestedActionResult?.openedProject ||
    {};
  const projectDataProject =
    result?.project_data?.project ||
    result?.projectData?.project ||
    nestedActionResult?.project_data?.project ||
    nestedActionResult?.projectData?.project ||
    {};
  const firstProject = firstItem(result, ["projects", "items", "records"]) || {};
  const firstRole = firstItem(result, ["roles", "characters", "items"]) || {};
  const questionCollection =
    result?.questions ||
    result?.story_setup_questions ||
    result?.storySetupQuestions ||
    nestedActionResult?.questions ||
    nestedActionResult?.story_setup_questions ||
    nestedActionResult?.storySetupQuestions ||
    {};
  const firstQuestion =
    firstItem(result, ["questions", "blocking_questions", "items"]) ||
    firstItem(questionCollection, ["questions", "blocking_questions", "items"]) ||
    {};
  const answeredStorySetupQuestion =
    result?.answer ||
    result?.answered_question ||
    result?.answeredQuestion ||
    result?.story_setup_question ||
    result?.storySetupQuestion ||
    {};
  const firstPluginRun = firstItem(result, ["plugin_runs", "runs", "items"]) || {};
  const firstCheckpoint = firstItem(result, ["checkpoints", "pending_checkpoints", "items"]) || {};
  const firstProfile =
    firstItem(result, ["profiles", "model_profiles", "items"]) ||
    firstItem(result?.profiles, ["profiles", "model_profiles", "items"]) ||
    firstItem(result?.workbench, ["profiles", "model_profiles", "items"]) ||
    {};
  const firstTemplate = firstItem(result, ["templates", "project_templates", "projectTemplates", "items"]) || {};
  const firstDemoSeed = firstItem(result, ["demo_seed_profiles", "demoSeedProfiles", "demo_seeds", "demoSeeds", "items"]) || {};
  const firstAnalyzeImport = firstItem(result, ["imports", "analyze_stories_imports", "analyzeStoriesImports", "items"]) || {};
  const firstAnalyzeCandidate = firstItem(result, ["framework_candidates", "frameworkCandidates", "candidates", "items"]) || {};
  const currentAnalyzeCandidate = result?.candidate || result?.framework_candidate || result?.frameworkCandidate || {};
  const importedEditSession =
    result?.edit_session ||
    result?.editSession ||
    nestedActionResult?.edit_session ||
    nestedActionResult?.editSession ||
    result?.selected_imported_edit_session?.edit_session ||
    result?.selectedImportedEditSession?.editSession ||
    {};
  const importedActivationPlan =
    result?.activation_plan ||
    result?.activationPlan ||
    nestedActionResult?.activation_plan ||
    nestedActionResult?.activationPlan ||
    result?.selected_imported_edit_session?.activation_plan ||
    result?.selectedImportedEditSession?.activationPlan ||
    {};
  const currentSceneRevision =
    result?.scene_revision ||
    result?.sceneRevision ||
    nestedActionResult?.scene_revision ||
    nestedActionResult?.sceneRevision ||
    result?.modification_choice ||
    result?.modificationChoice ||
    {};
  const currentSceneRevisionCandidate =
    currentSceneRevision?.candidate ||
    currentSceneRevision?.current_candidate ||
    currentSceneRevision?.currentCandidate ||
    result?.candidate ||
    {};
  const firstExportRun = firstItem(result, ["export_runs", "exportRuns", "items", "records"]) || {};
  const currentCreationRequest = result?.creation_request || result?.creationRequest || result?.project_creation_request || {};
  const currentCreationDraft = result?.creation_draft || result?.creationDraft || result?.project_creation_draft || {};
  const currentCreationDecision = result?.creation_decision || result?.creationDecision || result?.project_creation_decision || {};
  const currentCharacterDraft =
    result?.character_draft?.draft ||
    result?.characterDraft?.draft ||
    nestedActionResult?.character_draft?.draft ||
    nestedActionResult?.characterDraft?.draft ||
    {};
  const currentCharacter = currentCharacterDraft?.character || currentCharacterDraft?.role || {};
  const generatedRoleDraft =
    result?.draft ||
    result?.generated_role_draft ||
    result?.generatedRoleDraft ||
    result?.role_draft ||
    result?.roleDraft ||
    {};
  const generatedRoleDraftPayload = generatedRoleDraft?.draft || generatedRoleDraft;
  const participantSelection = result?.participant_selection || result?.participantSelection || result?.selection || {};
  const firstSceneParticipantSelection =
    firstItem(result, ["participant_selections", "selections", "items"]) ||
    participantSelection ||
    {};
  const firstSceneParticipantCandidate =
    firstItem(result, ["creation_candidates", "candidates", "items"]) ||
    firstItem(participantSelection, ["creation_candidates", "candidates", "items"]) ||
    {};
  const sceneParticipantCandidateIdKeys = [
    "creation_candidate_id",
    "creationCandidateId",
    "candidate_id",
    "candidateId",
    "scene_participant_candidate_id",
    "id",
  ];
  const readinessGate =
    result?.readiness_gate ||
    result?.readinessGate ||
    result?.gate ||
    nestedActionResult?.readiness_gate ||
    nestedActionResult?.readinessGate ||
    nestedActionResult?.gate ||
    {};
  const exportRun = result?.export_run || result?.exportRun || nestedActionResult?.export_run || nestedActionResult?.exportRun || {};
  const snapshot =
    result?.snapshot ||
    result?.final_snapshot ||
    result?.finalSnapshot ||
    nestedActionResult?.snapshot ||
    nestedActionResult?.final_snapshot ||
    nestedActionResult?.finalSnapshot ||
    {};
  const activeModelSelection =
    result?.active_selection?.active_selection ||
    result?.activeSelection?.activeSelection ||
    result?.active_selection ||
    result?.activeSelection ||
    result?.model_active_selection ||
    {};
  const nextChapterPreparation = result?.preparation || result?.next_chapter_preparation || result?.nextChapterPreparation || {};
  const chapterFramework = result?.chapter_framework || result?.chapterFramework || {};
  const currentScene =
    result?.selected_scene ||
    result?.selectedScene ||
    nestedActionResult?.selected_scene ||
    nestedActionResult?.selectedScene ||
    result?.current_scene ||
    result?.currentScene ||
    result?.scene ||
    {};
  const currentSceneRecord =
    currentScene?.scene ||
    currentScene?.current_scene ||
    currentScene?.currentScene ||
    currentScene;
  const topLevelSceneProgress =
    result?.scene_progress ||
    result?.sceneProgress ||
    nestedActionResult?.scene_progress ||
    nestedActionResult?.sceneProgress ||
    {};
  const currentSceneProgress = currentScene?.progress || currentScene?.scene_progress || currentScene?.sceneProgress || topLevelSceneProgress || {};
  const storyProgress =
    result?.story_progress ||
    result?.storyProgress ||
    result?.progress ||
    nestedActionResult?.story_progress ||
    nestedActionResult?.storyProgress ||
    {};
  const storySetupPrompt =
    result?.story_setup_prompt ||
    result?.storySetupPrompt ||
    nestedActionResult?.story_setup_prompt ||
    nestedActionResult?.storySetupPrompt ||
    {};
  const storySetupDraftBundle =
    result?.story_setup_draft_bundle ||
    result?.storySetupDraftBundle ||
    result?.draft_bundle ||
    result?.draftBundle ||
    nestedActionResult?.story_setup_draft_bundle ||
    nestedActionResult?.storySetupDraftBundle ||
    nestedActionResult?.draft_bundle ||
    nestedActionResult?.draftBundle ||
    nestedActionResult?.draft_bundle?.draft_bundle ||
    {};
  const storySetupIntake =
    result?.story_setup_intake ||
    result?.storySetupIntake ||
    nestedActionResult?.story_setup_intake ||
    nestedActionResult?.storySetupIntake ||
    nestedActionResult?.intake ||
    {};
  const storySetupDecision =
    result?.story_setup_decision ||
    result?.storySetupDecision ||
    nestedActionResult?.story_setup_decision ||
    nestedActionResult?.storySetupDecision ||
    nestedActionResult?.decision ||
    {};
  const storySetupHandoff =
    result?.story_setup_handoff ||
    result?.storySetupHandoff ||
    nestedActionResult?.story_setup_handoff ||
    nestedActionResult?.storySetupHandoff ||
    nestedActionResult?.handoff ||
    {};
  const incomingStorySetupPromptId =
    pickId(result, ["story_setup_prompt_id", "storySetupPromptId", "prompt_id"]) ||
    pickId(nestedActionResult, ["story_setup_prompt_id", "storySetupPromptId", "prompt_id"]) ||
    pickId(storySetupPrompt, ["story_setup_prompt_id", "storySetupPromptId", "prompt_id"]) ||
    pickId(storySetupDraftBundle, ["story_setup_prompt_id", "storySetupPromptId", "prompt_id"]);
  const nextStorySetupPromptId = incomingStorySetupPromptId || refs.storySetupPromptId;
  const storySetupPromptChanged = Boolean(
    incomingStorySetupPromptId && refs.storySetupPromptId && incomingStorySetupPromptId !== refs.storySetupPromptId,
  );
  const resultStorySetupDraftBundleId =
    pickId(result, ["story_setup_draft_bundle_id", "storySetupDraftBundleId", "draft_bundle_id"]) ||
    pickId(nestedActionResult, ["story_setup_draft_bundle_id", "storySetupDraftBundleId", "draft_bundle_id"]) ||
    pickId(storySetupDraftBundle, ["story_setup_draft_bundle_id", "storySetupDraftBundleId", "draft_bundle_id", "id"]);
  const chapterIndex = Number(
    result?.chapter_index ||
    result?.chapterIndex ||
    storyProgress?.current_chapter_index ||
    storyProgress?.currentChapterIndex ||
    currentSceneRecord?.chapter_index ||
    currentSceneRecord?.chapterIndex ||
    currentSceneProgress?.chapter_index ||
    currentSceneProgress?.chapterIndex ||
    chapterFramework?.chapter_index ||
    chapterFramework?.chapterIndex ||
    refs.chapterIndex ||
    0,
  );
  const incomingChapterId =
    pickId(storyProgress, ["current_chapter_id", "currentChapterId", "chapter_id", "chapterId", "id"]) ||
    pickId(currentSceneProgress, ["chapter_id", "chapterId", "id"]) ||
    pickId(currentSceneRecord, ["chapter_id", "chapterId"]) ||
    pickId(result, ["chapter_id", "chapterId", "id"]) ||
    pickId(chapterFramework, ["chapter_id", "chapterId", "id"]);
  const resolvedChapterId = preferRuntimeChapterId(incomingChapterId, refs.chapterId);
  const chapterChanged = Boolean(resolvedChapterId && refs.chapterId && resolvedChapterId !== refs.chapterId);
  const incomingSceneId =
    pickId(result, ["scene_id", "sceneId", "id"]) ||
    pickId(currentSceneRecord, ["scene_id", "sceneId", "id"]);
  const progressSceneCursor = Number(
    refs.sceneSelectionPinned ? 0 : (
      currentSceneProgress?.next_scene_index ||
      currentSceneProgress?.nextSceneIndex ||
      0
    ),
  );
  const incomingSceneIndex = Number(
    result?.scene_index ||
      result?.sceneIndex ||
      currentSceneRecord?.scene_index ||
      currentSceneRecord?.sceneIndex ||
      progressSceneCursor ||
      0,
  );

  return {
    ...refs,
    projectId:
      pickId(result, ["project_id", "projectId"]) ||
      pickId(activeProject, ["project_id", "projectId"]) ||
      refs.projectId,
    selectedProjectId:
      pickId(result, ["project_id", "projectId"]) ||
      pickId(activeProject, ["project_id", "projectId"]) ||
      refs.selectedProjectId ||
      pickId(firstProject, ["project_id", "projectId"]),
    projectTitle:
      firstUserProjectTitle(
        openedProject?.title,
        openedProject?.requested_title,
        openedProject?.requestedTitle,
        projectDataProject?.title,
        projectDataProject?.requested_title,
        projectDataProject?.requestedTitle,
        result?.requested_title,
        result?.requestedTitle,
        currentCreationRequest?.requested_title,
        currentCreationRequest?.requestedTitle,
        currentCreationDraft?.proposed_title,
        currentCreationDraft?.proposedTitle,
      ) || refs.projectTitle,
    requestedTitle:
      firstUserProjectTitle(
        openedProject?.requested_title,
        openedProject?.requestedTitle,
        openedProject?.title,
        projectDataProject?.requested_title,
        projectDataProject?.requestedTitle,
        projectDataProject?.title,
        result?.requested_title,
        result?.requestedTitle,
        currentCreationRequest?.requested_title,
        currentCreationRequest?.requestedTitle,
        currentCreationDraft?.proposed_title,
        currentCreationDraft?.proposedTitle,
      ) || refs.requestedTitle,
    setupPrompt:
      firstNonEmptyText(result?.controlled_prompt_text, result?.controlledPromptText) || refs.setupPrompt,
    promptText:
      firstNonEmptyText(result?.controlled_prompt_text, result?.controlledPromptText) || refs.promptText,
    projectPrompt:
      firstNonEmptyText(result?.controlled_prompt_text, result?.controlledPromptText) || refs.projectPrompt,
    creationRequestId:
      pickId(result, ["creation_request_id", "creationRequestId", "request_id", "id"]) ||
      pickId(currentCreationRequest, ["creation_request_id", "creationRequestId", "request_id", "id"]) ||
      refs.creationRequestId,
    creationDraftId:
      pickId(result, ["creation_draft_id", "creationDraftId", "draft_id", "id"]) ||
      pickId(currentCreationDraft, ["creation_draft_id", "creationDraftId", "draft_id", "id"]) ||
      refs.creationDraftId,
    creationDecisionId:
      pickId(result, ["creation_decision_id", "creationDecisionId", "decision_id", "id"]) ||
      pickId(currentCreationDecision, ["creation_decision_id", "creationDecisionId", "decision_id", "id"]) ||
      refs.creationDecisionId,
    templateInstantiationRequestId:
      pickId(result, ["template_instantiation_request_id", "templateInstantiationRequestId", "request_id", "id"]) ||
      refs.templateInstantiationRequestId,
    demoSeedRunId: pickId(result, ["demo_seed_run_id", "demoSeedRunId", "run_id", "id"]) || refs.demoSeedRunId,
    templateId:
      pickId(result, ["template_id", "templateId"]) ||
      pickId(currentCreationRequest, ["template_id", "templateId"]) ||
      pickId(firstTemplate, ["template_id", "templateId", "id"]) ||
      refs.templateId,
    demoSeedId:
      pickId(result, ["demo_seed_id", "demoSeedId"]) ||
      pickId(currentCreationRequest, ["demo_seed_id", "demoSeedId"]) ||
      pickId(firstDemoSeed, ["demo_seed_id", "demoSeedId", "id"]) ||
      refs.demoSeedId,
    frameworkCompositionId:
      pickId(result, ["framework_composition_id", "composition_id", "compositionId", "id"]) || refs.frameworkCompositionId,
    analyzeImportId:
      pickId(result, ["import_id", "importId", "analyze_stories_import_id", "id"]) ||
      pickId(currentCreationRequest, ["analyze_stories_import_ref", "analyzeStoriesImportRef"]) ||
      pickId(firstAnalyzeImport, ["import_id", "importId", "analyze_stories_import_id", "id"]) ||
      refs.analyzeImportId,
    analyzeBundleId: pickId(result, ["bundle_manifest_id", "bundleManifestId", "bundle_id", "id"]) || refs.analyzeBundleId,
    analyzeCandidateId:
      pickId(result, ["candidate_id", "candidateId", "id"]) ||
      pickId(currentAnalyzeCandidate, ["candidate_id", "candidateId", "framework_candidate_id", "frameworkCandidateId", "id"]) ||
      pickId(importedEditSession, ["candidate_id", "candidateId"]) ||
      pickId(firstAnalyzeCandidate, ["candidate_id", "candidateId", "framework_candidate_id", "id"]) ||
      refs.analyzeCandidateId,
    importedEditSessionId:
      pickId(result, ["edit_session_id", "editSessionId"]) ||
      pickId(importedEditSession, ["edit_session_id", "editSessionId"]) ||
      refs.importedEditSessionId,
    importedActivationPlanId:
      pickId(result, ["activation_plan_id", "activationPlanId", "plan_id"]) ||
      pickId(importedActivationPlan, ["activation_plan_id", "activationPlanId", "plan_id", "planId"]) ||
      refs.importedActivationPlanId,
    storySetupPromptId: nextStorySetupPromptId,
    storySetupIntakeId:
      pickId(result, ["story_setup_intake_id", "storySetupIntakeId", "intake_id", "id"]) ||
      pickId(nestedActionResult, ["story_setup_intake_id", "storySetupIntakeId", "intake_id", "id"]) ||
      pickId(storySetupIntake, ["story_setup_intake_id", "storySetupIntakeId", "intake_id", "id"]) ||
      pickId(storySetupDraftBundle, ["story_setup_intake_id", "storySetupIntakeId", "intake_id"]) ||
      (storySetupPromptChanged ? "" : refs.storySetupIntakeId),
    storySetupDraftBundleId: resultStorySetupDraftBundleId || (storySetupPromptChanged ? "" : refs.storySetupDraftBundleId),
    storySetupQuestionId:
      pickId(answeredStorySetupQuestion, ["question_id", "questionId", "story_setup_question_id", "storySetupQuestionId", "id"]) ||
      pickId(result, ["question_id", "questionId", "id"]) ||
      pickId(nestedActionResult, ["question_id", "questionId", "story_setup_question_id", "storySetupQuestionId", "id"]) ||
      pickId(firstQuestion, ["question_id", "questionId", "story_setup_question_id", "id"]) ||
      (storySetupPromptChanged ? "" : refs.storySetupQuestionId),
    storySetupDecisionId:
      pickId(result, ["story_setup_decision_id", "storySetupDecisionId", "decision_id", "id"]) ||
      pickId(nestedActionResult, ["story_setup_decision_id", "storySetupDecisionId", "decision_id", "id"]) ||
      pickId(storySetupDecision, ["story_setup_decision_id", "storySetupDecisionId", "decision_id", "id"]) ||
      (storySetupPromptChanged ? "" : refs.storySetupDecisionId),
    storySetupHandoffId:
      pickId(result, ["story_setup_handoff_id", "storySetupHandoffId", "handoff_id", "id"]) ||
      pickId(nestedActionResult, ["story_setup_handoff_id", "storySetupHandoffId", "handoff_id", "id"]) ||
      pickId(storySetupHandoff, ["story_setup_handoff_id", "storySetupHandoffId", "handoff_id", "id"]) ||
      (storySetupPromptChanged ? "" : refs.storySetupHandoffId),
    characterId:
      pickId(result, ["character_id", "characterId", "role_id", "id"]) ||
      pickId(generatedRoleDraftPayload, ["character_id", "characterId", "role_id", "id"]) ||
      pickId(generatedRoleDraftPayload?.character, ["character_id", "characterId", "role_id", "id"]) ||
      pickId(generatedRoleDraftPayload?.role, ["character_id", "characterId", "role_id", "id"]) ||
      refs.characterId ||
      pickId(firstRole, ["character_id", "characterId", "role_id", "id"]),
    roleTier:
      String(
        result?.target_tier ||
        result?.targetTier ||
        generatedRoleDraftPayload?.target_tier ||
        generatedRoleDraftPayload?.targetTier ||
        generatedRoleDraftPayload?.complexity_profile?.tier ||
        generatedRoleDraftPayload?.complexityProfile?.tier ||
        generatedRoleDraftPayload?.character?.tier ||
        generatedRoleDraftPayload?.role?.tier ||
        refs.roleTier ||
        currentCharacterDraft?.target_tier ||
        currentCharacterDraft?.targetTier ||
        currentCharacter?.tier ||
        firstRole?.tier ||
        "",
      ).toUpperCase(),
    roleStateChangeId: pickId(result, ["change_id", "role_state_change_id", "id"]) || refs.roleStateChangeId,
    chapterId: resolvedChapterId,
    chapterIndex: chapterIndex || refs.chapterIndex,
    chapterFrameworkId:
      pickId(result, ["chapter_framework_id", "chapterFrameworkId", "id"]) ||
      pickId(chapterFramework, ["chapter_framework_id", "chapterFrameworkId", "id"]) ||
      refs.chapterFrameworkId,
    sceneId: incomingSceneId || (chapterChanged ? "" : refs.sceneId),
    sceneIndex: incomingSceneIndex || (chapterChanged ? 1 : refs.sceneIndex),
    sceneRevisionId:
      pickId(result, ["revision_id", "revisionId", "id"]) ||
      pickId(currentSceneRevisionCandidate, ["revision_id", "revisionId", "id"]) ||
      (chapterChanged ? "" : refs.sceneRevisionId),
    continuityIssueId: pickId(result, ["issue_id", "issueId", "id"]) || refs.continuityIssueId,
    modificationPreviewId: pickId(result, ["preview_id", "previewId", "id"]) || refs.modificationPreviewId,
    preModifyCandidateId: pickId(result, ["candidate_id", "candidateId", "id"]) || refs.preModifyCandidateId,
    sceneParticipantSelectionId:
      pickId(result, ["selection_id", "selectionId", "scene_participant_selection_id", "id"]) ||
      pickId(firstSceneParticipantSelection, ["selection_id", "selectionId", "scene_participant_selection_id", "id"]) ||
      (chapterChanged ? "" : refs.sceneParticipantSelectionId),
    sceneParticipantCandidateId:
      pickId(result, sceneParticipantCandidateIdKeys) ||
      pickId(firstSceneParticipantCandidate, sceneParticipantCandidateIdKeys) ||
      firstIdFromList(result, ["pending_creation_candidate_ids", "candidate_ids"], sceneParticipantCandidateIdKeys) ||
      firstIdFromList(participantSelection, ["pending_creation_candidate_ids", "candidate_ids"], sceneParticipantCandidateIdKeys) ||
      (chapterChanged ? "" : refs.sceneParticipantCandidateId),
    chapterArchiveId: pickId(result, ["chapter_archive_id", "chapterArchiveId", "archive_id", "id"]) || refs.chapterArchiveId,
    nextChapterPreparationId:
      pickId(result, ["preparation_id", "preparationId", "id"]) ||
      pickId(nextChapterPreparation, ["preparation_id", "preparationId", "id"]) ||
      refs.nextChapterPreparationId,
    finalReadinessGateId:
      pickFinalReadinessGateId(result) ||
      pickFinalReadinessGateId(nestedActionResult) ||
      pickFinalReadinessGateId(readinessGate) ||
      refs.finalReadinessGateId,
    finalExportRunId:
      pickId(result, ["export_run_id", "exportRunId", "run_id", "id"]) ||
      pickId(nestedActionResult, ["export_run_id", "exportRunId", "run_id", "id"]) ||
      pickId(exportRun, ["export_run_id", "exportRunId", "run_id", "id"]) ||
      pickId(firstExportRun, ["export_run_id", "exportRunId", "run_id", "id"]) ||
      refs.finalExportRunId,
    finalSnapshotId:
      pickId(result, ["snapshot_id", "snapshotId", "id"]) ||
      pickId(nestedActionResult, ["snapshot_id", "snapshotId", "id"]) ||
      pickId(snapshot, ["snapshot_id", "snapshotId", "id"]) ||
      pickId(exportRun, ["snapshot_id", "snapshotId"]) ||
      pickId(firstExportRun, ["snapshot_id", "snapshotId"]) ||
      refs.finalSnapshotId,
    finalViewerStateId: pickId(result, ["viewer_state_id", "viewerStateId", "id"]) || refs.finalViewerStateId,
    pluginId: pickId(result, ["plugin_id", "pluginId", "id"]) || refs.pluginId || "script_forging",
    pluginRunId:
      pickId(result, ["plugin_run_id", "pluginRunId", "run_id", "id"]) ||
      pickId(firstPluginRun, ["plugin_run_id", "pluginRunId", "run_id", "id"]) ||
      refs.pluginRunId,
    pluginCheckpointId:
      pickId(result, ["checkpoint_id", "checkpointId", "id"]) ||
      pickId(firstCheckpoint, ["checkpoint_id", "checkpointId", "id"]) ||
      refs.pluginCheckpointId,
    pluginArtifactId: pickId(result, ["artifact_id", "artifactId", "id"]) || refs.pluginArtifactId,
    modelProfileId:
      pickId(result, ["profile_id", "profileId", "id"]) ||
      pickId(firstProfile, ["profile_id", "profileId", "id"]) ||
      pickId(activeModelSelection, ["provider_profile_id", "providerProfileId", "profile_id", "profileId", "id"]) ||
      refs.modelProfileId,
  };
}

function createDemoResult(actionId, refs) {
  const safe = actionId.replace(/[^a-z0-9]+/gi, "_");
  return {
    mode: "demo",
    action_id: actionId,
    id: `${safe}_${Date.now()}`,
    project_id: refs.projectId || "demo_project",
    scene_id: refs.sceneId || "demo_scene",
    status: "ok",
  };
}

const defaultPayload = {
  userInput: "来自产品 UI 的确认。",
  safeUserNote: "产品 UI 操作。",
  answerText: "用户已补充必要信息。",
  requestedChanges: ["请根据用户修订意见重新整理草案。"],
};

function defaultAnalyzeStoriesFrameworkPackage() {
  const macroComponents = [
    {
      component_id: "macro_opening",
      label: "开局压力",
      order: 1,
      instruction: "引入核心压力与第一次可见选择。",
    },
    {
      component_id: "macro_turn",
      label: "中点转折",
      order: 2,
      instruction: "改变故事路径，让早前假设不再足够。",
    },
  ];
  const chapterModules = [
    {
      module_id: "chapter_function",
      label: "篇章功能",
      allowed_components: ["macro_opening", "macro_turn"],
    },
    {
      module_id: "reader_emotion",
      label: "读者情绪",
      allowed_components: ["macro_opening", "macro_turn"],
    },
    {
      module_id: "character_desire",
      label: "角色欲望",
      allowed_components: ["macro_opening", "macro_turn"],
    },
    {
      module_id: "character_arc",
      label: "人物弧光",
      allowed_components: ["macro_opening", "macro_turn"],
    },
    {
      module_id: "conflict",
      label: "冲突",
      allowed_components: ["macro_opening", "macro_turn"],
    },
    {
      module_id: "information_release",
      label: "信息释放",
      allowed_components: ["macro_opening", "macro_turn"],
    },
    {
      module_id: "style_pacing",
      label: "风格与节奏",
      allowed_components: ["macro_opening", "macro_turn"],
    },
  ];
  const builtModules = chapterModules.map((module) => ({
    module_id: module.module_id,
    label: module.label,
    components: [{ component_id: "macro_opening" }, { component_id: "macro_turn" }],
  }));
  return {
    source: "analyze_stories",
    metadata: {
      source: "analyze_stories",
      analyzer_version: "production_ui_live_parity_v1",
      workflow_version: "phase85_production_ui",
      model: "deterministic_verifier",
      processed_at: new Date().toISOString(),
    },
    macro_framework: {
      framework_id: "production_ui_live_parity_framework",
      label: "Production UI Live Parity Framework",
      components: macroComponents,
    },
    component_vocabulary: {
      chapter_modules: chapterModules,
    },
    chapter_macro_assignments: [
      {
        chapter_index: 1,
        linked_macro_component_ids: ["macro_opening", "macro_turn"],
        assignment_type: "analyze_stories_recommended",
        safe_summary: "Chapter 1 receives opening and turn pressure recommendations.",
      },
    ],
    built_chapter_frameworks: [
      {
        chapter_index: 1,
        chapter_id: "chapter_001",
        chapter_framework_id: "chapter_framework_001",
        linked_macro_component_ids: ["macro_opening", "macro_turn"],
        modules: builtModules,
        safe_summary: "Inactive imported framework candidate for live parity verification.",
      },
    ],
    input_fingerprints: [
      {
        input_filename: "production-ui-live-parity-framework-package.json",
        chapter_index: 1,
        input_title: "Production UI Live Parity Framework",
        input_content_sha256: "0".repeat(64),
        text_length: 1200,
        analyzer_version: "production_ui_live_parity_v1",
        workflow_version: "phase85_production_ui",
        model: "deterministic_verifier",
        processed_at: new Date().toISOString(),
      },
    ],
  };
}

const OPTIONAL_READ_TIMEOUT_MS = 8000;

async function safeRead(reader, timeoutMs = OPTIONAL_READ_TIMEOUT_MS) {
  let timeoutId = null;
  try {
    const timeout = new Promise((_, reject) => {
      timeoutId = globalThis.setTimeout(() => {
        const error = new Error("Optional backend state read timed out.");
        error.code = "OPTIONAL_READ_TIMEOUT";
        reject(error);
      }, timeoutMs);
    });
    return await Promise.race([reader(), timeout]);
  } catch {
    return null;
  } finally {
    if (timeoutId) {
      globalThis.clearTimeout(timeoutId);
    }
  }
}

function withActionTimeout(promise, timeoutMs, code = "ACTION_TIMEOUT") {
  let timeoutId = null;
  const timeout = new Promise((_, reject) => {
    timeoutId = globalThis.setTimeout(() => {
      const error = new Error("Action request timed out.");
      error.code = code;
      reject(error);
    }, timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timeoutId) {
      globalThis.clearTimeout(timeoutId);
    }
  });
}

function delay(ms) {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms);
  });
}

function mergeHydratedRefs(refs, ...results) {
  return results.filter(Boolean).reduce((current, result) => updateRefsFromResult(current, result), refs);
}

function refsForActiveProject(refs, projectId) {
  const nextProjectId = String(projectId || "").trim();
  if (!nextProjectId || nextProjectId === String(refs?.projectId || refs?.selectedProjectId || "").trim()) {
    return refs || {};
  }
  return {
    projectId: nextProjectId,
    selectedProjectId: nextProjectId,
    pluginId: refs?.pluginId || "script_forging",
    ...(refs?.modelProfileId ? { modelProfileId: refs.modelProfileId } : {}),
  };
}

function stateParams(refs) {
  const projectId = refs.projectId || refs.selectedProjectId || "";
  return projectId ? { projectId } : {};
}

async function loadShellState(refs, workspaceId = "") {
  const params = stateParams(refs);
  const navigationParams = workspaceId ? { ...params, workspaceId } : params;
  const [
    health,
    projectStatus,
    projectData,
    appProgress,
    navigationWorkspaces,
    navigationGroups,
    navigationState,
    navigationAvailability,
    workspaceAccess,
    navigationPreferences,
    modeProfile,
    progressState,
    progressSummary,
    progressNextActions,
    progressDecisionSurfaces,
    progressBlockingIssues,
    progressSafetyReport,
  ] = await Promise.all([
    safeRead(() => projectApi.getHealth()),
    safeRead(() => projectApi.getProjectStatus()),
    safeRead(() => projectApi.getProjectData()),
    safeRead(() => getAppProgress()),
    safeRead(() => projectApi.getProductNavigationWorkspaces()),
    safeRead(() => projectApi.getProductNavigationGroups()),
    safeRead(() => projectApi.getProductNavigationState(navigationParams)),
    safeRead(() => projectApi.getProductNavigationAvailability(params)),
    workspaceId ? safeRead(() => projectApi.getProductWorkspaceAccess(workspaceId, params)) : Promise.resolve(null),
    safeRead(() => projectApi.getProductNavigationPreferences()),
    safeRead(() => projectApi.getProductModeProfile()),
    safeRead(() => projectApi.getProductProgressState(params)),
    safeRead(() => projectApi.getProductProgressSummary(params)),
    safeRead(() => projectApi.getProductProgressNextActions(params)),
    safeRead(() => projectApi.getProductProgressDecisionSurfaces(params)),
    safeRead(() => projectApi.getProductProgressBlockingIssues(params)),
    safeRead(() => projectApi.getProductProgressSafetyReport(params)),
  ]);

  return compactObject({
    health,
    project_status: projectStatus,
    project_data: projectData,
    app_progress: appProgress,
    product_navigation_workspaces: navigationWorkspaces,
    product_navigation_groups: navigationGroups,
    product_navigation_state: navigationState,
    product_navigation_availability: navigationAvailability,
    product_workspace_access: workspaceAccess,
    product_navigation_preferences: navigationPreferences,
    product_mode_profile: modeProfile,
    product_progress_state: progressState,
    product_progress_summary: progressSummary,
    product_progress_next_actions: progressNextActions,
    product_progress_decision_surfaces: progressDecisionSurfaces,
    product_progress_blocking_issues: progressBlockingIssues,
    product_progress_safety_report: progressSafetyReport,
  });
}

async function loadCurrentProjectOverview(refs = {}) {
  const params = stateParams(refs);
  const [
    projectStatus,
    projectData,
    appProgress,
    activeProjectSelection,
    activeModelSelection,
    progressState,
    progressSummary,
    progressNextActions,
    progressBlockingIssues,
    finalExports,
  ] = await Promise.all([
    safeRead(() => projectApi.getProjectStatus()),
    safeRead(() => projectApi.getProjectData()),
    safeRead(() => getAppProgress()),
    safeRead(() => projectApi.getActiveProjectSelection()),
    safeRead(() => projectApi.getActiveModelSelection()),
    safeRead(() => projectApi.getProductProgressState(params)),
    safeRead(() => projectApi.getProductProgressSummary(params)),
    safeRead(() => projectApi.getProductProgressNextActions(params)),
    safeRead(() => projectApi.getProductProgressBlockingIssues(params)),
    safeRead(() => projectApi.getFinalStoryPackageExportRuns()),
  ]);

  return compactObject({
    project_status: projectStatus,
    project_data: projectData,
    app_progress: appProgress,
    active_project_selection: activeProjectSelection,
    active_model_selection: activeModelSelection,
    product_progress_state: progressState,
    product_progress_summary: progressSummary,
    product_progress_next_actions: progressNextActions,
    product_progress_blocking_issues: progressBlockingIssues,
    final_exports: finalExports,
  });
}

async function loadWorkspaceNavigation(refs, workspaceId) {
  return loadShellState(refs, workspaceId);
}

async function loadFrameworkWorkbenchSurface(refs = {}) {
  const [
    workbench,
    frameworkPackage,
    libraryItems,
    privateFrameworks,
    systemRecommendations,
  ] = await Promise.all([
    safeRead(() => projectApi.getFrameworkWorkbench()),
    safeRead(() => projectApi.getFrameworkPackage()),
    safeRead(() => projectApi.getFrameworkLibraryItems()),
    safeRead(() => projectApi.getFrameworkLibraryPrivateFrameworks()),
    safeRead(() => projectApi.getFrameworkLibrarySystemRecommendations()),
  ]);

  return compactObject({
    project_id: refs.projectId || refs.selectedProjectId || "",
    workbench,
    framework_workbench: workbench,
    framework_package: frameworkPackage,
    library_items: libraryItems,
    framework_library_items: libraryItems,
    private_frameworks: privateFrameworks,
    system_recommendations: systemRecommendations,
  });
}

const NAVIGATION_WORKSPACE_IDS = {
  "navigation.createProject": "create_project",
  "navigation.templateDemo": "template_demo",
  "navigation.framework": "framework",
  "navigation.analyzeStories": "analyze_stories",
  "navigation.storySetup": "story_setup",
  "navigation.worldCanvas": "world_canvas",
  "navigation.characters": "characters",
  "navigation.chapterPlan": "chapter_plan",
  "navigation.scene": "chapter_scene",
  "navigation.finalOutputs": "final_outputs",
  "navigation.pluginOutputs": "plugin_outputs",
  "navigation.settings": "settings",
};

export function workspaceIdForPageId(pageId) {
  if (["project-create", "projects", "current-project"].includes(pageId)) {
    return "create_project";
  }
  if (["template-demo"].includes(pageId)) {
    return "template_demo";
  }
  if (["framework", "framework-library", "imported-session"].includes(pageId)) {
    return "framework";
  }
  if (["import-source", "analyzing", "analysis-result", "framework-candidate"].includes(pageId)) {
    return "analyze_stories";
  }
  if (String(pageId || "").startsWith("story-setup")) {
    return "story_setup";
  }
  if (String(pageId || "").startsWith("world-")) {
    return "world_canvas";
  }
  if (
    [
      "character-entry",
      "character-generating",
      "character-review",
      "character-conflict",
      "character-missing",
      "character-revision",
      "character-confirm",
      "role-library",
      "role-context",
      "a-tier-state-change",
    ].includes(pageId)
  ) {
    return "characters";
  }
  if (String(pageId || "").startsWith("chapter-") && pageId !== "chapter-closeout") {
    return "chapter_plan";
  }
  if (String(pageId || "").startsWith("scene-") || pageId === "chapter-closeout") {
    return "chapter_scene";
  }
  if (String(pageId || "").startsWith("final-")) {
    return "final_outputs";
  }
  if (String(pageId || "").startsWith("plugin-")) {
    return "plugin_outputs";
  }
  if (String(pageId || "").startsWith("settings-")) {
    return "settings";
  }
  return "";
}

function workspaceIdForAction(actionId) {
  if (NAVIGATION_WORKSPACE_IDS[actionId]) {
    return NAVIGATION_WORKSPACE_IDS[actionId];
  }
  if (actionId.startsWith("navigation.")) {
    return "";
  }
  if (actionId.startsWith("project.") || actionId.startsWith("projects.")) {
    return "create_project";
  }
  if (actionId.startsWith("template.")) {
    return "template_demo";
  }
  if (actionId.startsWith("framework.")) {
    return "framework";
  }
  if (actionId.startsWith("analyze.")) {
    return "analyze_stories";
  }
  if (actionId.startsWith("storySetup.")) {
    return "story_setup";
  }
  if (actionId.startsWith("world.")) {
    return "world_canvas";
  }
  if (actionId.startsWith("characters.") || actionId.startsWith("roles.")) {
    return "characters";
  }
  if (actionId.startsWith("chapter.")) {
    return "chapter_plan";
  }
  if (actionId.startsWith("scene.")) {
    return "chapter_scene";
  }
  if (actionId.startsWith("final.")) {
    return "final_outputs";
  }
  if (actionId.startsWith("plugins.")) {
    return "plugin_outputs";
  }
  if (actionId.startsWith("settings.")) {
    return "settings";
  }
  return "";
}

export async function hydrateWorkspaceRefs(refs = {}, options = {}) {
  if (!isLiveMode()) {
    return refs;
  }

  const activeSelection = await safeRead(() => projectApi.getActiveProjectSelection());
  const activeProjectId = pickId(
    activeSelection?.active_project_selection || activeSelection?.activeProjectSelection || activeSelection,
    ["project_id", "projectId"],
  );
  let hydrated = mergeHydratedRefs(refsForActiveProject(refs, activeProjectId), activeSelection);
  const projectId = hydrated.projectId || hydrated.selectedProjectId || "";
  const workspaceId = options.workspaceId || "";
  const shouldHydrateStorySetup = workspaceId === "story_setup";
  const shouldHydrateCharacters = workspaceId === "characters";
  const shouldHydrateFramework = workspaceId === "framework";
  const shouldHydrateWorldCanvas = workspaceId === "world_canvas";
  const shouldHydrateScene = workspaceId === "chapter_scene";
  const shouldHydrateFinalOutputs = workspaceId === "final_outputs";
  const shouldHydratePluginOutputs = workspaceId === "plugin_outputs";
  const shouldHydrateSettings = workspaceId === "settings";
  const preserveSceneSelection = Boolean(
    options.preserveSceneSelection &&
      hydrated.sceneSelectionPinned &&
      hydrated.sceneId &&
      Number(hydrated.sceneIndex || 0) > 0,
  );
  const pinnedSceneSelection = preserveSceneSelection
    ? {
        chapterId: hydrated.chapterId,
        sceneId: hydrated.sceneId,
        sceneIndex: Number(hydrated.sceneIndex),
        sceneSelectionPinned: true,
      }
    : null;
  const sceneStoryProgress = shouldHydrateScene
    ? await safeRead(() => projectApi.getStoryProgressCurrent())
    : null;
  const authoritativeSceneChapterId = preferRuntimeChapterId(
    sceneStoryProgress?.current_chapter_id || sceneStoryProgress?.currentChapterId,
    hydrated.chapterId,
  );

  const [
    shellState,
    projectCreationModes,
    projectCreationDemoSeeds,
    projectCreationState,
    storySetupState,
    storySetupPrompt,
    storySetupIntake,
    storySetupDraftBundle,
    storySetupDecision,
    storySetupHandoff,
    roles,
    generatedRoleDraft,
    worldCanvas,
    worldPremise,
    currentScene,
    sceneProgress,
    storyProgress,
    sceneParticipantSelection,
    finalReadiness,
    finalExports,
    pluginFinalExports,
    pluginRuns,
    profiles,
    activeModelSelection,
    frameworkWorkbenchSurface,
  ] = await Promise.all([
    safeRead(() => loadShellState(hydrated, workspaceId)),
    safeRead(() => projectApi.getProjectCreationModes()),
    safeRead(() => projectApi.getProjectCreationDemoSeeds()),
    safeRead(() => projectApi.getCurrentProjectCreationState({ projectId })),
    shouldHydrateStorySetup ? safeRead(() => projectApi.getCurrentStorySetupState({ projectId })) : Promise.resolve(null),
    shouldHydrateStorySetup && hydrated.storySetupPromptId ? safeRead(() => projectApi.getStorySetupPrompt(hydrated.storySetupPromptId)) : Promise.resolve(null),
    shouldHydrateStorySetup && hydrated.storySetupIntakeId ? safeRead(() => projectApi.getStorySetupIntake(hydrated.storySetupIntakeId)) : Promise.resolve(null),
    shouldHydrateStorySetup && hydrated.storySetupDraftBundleId ? safeRead(() => projectApi.getStorySetupDraftBundle(hydrated.storySetupDraftBundleId)) : Promise.resolve(null),
    shouldHydrateStorySetup && hydrated.storySetupDecisionId ? safeRead(() => projectApi.getStorySetupDecision(hydrated.storySetupDecisionId)) : Promise.resolve(null),
    shouldHydrateStorySetup && hydrated.storySetupHandoffId ? safeRead(() => projectApi.getStorySetupHandoff(hydrated.storySetupHandoffId)) : Promise.resolve(null),
    shouldHydrateCharacters ? safeRead(() => projectApi.getRoles({ includeArchived: false })) : Promise.resolve(null),
    shouldHydrateCharacters ? safeRead(() => projectApi.getGeneratedRoleDraft()) : Promise.resolve(null),
    shouldHydrateWorldCanvas ? safeRead(() => projectApi.getCurrentWorldCanvas()) : Promise.resolve(null),
    shouldHydrateWorldCanvas ? safeRead(() => projectApi.getCurrentProjectStoryPremise()) : Promise.resolve(null),
    shouldHydrateScene ? safeRead(() => projectApi.getCurrentScene(authoritativeSceneChapterId || null, Number(hydrated.sceneIndex || 0) || null)) : Promise.resolve(null),
    shouldHydrateScene ? safeRead(() => projectApi.getSceneProgress(authoritativeSceneChapterId || null)) : Promise.resolve(null),
    shouldHydrateScene ? Promise.resolve(sceneStoryProgress) : Promise.resolve(null),
    shouldHydrateScene
      ? safeRead(() => projectApi.getCurrentSceneParticipantSelection(authoritativeSceneChapterId || null, Number(hydrated.sceneIndex || 1)))
      : Promise.resolve(null),
    shouldHydrateFinalOutputs ? safeRead(() => projectApi.getFinalStoryPackageReadiness()) : Promise.resolve(null),
    shouldHydrateFinalOutputs ? safeRead(() => projectApi.getFinalStoryPackageExportRuns()) : Promise.resolve(null),
    shouldHydratePluginOutputs ? safeRead(() => projectApi.getFinalStoryPackageExportRuns()) : Promise.resolve(null),
    shouldHydratePluginOutputs ? safeRead(() => projectApi.getPluginRuns()) : Promise.resolve(null),
    shouldHydrateSettings ? safeRead(() => projectApi.getModelProviderProfiles()) : Promise.resolve(null),
    shouldHydrateSettings ? safeRead(() => projectApi.getActiveModelSelection()) : Promise.resolve(null),
    shouldHydrateFramework ? safeRead(() => loadFrameworkWorkbenchSurface(hydrated)) : Promise.resolve(null),
  ]);

  hydrated = mergeHydratedRefs(
    hydrated,
    shellState,
    projectCreationModes,
    projectCreationDemoSeeds,
    projectCreationState,
    storySetupState,
    storySetupPrompt,
    storySetupIntake,
    storySetupDraftBundle,
    storySetupDecision,
    storySetupHandoff,
    roles,
    generatedRoleDraft,
    worldCanvas,
    worldPremise,
    currentScene,
    sceneProgress,
    storyProgress,
    sceneParticipantSelection,
    finalReadiness,
    finalExports,
    pluginFinalExports,
    pluginRuns,
    profiles,
    activeModelSelection,
    frameworkWorkbenchSurface,
  );

  if (shouldHydrateScene) {
    const progressSceneIndex = Number(
      sceneProgress?.next_scene_index ||
        sceneProgress?.nextSceneIndex ||
        sceneProgress?.current_scene_index ||
        sceneProgress?.currentSceneIndex ||
        0,
    ) || 0;
    const progressChapterId = preferRuntimeChapterId(
      sceneProgress?.chapter_id || sceneProgress?.chapterId,
      storyProgress?.current_chapter_id || storyProgress?.currentChapterId,
      hydrated.chapterId,
    );
    if (progressSceneIndex > 0 && !preserveSceneSelection) {
      const progressScene = await safeRead(() =>
        projectApi.getCurrentScene(progressChapterId || null, progressSceneIndex),
      );
      hydrated = mergeHydratedRefs(
        hydrated,
        progressScene,
        {
          chapter_id: progressChapterId,
          scene_index: progressSceneIndex,
        },
      );
    }
  }

  const [storySetupQuestions, storySetupSafetyReport] = await Promise.all([
    shouldHydrateStorySetup && hydrated.storySetupDraftBundleId
      ? safeRead(() => projectApi.getStorySetupQuestions(hydrated.storySetupDraftBundleId))
      : Promise.resolve(null),
    shouldHydrateStorySetup && hydrated.storySetupDraftBundleId
      ? safeRead(() => projectApi.getStorySetupSafetyReport(hydrated.storySetupDraftBundleId))
      : Promise.resolve(null),
  ]);

  hydrated = mergeHydratedRefs(hydrated, storySetupQuestions, storySetupSafetyReport);

  if (pinnedSceneSelection) {
    hydrated = {
      ...hydrated,
      ...pinnedSceneSelection,
    };
  }

  return {
    ...hydrated,
    pluginId: hydrated.pluginId || "script_forging",
  };
}

function projectCreationPayload(form) {
  const promptText = firstNonEmptyText(form.projectPrompt, form.promptText, form.setupPrompt, form.storyPrompt);
  const modeType = form.modeType || (promptText ? "prompt_first_project" : "blank_project");
  const requestedTitle = firstUserProjectTitle(form.projectTitle, form.requestedTitle, form.projectName);
  return {
    requestedTitle: requestedTitle || "未命名故事项目",
    requestedLanguage: form.projectLanguage || form.requestedLanguage || "zh",
    promptText,
    modeType,
    explicitUserSelection: true,
  };
}

async function createConfirmedProject(form) {
  const controlledPromptText = firstNonEmptyText(
    form.projectPrompt,
    form.promptText,
    form.setupPrompt,
    form.storyPrompt,
  );
  globalThis.__mafsWorkspaceActionPhase = "project_create:request";
  const request = await projectApi.createProjectCreationRequest(projectCreationPayload(form));
  const requestId = pickId(request, ["creation_request_id", "creationRequestId", "request_id", "id"]);
  globalThis.__mafsWorkspaceActionPhase = `project_create:validate:${requestId}`;
  const validation = await projectApi.validateProjectCreationRequest(requestId);
  globalThis.__mafsWorkspaceActionPhase = `project_create:draft:${requestId}`;
  const draft = await projectApi.createProjectCreationDraftRecoverable(requestId);
  const draftId = pickId(draft, ["creation_draft_id", "creationDraftId", "draft_id", "id"]);
  globalThis.__mafsWorkspaceActionPhase = `project_create:confirm:${draftId}`;
  const decision = await projectApi.confirmProjectCreationDraft(draftId, defaultPayload);
  const projectId =
    pickId(decision, ["project_id", "projectId"]) ||
    pickId(draft, ["proposed_project_id", "project_id", "projectId"]);

  let activeSelection = null;
  let openedProject = null;
  if (projectId) {
    globalThis.__mafsWorkspaceActionPhase = `project_create:open:${projectId}`;
    openedProject = await safeRead(() => projectApi.openProject(projectId));
    globalThis.__mafsWorkspaceActionPhase = `project_create:set_active:${projectId}`;
    activeSelection = await safeRead(() => projectApi.setActiveProjectSelection({
      projectId,
      selectedBy: "user",
    }));
  }
  const storySetupPrompt = projectId && controlledPromptText
    ? await projectApi.createStorySetupPromptFromProject({
        projectId,
        creationRequestId: requestId,
        promptText: controlledPromptText,
      })
    : null;
  globalThis.__mafsWorkspaceActionPhase = "project_create:done";

  return compactObject({
    action: "project.createConfirmed",
    project_id: projectId,
    creation_request_id: requestId,
    creation_draft_id: draftId,
    request,
    validation,
    draft,
    decision,
    open_project: openedProject,
    active_project_selection: activeSelection,
    story_setup_prompt: storySetupPrompt,
  });
}

async function createOrReuseStorySetupPrompt(refs, form) {
  const projectId = refs.projectId || refs.selectedProjectId || "";
  const promptText = firstNonEmptyText(
    form.setupPrompt,
    form.promptText,
    form.projectPrompt,
    form.storyPrompt,
    refs.setupPrompt,
    refs.promptText,
    refs.projectPrompt,
  );
  const current = await safeRead(() => projectApi.getCurrentStorySetupState({ projectId }), 8000);
  const currentPromptText = firstNonEmptyText(current?.controlled_prompt_text, current?.controlledPromptText);
  if (
    (current?.story_setup_prompt || current?.storySetupPrompt || current?.story_setup_draft_bundle || current?.storySetupDraftBundle) &&
    (!promptText || promptText === currentPromptText)
  ) {
    return current;
  }
  return projectApi.createStorySetupPromptFromProject({
    projectId,
    promptText,
  });
}

async function loadCurrentStorySetupSurface(refs) {
  const projectId = refs.projectId || refs.selectedProjectId || "";
  const [current, projectCreationState] = await Promise.all([
    projectApi.getCurrentStorySetupState({ projectId }),
    safeRead(() => projectApi.getCurrentProjectCreationState({ projectId })),
  ]);
  return compactObject({
    ...current,
    project_creation_state: projectCreationState,
    creation_request: projectCreationState?.creation_request || projectCreationState?.creationRequest,
    creation_draft: projectCreationState?.creation_draft || projectCreationState?.creationDraft,
  });
}

async function loadStorySetupProjectPrompt(refs) {
  const current = await loadCurrentStorySetupSurface(refs);
  if (!String(current?.controlled_prompt_text || current?.controlledPromptText || "").trim()) {
    const error = new Error("当前项目没有可载入的原始提示词，请先在新建项目时填写故事构想。");
    error.code = "CONTROLLED_PROJECT_PROMPT_MISSING";
    throw error;
  }
  return current;
}

async function createOrReuseStorySetupDecision(refs, form = {}, forcedDecisionType = "") {
  const projectId = refs.projectId || refs.selectedProjectId || "";
  const bundleId = requireRef(refs, "storySetupDraftBundleId", "故事设定草案 ID");
  const decisionType = forcedDecisionType || form.decisionType || "confirm_for_handoff";
  const current = await safeRead(() => projectApi.getCurrentStorySetupState({ projectId }), 8000);
  const existing = current?.story_setup_decision || current?.storySetupDecision || null;
  const existingBundleId = pickId(existing, ["story_setup_draft_bundle_id", "storySetupDraftBundleId", "draft_bundle_id"]);
  const existingType = String(existing?.decision_type || existing?.decisionType || "");
  if (existing && existingBundleId === bundleId && existingType === decisionType) {
    return current;
  }
  return projectApi.createStorySetupDecision(bundleId, {
    decisionType,
    safeUserNote: form.decisionNote || form.safeUserNote || "",
    requestedChanges: decisionType === "request_revision"
      ? [form.decisionNote || form.safeUserNote || "请根据用户选择修订故事设定草案。"]
      : [],
  });
}

async function confirmExistingProjectDraft(refs) {
  const draftId = requireRef(refs, "creationDraftId", "项目草稿 ID");
  const draft = await safeRead(() => projectApi.getProjectCreationDraft(draftId));
  const decision = await projectApi.confirmProjectCreationDraft(draftId, defaultPayload);
  const projectId =
    pickId(decision, ["project_id", "projectId"]) ||
    pickId(draft, ["proposed_project_id", "project_id", "projectId"]);
  const openedProject = projectId ? await safeRead(() => projectApi.openProject(projectId)) : null;
  const activeSelection = projectId
    ? await safeRead(() => projectApi.setActiveProjectSelection({ projectId, selectedBy: "user" }))
    : null;

  return compactObject({
    action: "project.confirmExistingDraft",
    project_id: projectId,
    creation_draft_id: draftId,
    draft,
    decision,
    open_project: openedProject,
    active_project_selection: activeSelection,
  });
}

async function instantiateTemplate(refs) {
  let requestId = refs.templateInstantiationRequestId;
  let request = null;
  if (!requestId) {
    request = await projectApi.createTemplateInstantiationRequest(refs.templateId || "default", {
      ...defaultPayload,
      projectId: refs.projectId || refs.selectedProjectId || "",
    });
    requestId = pickId(request, ["template_instantiation_request_id", "templateInstantiationRequestId", "request_id", "id"]);
  }
  const validation = await projectApi.validateTemplateInstantiationRequest(requestId);
  const instantiation = await projectApi.instantiateTemplateRequest(requestId);
  return compactObject({
    template_instantiation_request_id: requestId,
    request,
    validation,
    instantiation,
  });
}

async function validateAndConfirmFrameworkWorkbench(form) {
  const premise = await safeRead(() => projectApi.getCurrentProjectStoryPremise());
  const premiseText = projectStoryPremiseText(premise);
  const premiseChapterCount = inferChapterCountFromText(premiseText);
  const requestedChapterCount = premiseChapterCount || Number(form.chapterCount || form.frameworkChapterCount || 0);
  const chapterCountUpdate =
    requestedChapterCount > 0
      ? await projectApi.updateFrameworkWorkbenchChapterCount(requestedChapterCount, true, true)
      : null;
  const recommendation = await projectApi.recommendFrameworkWorkbenchMapping(
    requestedChapterCount > 0 ? requestedChapterCount : 5,
    "balanced",
    true,
  );
  const workbench = await projectApi.getFrameworkWorkbench();
  const validation = await projectApi.validateFrameworkWorkbenchMapping();
  const confirmation = await projectApi.confirmFrameworkWorkbenchMapping(
    form.frameworkNote || defaultPayload.safeUserNote,
    true,
  );
  const confirmedWorkbench = await safeRead(() => projectApi.getFrameworkWorkbench());

  return compactObject({
    chapter_count_update: chapterCountUpdate,
    project_story_premise: premise,
    recommendation,
    workbench,
    validation,
    confirmation,
    confirmed_workbench: confirmedWorkbench,
  });
}

async function loadStorySetupDraftBundleSurface(refs, draftBundle, prompt = null, intake = null) {
  const draftBundleId = pickId(draftBundle, ["story_setup_draft_bundle_id", "storySetupDraftBundleId", "draft_bundle_id", "id"]);
  if (!draftBundleId) {
    const error = new Error("Story setup draft bundle was not created.");
    error.code = "STORY_SETUP_DRAFT_BUNDLE_MISSING";
    throw error;
  }
  const [questions, safetyReport] = await Promise.all([
    safeRead(() => projectApi.getStorySetupQuestions(draftBundleId)),
    safeRead(() => projectApi.getStorySetupSafetyReport(draftBundleId)),
  ]);

  return compactObject({
    prompt,
    intake,
    story_setup_intake_id: pickId(intake, ["story_setup_intake_id", "storySetupIntakeId", "intake_id", "id"]),
    draft_bundle: draftBundle,
    story_setup_draft_bundle_id: draftBundleId,
    questions,
    safety_report: safetyReport,
  });
}

function storySetupPromptIdFor(value) {
  return pickId(value, ["story_setup_prompt_id", "storySetupPromptId", "prompt_id"]);
}

function storySetupSurfaceMatchesPrompt(surface, promptId) {
  if (!promptId || !surface) {
    return false;
  }
  const draftBundle = surface.draft_bundle || surface.draftBundle || surface;
  const prompt = surface.prompt || surface.story_setup_prompt || surface.storySetupPrompt || null;
  return storySetupPromptIdFor(draftBundle) === promptId || storySetupPromptIdFor(prompt) === promptId;
}

function storySetupSurfaceNeedsRealProviderRetry(surface) {
  if (!surface) {
    return false;
  }
  const draftBundle = surface.draft_bundle || surface.draftBundle || surface;
  const prompt = surface.prompt || surface.story_setup_prompt || surface.storySetupPrompt || {};
  const providerType = String(
    prompt.active_model_provider_type ||
      prompt.activeModelProviderType ||
      draftBundle.active_model_provider_type ||
      draftBundle.activeModelProviderType ||
      "",
  )
    .trim()
    .toLowerCase();
  const usedFallback = Boolean(
    draftBundle.used_deterministic_fallback ?? draftBundle.usedDeterministicFallback,
  );
  return usedFallback && providerType !== "local";
}

async function readCurrentStorySetupDraftBundleSurface(refs) {
  const current = await safeRead(
    () => projectApi.getCurrentStorySetupState({ projectId: refs.projectId || refs.selectedProjectId || "" }),
    8000,
  );
  const draftBundle = current?.story_setup_draft_bundle || current?.storySetupDraftBundle || null;
  if (!draftBundle) {
    return null;
  }
  return loadStorySetupDraftBundleSurface(
    refs,
    draftBundle,
    current?.story_setup_prompt || current?.storySetupPrompt || null,
    current?.story_setup_intake || current?.storySetupIntake || null,
  );
}

async function createStorySetupDraftBundleWithQuestions(refs) {
  let promptId = refs.storySetupPromptId || "";
  let recoveredCurrentState = null;
  let recoveredCurrentSurface = null;

  if (!promptId) {
    recoveredCurrentState = await safeRead(
      () => projectApi.getCurrentStorySetupState({ projectId: refs.projectId || refs.selectedProjectId || "" }),
      8000,
    );
    const currentPrompt = recoveredCurrentState?.story_setup_prompt || recoveredCurrentState?.storySetupPrompt || null;
    const currentDraftBundle =
      recoveredCurrentState?.story_setup_draft_bundle || recoveredCurrentState?.storySetupDraftBundle || null;
    const currentIntake = recoveredCurrentState?.story_setup_intake || recoveredCurrentState?.storySetupIntake || null;
    promptId =
      storySetupPromptIdFor(currentPrompt) ||
      storySetupPromptIdFor(currentDraftBundle) ||
      pickId(recoveredCurrentState, ["story_setup_prompt_id", "storySetupPromptId", "prompt_id"]);
    if (currentDraftBundle) {
      recoveredCurrentSurface = await loadStorySetupDraftBundleSurface(refs, currentDraftBundle, currentPrompt, currentIntake);
    }
  }

  if (!promptId) {
    requireRef(refs, "storySetupPromptId", "故事设定提示 ID");
  }

  if (refs.storySetupDraftBundleId) {
    const existing = await safeRead(() => projectApi.getStorySetupDraftBundle(refs.storySetupDraftBundleId), 8000);
    if (
      existing &&
      storySetupPromptIdFor(existing) === promptId &&
      !storySetupSurfaceNeedsRealProviderRetry({ draft_bundle: existing, prompt: recoveredCurrentState?.story_setup_prompt })
    ) {
      return loadStorySetupDraftBundleSurface(refs, existing);
    }
  }

  const currentSurface = recoveredCurrentSurface || (await readCurrentStorySetupDraftBundleSurface(refs));
  if (
    currentSurface?.story_setup_draft_bundle_id &&
    storySetupSurfaceMatchesPrompt(currentSurface, promptId) &&
    !storySetupSurfaceNeedsRealProviderRetry(currentSurface)
  ) {
    return currentSurface;
  }

  let draftBundle = null;
  try {
    draftBundle = await withActionTimeout(
      projectApi.createStorySetupDraftBundleFromPrompt(promptId),
      100000,
      "STORY_SETUP_DRAFT_TIMEOUT",
    );
  } catch (error) {
    if (error?.code !== "API_REQUEST_TIMEOUT" && error?.code !== "STORY_SETUP_DRAFT_TIMEOUT") {
      throw error;
    }
    const recovered = await readCurrentStorySetupDraftBundleSurface(refs);
    if (
      recovered?.story_setup_draft_bundle_id &&
      storySetupSurfaceMatchesPrompt(recovered, promptId) &&
      !storySetupSurfaceNeedsRealProviderRetry(recovered)
    ) {
      return recovered;
    }
    throw error;
  }
  const prompt =
    recoveredCurrentState?.story_setup_prompt ||
    recoveredCurrentState?.storySetupPrompt ||
    (await safeRead(() => projectApi.getStorySetupPrompt(promptId), 8000));
  return loadStorySetupDraftBundleSurface(refs, draftBundle, prompt);
}

async function answerStorySetupQuestionAndRefresh(refs, form) {
  const questionId = form.storySetupQuestionId || refs.storySetupQuestionId;
  if (!questionId) {
    const error = new Error("缺少故事设定问题 ID，请重新进入审阅页面后再保存回答。");
    error.code = "MISSING_REF";
    throw error;
  }
  const answerText = String(form.answerText || "").trim() || defaultPayload.answerText;
  const answer = await projectApi.answerStorySetupQuestion(questionId, {
    answerText,
    safeUserNote: defaultPayload.safeUserNote,
  });
  const projectId = refs.projectId || refs.selectedProjectId || "";
  const current = projectId
    ? await safeRead(() => projectApi.getCurrentStorySetupState({ projectId }), 8000)
    : null;
  const currentDraftBundle = current?.story_setup_draft_bundle || current?.storySetupDraftBundle || null;
  const draftBundleId =
    refs.storySetupDraftBundleId ||
    pickId(currentDraftBundle, ["story_setup_draft_bundle_id", "storySetupDraftBundleId", "draft_bundle_id", "id"]);
  const questions =
    current?.story_setup_questions ||
    current?.storySetupQuestions ||
    (draftBundleId
      ? await safeRead(() => projectApi.getStorySetupQuestions(draftBundleId))
      : null);
  return compactObject({
    answer,
    questions,
    controlled_question_answers:
      current?.controlled_question_answers ||
      current?.controlledQuestionAnswers ||
      null,
    current_story_setup_state: current,
    story_setup_draft_bundle_id: draftBundleId,
    question_id: pickId(answer, ["question_id", "questionId", "story_setup_question_id", "storySetupQuestionId", "id"]) || questionId,
  });
}

async function recoverStorySetupHandoffAfterTimeout(refs) {
  const projectId = refs.projectId || refs.selectedProjectId || "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const state = await safeRead(
      () => projectApi.getCurrentStorySetupState({ projectId }),
      8000,
    );
    const handoff = state?.story_setup_handoff || state?.storySetupHandoff || null;
    const handoffId = pickId(handoff, ["story_setup_handoff_id", "storySetupHandoffId", "handoff_id", "id"]);
    if (handoffId) {
      return handoff;
    }
    await delay(750);
  }
  return null;
}

async function createOrReuseStorySetupHandoff(refs, form = {}) {
  const projectId = refs.projectId || refs.selectedProjectId || "";
  const current = await safeRead(
    () => projectApi.getCurrentStorySetupState({ projectId }),
    8000,
  );
  const existing = current?.story_setup_handoff || current?.storySetupHandoff || null;
  const existingId = pickId(existing, ["story_setup_handoff_id", "storySetupHandoffId", "handoff_id", "id"]);
  if (existingId) {
    return existing;
  }
  const decisionId = requireRef(refs, "storySetupDecisionId", "故事设定决策 ID");
  try {
    return await projectApi.createStorySetupHandoff(decisionId, {
      targetWorkspace: form.targetWorkspace || "world_canvas_workspace",
      safeUserNote: defaultPayload.safeUserNote,
    });
  } catch (error) {
    if (error?.code !== "API_REQUEST_TIMEOUT") {
      throw error;
    }
    const recovered = await recoverStorySetupHandoffAfterTimeout(refs);
    if (recovered) {
      return recovered;
    }
    throw error;
  }
}

async function resolveWorldGenerationIdea(refs = {}, form = {}) {
  const directIdea = firstUserVisibleText(
    form.worldIdea,
    form.storyIdea,
    form.setupPrompt,
    form.promptText,
    form.projectPrompt,
    form.storyPrompt,
    refs.setupPrompt,
    refs.promptText,
    refs.projectPrompt,
  );
  if (directIdea) {
    return directIdea;
  }

  const projectId = refs.projectId || refs.selectedProjectId || "";
  const [premiseResponse, storySetupState] = await Promise.all([
    safeRead(() => projectApi.getCurrentProjectStoryPremise(), 8000),
    safeRead(() => projectApi.getCurrentStorySetupState({ projectId }), 8000),
  ]);
  const storySetupPrompt = storySetupState?.story_setup_prompt || storySetupState?.storySetupPrompt || {};
  const storySetupDraft =
    storySetupState?.story_setup_draft_bundle ||
    storySetupState?.storySetupDraftBundle ||
    {};
  return firstUserVisibleText(
    projectStoryPremiseText(premiseResponse),
    storySetupPrompt.safe_prompt_summary,
    storySetupPrompt.safePromptSummary,
    storySetupPrompt.safe_summary,
    storySetupPrompt.safeSummary,
    storySetupDraft.safe_summary,
    storySetupDraft.safeSummary,
  );
}

async function loadRolesSurface(refs = {}) {
  const [roles, characterDraft, generatedRoleDraft, pendingStateChanges] = await Promise.all([
    projectApi.getRoles({ includeArchived: false }),
    safeRead(() => projectApi.getCurrentCharacterDraft()),
    safeRead(() => projectApi.getGeneratedRoleDraft()),
    safeRead(() => projectApi.getPendingRoleStateChanges()),
  ]);
  const requestedTier = normalizeRoleTier(refs.roleTier);
  const generatedTier = normalizeRoleTier(
    generatedRoleDraft?.draft?.target_tier ||
      generatedRoleDraft?.draft?.targetTier ||
      generatedRoleDraft?.draft?.character?.tier ||
      generatedRoleDraft?.draft?.role?.tier ||
      generatedRoleDraft?.draft?.complexity_profile?.tier ||
      generatedRoleDraft?.draft?.complexityProfile?.tier ||
      generatedRoleDraft?.target_tier ||
      generatedRoleDraft?.targetTier ||
      generatedRoleDraft?.role?.tier ||
      generatedRoleDraft?.complexity_profile?.tier ||
      generatedRoleDraft?.complexityProfile?.tier,
  );
  return compactObject({
    roles,
    character_draft: characterDraft,
    generated_role_draft: generatedRoleDraft,
    pending_state_changes: pendingStateChanges,
    roleTier: requestedTier || generatedTier || "A",
  });
}

function normalizeRoleTier(value, fallback = "") {
  const tier = String(value || fallback || "").trim().toUpperCase();
  return ["A", "B", "C", "D"].includes(tier) ? tier : "";
}

function positiveInt(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function usableFormText(value) {
  const text = String(value || "").trim();
  if (!text || text === "暂无此项数据" || text === "正在读取项目数据" || text === "待后端接入") {
    return "";
  }
  return text;
}

function safeList(value) {
  return Array.isArray(value) ? value : [];
}

function chapterCountFromFrameworkState(value) {
  if (!value || typeof value !== "object") {
    return 0;
  }
  const direct = positiveInt(value.chapter_count || value.chapterCount);
  if (direct) {
    return direct;
  }
  const assignments = safeList(
    value.chapter_macro_assignments ||
    value.chapterMacroAssignments ||
    value.assignments,
  );
  return assignments.reduce((max, item) => Math.max(max, positiveInt(item?.chapter_index || item?.chapterIndex)), 0);
}

async function resolveChapterPlanGenerationScope(refs, form) {
  const requestedChapterCount = positiveInt(form.chapterCount, 0);
  const requestedChapterIndex = positiveInt(refs.chapterIndex, 0) || 1;
  const [workbench, currentPlan, storyProgress] = await Promise.all([
    safeRead(() => projectApi.getFrameworkWorkbench()),
    safeRead(() => projectApi.getCurrentChapterPlan()),
    safeRead(() => projectApi.getStoryProgressCurrent()),
  ]);
  const progress = storyProgress?.story_progress || storyProgress?.storyProgress || storyProgress || {};
  const activeChapterIndex = positiveInt(
    progress.current_chapter_index || progress.currentChapterIndex,
    0,
  );
  const workbenchChapterCount = chapterCountFromFrameworkState(workbench);
  const planChapterCount = chapterCountFromFrameworkState(
    currentPlan?.chapter_plan ||
    currentPlan?.chapterPlan ||
    currentPlan?.draft ||
    currentPlan,
  );
  const mappedChapterCount = workbenchChapterCount || planChapterCount;
  const chapterCount = mappedChapterCount
    ? Math.min(requestedChapterCount || mappedChapterCount, mappedChapterCount)
    : requestedChapterCount;
  const safeChapterCount = chapterCount || 5;
  const chapterIndex = Math.min(Math.max(activeChapterIndex || requestedChapterIndex, 1), safeChapterCount);
  return { chapterCount: safeChapterCount, chapterIndex };
}

async function resolveActiveChapterIndex(refs, form = {}) {
  const storyProgress = await safeRead(() => projectApi.getStoryProgressCurrent());
  const progress = storyProgress?.story_progress || storyProgress?.storyProgress || storyProgress || {};
  return (
    positiveInt(progress.current_chapter_index || progress.currentChapterIndex, 0) ||
    positiveInt(form.chapterIndex, 0) ||
    positiveInt(refs.chapterIndex, 0) ||
    1
  );
}

async function resolveActiveChapterArchiveTarget(refs, form = {}) {
  const storyProgress = await safeRead(() => projectApi.getStoryProgressCurrent());
  const progress = storyProgress?.story_progress || storyProgress?.storyProgress || storyProgress || {};
  const chapterId = preferRuntimeChapterId(
    progress.current_chapter_id || progress.currentChapterId || form.chapterId || refs.chapterId,
    refs.chapterId,
  );
  const chapterIndex =
    positiveInt(progress.current_chapter_index || progress.currentChapterIndex, 0) ||
    positiveInt(form.chapterIndex, 0) ||
    positiveInt(refs.chapterIndex, 0) ||
    null;
  return { chapterId: chapterId || null, chapterIndex };
}

async function ensureCurrentChapterFramework(refs, chapterIndex) {
  try {
    const existing = await projectApi.getCurrentChapterFrameworkBuild(null, chapterIndex);
    const existingFramework = existing?.chapter_framework || existing?.chapterFramework || {};
    if (existingFramework?.chapter_framework_id || existingFramework?.chapterFrameworkId) {
      return existing;
    }
  } catch {
    // Missing current framework is expected before the first chapter route build.
  }
  return projectApi.buildCurrentChapterFramework({
    chapterIndex: chapterIndex || refs.chapterIndex || 1,
  });
}

async function generateRoleForTier(form) {
  const targetTier = normalizeRoleTier(form.roleTier, "A") || "A";
  const userPrompt = form.characterPrompt || "";
  const roleHint = form.roleHint || "";
  const storyFunctionHint = form.storyFunctionHint || "";
  if (targetTier === "A") {
    return projectApi.generateCharacter(userPrompt, roleHint, storyFunctionHint);
  }
  return projectApi.generateRoleDraft({
    userPrompt,
    targetTier,
    roleHint,
    storyFunctionHint,
  });
}

async function confirmGeneratedRoleAndRefresh(refs, form) {
  const targetTier = normalizeRoleTier(form.roleTier, refs.roleTier) || "A";
  const confirmation = targetTier === "A"
    ? await projectApi.confirmCharacter(defaultPayload.userInput)
    : await projectApi.confirmGeneratedRoleDraft(defaultPayload.userInput);
  const roles = await safeRead(() => projectApi.getRoles({ includeArchived: false }));
  const pendingStateChanges = await safeRead(() => projectApi.getPendingRoleStateChanges());
  return compactObject({
    confirmation,
    roles,
    pending_state_changes: pendingStateChanges,
  });
}

async function loadSceneSurface(refs = {}, options = {}) {
  const requestedChapterId = preferRuntimeChapterId(refs.chapterId) || null;
  const requestedSceneId = String(refs.sceneId || "").trim();
  const requestedSceneIndex = Number(refs.sceneIndex || 0) || null;
  const [storyProgress, chapterPlan] = await Promise.all([
    safeRead(() => projectApi.getStoryProgressCurrent()),
    safeRead(() => projectApi.getCurrentChapterPlan()),
  ]);
  const authoritativeChapterId = preferRuntimeChapterId(
    storyProgress?.current_chapter_id || storyProgress?.currentChapterId,
    requestedChapterId || "",
  );
  const sceneProgress = await safeRead(() => projectApi.getSceneProgress(authoritativeChapterId || null));
  const resolvedChapterId =
    sceneProgress?.chapter_id ||
    sceneProgress?.chapterId ||
    storyProgress?.current_chapter_id ||
    storyProgress?.currentChapterId ||
    requestedChapterId ||
    "";
  const progressNextSceneIndex = Number(sceneProgress?.next_scene_index || sceneProgress?.nextSceneIndex || 0) || 0;
  const progressScenes = (sceneProgress?.scenes || sceneProgress?.items || []).filter(
    (item) => item && typeof item === "object",
  );
  const requestedSceneRecord = requestedSceneId
    ? progressScenes.find((item) => pickId(item, ["scene_id", "sceneId", "id"]) === requestedSceneId) || null
    : null;
  const requestedSceneIndexById = Number(
    requestedSceneRecord?.scene_index || requestedSceneRecord?.sceneIndex || 0,
  ) || null;
  const resolvedSceneIndex = Number(
    options.preferRequestedSceneIndex
      ? (requestedSceneIndexById || requestedSceneIndex || progressNextSceneIndex || 1)
      : (progressNextSceneIndex || requestedSceneIndex || 1),
  ) || 1;
  const currentScene = await safeRead(() => projectApi.getCurrentScene(resolvedChapterId || null, resolvedSceneIndex));
  const currentSceneRecord = sceneRecordFromCurrentScenePayload(currentScene);
  const currentSceneMatches = sameChapterScene(currentSceneRecord, resolvedChapterId, resolvedSceneIndex);
  const resolvedSceneId =
    currentSceneMatches
      ? pickId(currentSceneRecord, ["scene_id", "sceneId", "id"])
      : "";
  const gateReadiness = resolvedSceneId
    ? await safeRead(() => projectApi.getSceneGateReadiness(resolvedSceneId))
    : null;
  const participantSelection = await safeRead(() =>
    projectApi.getCurrentSceneParticipantSelection(resolvedChapterId || null, resolvedSceneIndex),
  );
  return compactObject({
    selected_scene: currentSceneMatches ? currentSceneRecord : null,
    current_scene: currentSceneMatches ? currentScene : null,
    scene_progress: sceneProgress,
    story_progress: storyProgress,
    gate_readiness: gateReadiness,
    participant_selection: participantSelection,
    chapter_plan: chapterPlan,
    resolved_chapter_id: resolvedChapterId,
    resolved_scene_index: resolvedSceneIndex,
  });
}

async function resolveSceneParticipantCandidateId(refs = {}) {
  if (refs.sceneParticipantCandidateId) {
    return refs.sceneParticipantCandidateId;
  }
  const selection = await safeRead(() =>
    projectApi.getCurrentSceneParticipantSelection(preferRuntimeChapterId(refs.chapterId) || null, Number(refs.sceneIndex || 1)),
  );
  const candidateIdKeys = [
    "creation_candidate_id",
    "creationCandidateId",
    "candidate_id",
    "candidateId",
    "scene_participant_candidate_id",
    "id",
  ];
  const pendingCandidate =
    (selection?.creation_candidates || selection?.candidates || selection?.items || []).find((candidate) => {
      const status = String(candidate?.status || "").toLowerCase();
      return status === "pending" || status === "requires_user_confirmation" || status === "needs_user_confirmation";
    }) || null;
  const candidateId =
    pickId(pendingCandidate, candidateIdKeys) ||
    firstIdFromList(selection, ["pending_creation_candidate_ids", "candidate_ids"], candidateIdKeys);
  if (candidateId) {
    return candidateId;
  }
  return requireRef(refs, "sceneParticipantCandidateId", "参与角色候选 ID");
}

async function confirmPendingSceneParticipantCandidates(refs = {}) {
  const chapterId = preferRuntimeChapterId(refs.chapterId) || null;
  const sceneIndex = Number(refs.sceneIndex || 1);
  const selection = await safeRead(() =>
    projectApi.getCurrentSceneParticipantSelection(chapterId, sceneIndex),
  );
  const candidateIdKeys = [
    "creation_candidate_id",
    "creationCandidateId",
    "candidate_id",
    "candidateId",
    "scene_participant_candidate_id",
    "id",
  ];
  const candidates =
    selection?.creation_candidates ||
    selection?.creationCandidates ||
    selection?.candidates ||
    selection?.items ||
    [];
  const pendingCandidateIds = Array.from(
    new Set(
      candidates
        .filter((candidate) => {
          const status = String(candidate?.status || "").toLowerCase();
          return status === "pending" ||
            status === "requires_user_confirmation" ||
            status === "needs_user_confirmation";
        })
        .map((candidate) => pickId(candidate, candidateIdKeys))
        .filter(Boolean),
    ),
  );
  if (!pendingCandidateIds.length) {
    pendingCandidateIds.push(await resolveSceneParticipantCandidateId(refs));
  }
  const confirmations = [];
  let nextRefs = refs;
  for (const candidateId of pendingCandidateIds) {
    const confirmation = await projectApi.confirmSceneParticipantCreationCandidate(candidateId);
    confirmations.push(confirmation);
    nextRefs = updateRefsFromResult(nextRefs, confirmation);
  }
  return { confirmations, nextRefs };
}

function sceneParticipantSelectionNeedsConfirmation(selection = {}) {
  const candidates = selection?.creation_candidates || selection?.creationCandidates || selection?.candidates || selection?.items || [];
  const hasPendingCandidate = candidates.some((candidate) => {
    const status = String(candidate?.status || "").toLowerCase();
    return status === "pending" || status === "requires_user_confirmation" || status === "needs_user_confirmation";
  });
  return Boolean(
    hasPendingCandidate ||
      selection?.selection?.requires_user_confirmation ||
      selection?.selection?.requiresUserConfirmation ||
      selection?.requires_user_confirmation ||
      selection?.requiresUserConfirmation,
  );
}

async function loadPendingSceneParticipantGate(refs = {}, sceneIndexOverride = null) {
  const chapterId = preferRuntimeChapterId(refs.chapterId) || null;
  const sceneIndex = Number(sceneIndexOverride || refs.sceneIndex || 1);
  const sceneSurface = await loadSceneSurface(
    { ...refs, chapterId, sceneIndex },
    { preferRequestedSceneIndex: true },
  );
  const resolvedChapterId = sceneSurface.resolved_chapter_id || chapterId;
  const resolvedSceneIndex = Number(sceneSurface.resolved_scene_index || sceneIndex);
  const selection =
    sceneSurface.participant_selection ||
    await safeRead(() =>
      projectApi.getCurrentSceneParticipantSelection(resolvedChapterId, resolvedSceneIndex),
    );
  return compactObject({
    ...sceneSurface,
    participant_selection: selection,
    generation_blocked: sceneParticipantSelectionNeedsConfirmation(selection),
    blocking_reason: sceneParticipantSelectionNeedsConfirmation(selection)
      ? "scene_participation_confirmation_required"
      : "",
    resolved_chapter_id: sceneSurface.resolved_chapter_id || chapterId,
    resolved_scene_index: sceneSurface.resolved_scene_index || sceneIndex,
  });
}

function isSceneParticipantConfirmationError(error) {
  if (error?.status !== 409) {
    return false;
  }
  return /SCENE_PARTICIPATION_CONFIRMATION_REQUIRED|review_scene_participant_candidates|scene participation.*user confirmation|participation.*confirmation required/i.test(
    serializedErrorText(error),
  );
}

async function generateFirstSceneWithPrerequisites(refs = {}, form = {}) {
  const storyProgress = await safeRead(() => projectApi.getStoryProgressCurrent());
  const chapterId = preferRuntimeChapterId(
    storyProgress?.current_chapter_id || storyProgress?.currentChapterId,
    refs.chapterId,
  ) || null;
  // The first-scene endpoint has a fixed contract. Browser refs can retain the
  // previous project's scene cursor after project switches or session resume.
  const sceneIndex = 1;
  const progress = await safeRead(() => projectApi.getSceneProgress(chapterId));
  const authoritativeNextSceneIndex = Number(progress?.next_scene_index || progress?.nextSceneIndex || 1) || 1;
  if (authoritativeNextSceneIndex !== 1) {
    return loadSceneSurface(
      { ...refs, chapterId, sceneIndex: authoritativeNextSceneIndex },
      { preferRequestedSceneIndex: true },
    );
  }
  const participantGate = await loadPendingSceneParticipantGate(refs, sceneIndex);
  if (participantGate.generation_blocked) {
    return participantGate;
  }
  try {
    return await projectApi.generateFirstScene(chapterId, sceneIndex);
  } catch (error) {
    if (!isSceneParticipantConfirmationError(error)) {
      throw error;
    }
    return loadPendingSceneParticipantGate({ ...refs, chapterId }, sceneIndex);
  }
}

async function generateNextSceneWithPrerequisites(refs = {}) {
  const chapterId = preferRuntimeChapterId(refs.chapterId) || null;
  const participantGate = await loadPendingSceneParticipantGate(refs);
  if (participantGate.generation_blocked) {
    return participantGate;
  }
  try {
    return await projectApi.generateNextScene(chapterId, false, null);
  } catch (error) {
    if (!isSceneParticipantConfirmationError(error)) {
      throw error;
    }
    return loadPendingSceneParticipantGate(refs);
  }
}

function serializedErrorText(error) {
  return [
    error?.message,
    typeof error?.detail === "object" ? JSON.stringify(error.detail) : error?.detail,
    typeof error?.body === "object" ? JSON.stringify(error.body) : error?.body,
  ]
    .filter(Boolean)
    .join(" ");
}

function continuityIssueIdsFromError(error) {
  const text = serializedErrorText(error);
  return Array.from(new Set(text.match(/continuity_[a-z0-9_]+/gi) || []));
}

function isAutoAcceptableContinuityCommitError(error) {
  if (Number(error?.status || 0) !== 409) {
    return false;
  }
  return /scene_continuity_not_passed|scene_objective_repeated|continuity_scene_objective_repeated/i.test(serializedErrorText(error));
}

function isRuntimeRefreshConsistencyCommitError(error) {
  if (Number(error?.status || 0) !== 409) {
    return false;
  }
  return /SCENE_RUNTIME_REFRESH_NOT_READY|场景文本与已确认的记忆提取存在直接矛盾|scene runtime refresh state is not ready/i.test(
    serializedErrorText(error),
  );
}

function runtimeRefreshRepairHint(error) {
  const detail = serializedErrorText(error).replace(/\s+/g, " ").trim().slice(0, 1200);
  return [
    "修复当前场景的内部事实一致性。",
    "摘要、正文、角色行为、事件归属与结构化记忆提取必须描述同一组事实，不得让不同角色执行同一个互斥动作，也不得让记忆损失的对象或内容前后变化。",
    "保留当前场景目标以及已经确认的世界、角色和剧情事实，完整重写当前场景，并重新生成与新正文一致的记忆提取。",
    detail ? `提交门反馈：${detail}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function acceptedRuntimeIssueIdsFromCommitError(error) {
  const issueIds = continuityIssueIdsFromError(error);
  return issueIds;
}

async function commitSceneAndRefresh(refs) {
  const beforeCommitSurface = await loadSceneSurface(refs, { preferRequestedSceneIndex: true });
  const currentScene = sceneRecordFromSurface(beforeCommitSurface);
  const expectedChapterId = preferRuntimeChapterId(refs.chapterId) || currentScene.chapter_id || currentScene.chapterId;
  const expectedSceneId = String(refs.sceneId || "").trim();
  const currentSceneId = pickId(currentScene, ["scene_id", "sceneId", "id"]);
  const sceneId =
    currentSceneId ||
    requireRef(refs, "sceneId", "场景 ID");
  if (
    !sameChapterScene(currentScene, expectedChapterId) ||
    (expectedSceneId && currentSceneId && currentSceneId !== expectedSceneId)
  ) {
    const error = new Error("当前场景上下文与当前章节不一致，请重新进入场景写作页后再确认。");
    error.code = "SCENE_CONTEXT_MISMATCH";
    throw error;
  }
  const gateReadiness = await safeRead(() => projectApi.getSceneGateReadiness(sceneId));
  let autoAcceptedContinuityIssueIds = [];
  let commit;
  try {
    commit = await projectApi.commitScene(
      sceneId,
      "confirmed",
      defaultPayload.userInput,
      refs.sceneRevisionId || null,
      [],
    );
  } catch (error) {
    if (isRuntimeRefreshConsistencyCommitError(error)) {
      const currentSceneIndex = Number(
        currentScene.scene_index || currentScene.sceneIndex || refs.sceneIndex || 1,
      );
      const regenerated = await projectApi.regenerateFirstScene(
        runtimeRefreshRepairHint(error),
        sceneId,
        expectedChapterId,
        currentSceneIndex,
      );
      const repairedRefs = updateRefsFromResult(refs, regenerated);
      const repairedSurface = await loadSceneSurface(repairedRefs, {
        preferRequestedSceneIndex: true,
      });
      const repairedScene =
        regenerated?.scene ||
        repairedSurface?.current_scene?.scene ||
        repairedSurface?.currentScene?.scene ||
        null;
      return compactObject({
        commit_auto_repair_required: true,
        commit_auto_repair_reason: error?.message || "提交前一致性检查未通过。",
        commit_auto_repair: regenerated,
        current_scene: repairedScene
          ? {
              scene: repairedScene,
              progress:
                regenerated?.progress ||
                repairedSurface?.scene_progress ||
                repairedSurface?.sceneProgress ||
                null,
            }
          : repairedSurface.current_scene,
        scene_progress:
          regenerated?.progress ||
          repairedSurface?.scene_progress ||
          repairedSurface?.sceneProgress ||
          null,
        story_progress: repairedSurface.story_progress,
        participant_selection: repairedSurface.participant_selection,
        chapter_plan: repairedSurface.chapter_plan,
        resolved_chapter_id: repairedSurface.resolved_chapter_id || expectedChapterId,
        resolved_scene_index:
          repairedSurface.resolved_scene_index || currentSceneIndex,
        before_commit_surface: beforeCommitSurface,
        refreshed_scene_surface: repairedSurface,
      });
    }
    if (!isAutoAcceptableContinuityCommitError(error)) {
      throw error;
    }
    autoAcceptedContinuityIssueIds = acceptedRuntimeIssueIdsFromCommitError(error);
    if (!autoAcceptedContinuityIssueIds.length) {
      throw error;
    }
    commit = await projectApi.commitScene(
      sceneId,
      "confirmed",
      `${defaultPayload.userInput} 已自动接受连续性提示：${autoAcceptedContinuityIssueIds.join(", ")}。`,
      refs.sceneRevisionId || null,
      autoAcceptedContinuityIssueIds,
    );
  }
  const sceneSurface = await loadSceneSurface(updateRefsFromResult(refs, commit), { preferRequestedSceneIndex: true });
  const committedScene = commit?.scene || commit?.current_scene?.scene || commit?.currentScene?.scene || null;
  const committedProgress = commit?.progress || commit?.scene_progress || commit?.sceneProgress || sceneSurface.scene_progress || null;
  return compactObject({
    commit,
    auto_accepted_continuity_issue_ids: autoAcceptedContinuityIssueIds,
    current_scene: committedScene
      ? {
          scene: committedScene,
          progress: committedProgress,
        }
      : sceneSurface.current_scene,
    scene_progress: committedProgress,
    story_progress: sceneSurface.story_progress,
    gate_readiness: gateReadiness,
    participant_selection: sceneSurface.participant_selection,
    chapter_plan: sceneSurface.chapter_plan,
    resolved_chapter_id: sceneSurface.resolved_chapter_id,
    resolved_scene_index: sceneSurface.resolved_scene_index,
    before_commit_surface: beforeCommitSurface,
    refreshed_scene_surface: sceneSurface,
  });
}

async function continueToNextChapter(refs, form) {
  const { archive_preview: archivePreview, archive } = await archiveCurrentChapter(refs, form);
  const nextPreview = await projectApi.previewNextChapter();
  const preparation = await projectApi.prepareNextChapter({
    latestUserIntentSummary: form.answerText || defaultPayload.safeUserNote,
    storyGoal: form.storyGoal || "",
    sceneCountProposal: Number(form.sceneCount || 0) || null,
    acknowledgeProvisionalArchive: true,
  });
  const preparationId = pickId(preparation, ["preparation_id", "preparationId", "id"]);
  const confirmation = await projectApi.confirmNextChapter({
    preparationId,
    sceneCount: Number(form.sceneCount || 0) || null,
    confirmChapterPlan: true,
  });

  return compactObject({
    archive_preview: archivePreview,
    archive,
    next_chapter_preview: nextPreview,
    preparation,
    preparation_id: preparationId,
    confirmation,
  });
}

async function archiveCurrentChapter(refs, form) {
  const target = await resolveActiveChapterArchiveTarget(refs, form);
  const archivePreview = await projectApi.previewChapterArchive(target.chapterId, target.chapterIndex);
  const archive = await projectApi.archiveChapter({
    chapterId: target.chapterId,
    chapterIndex: target.chapterIndex,
    archiveMode: "stable",
    userInput: form.answerText || defaultPayload.userInput,
    acceptWarnings: true,
  });
  const [storyProgressEnvelope, chapterPlan] = await Promise.all([
    safeRead(() => projectApi.getStoryProgressCurrent()),
    safeRead(() => projectApi.getCurrentChapterPlan()),
  ]);
  const storyProgress =
    storyProgressEnvelope?.story_progress ||
    storyProgressEnvelope?.storyProgress ||
    storyProgressEnvelope ||
    null;
  return compactObject({
    archive_preview: archivePreview,
    archive,
    story_progress: storyProgress,
    chapter_plan: chapterPlan,
  });
}

async function evaluateFinalReadiness() {
  const readiness = await projectApi.evaluateFinalStoryPackageReadiness({
    forceRefresh: true,
    persist: true,
    safeUserNote: defaultPayload.safeUserNote,
  });
  const gateId = pickFinalReadinessGateId(readiness);
  const issues = gateId ? await safeRead(() => projectApi.getFinalStoryPackageReadinessIssues(gateId)) : null;
  return compactObject({
    readiness,
    readiness_gate_id: gateId,
    issues,
  });
}

async function resolveFinalReadinessGateId(refs) {
  if (refs.finalReadinessGateId) {
    return refs.finalReadinessGateId;
  }
  const readiness = await safeRead(() => projectApi.getFinalStoryPackageReadiness());
  return (
    pickFinalReadinessGateId(readiness) ||
    readiness?.latest_readiness_gate_id ||
    readiness?.latestReadinessGateId ||
    ""
  );
}

async function exportFinalStoryPackageAndLoadPreview(refs, form) {
  const readinessGateId = await resolveFinalReadinessGateId(refs);
  const exportRun = await projectApi.exportFinalStoryPackage({
    readinessGateId,
    exportFormat: "json_snapshot",
    safeUserNote: defaultPayload.safeUserNote,
  });
  const exportRunRecord = exportRun?.export_run || exportRun?.exportRun || exportRun;
  const snapshotRecord = exportRun?.snapshot || exportRun?.snapshot_record || exportRun?.snapshotRecord || {};
  const exportRunId =
    pickId(exportRun, ["export_run_id", "exportRunId", "run_id", "id"]) ||
    pickId(exportRunRecord, ["export_run_id", "exportRunId", "run_id", "id"]);
  const snapshotId =
    pickId(exportRun, ["snapshot_id", "snapshotId"]) ||
    pickId(snapshotRecord, ["snapshot_id", "snapshotId", "id"]) ||
    pickId(exportRunRecord, ["snapshot_id", "snapshotId"]);
  const [runDetail, snapshot, sections] = await Promise.all([
    exportRunId ? safeRead(() => projectApi.getFinalStoryPackageExportRun(exportRunId)) : Promise.resolve(null),
    snapshotId ? safeRead(() => projectApi.getFinalStoryPackageSnapshot(snapshotId)) : Promise.resolve(null),
    snapshotId ? safeRead(() => projectApi.getFinalStoryPackageSnapshotSections(snapshotId)) : Promise.resolve(null),
  ]);
  return compactObject({
    export_run: exportRun,
    export_run_id: exportRunId,
    snapshot_id: snapshotId,
    export_run_detail: runDetail,
    snapshot,
    sections,
  });
}

async function assembleFinalStoryPackage(refs, form) {
  const readinessResult = await evaluateFinalReadiness();
  const readinessGateId =
    readinessResult.readiness_gate_id ||
    pickFinalReadinessGateId(readinessResult.readiness) ||
    refs.finalReadinessGateId ||
    "";
  const exportResult = await exportFinalStoryPackageAndLoadPreview(
    {
      ...refs,
      finalReadinessGateId: readinessGateId,
    },
    form,
  );
  return compactObject({
    ...readinessResult,
    ...exportResult,
  });
}

async function resolveFinalSnapshotId(refs) {
  if (refs.finalSnapshotId) {
    return refs.finalSnapshotId;
  }
  const exportRuns = await safeRead(() => projectApi.getFinalStoryPackageExportRuns());
  const latestExportRun = firstItem(exportRuns, ["export_runs", "exportRuns", "items", "records"]) || {};
  return pickId(latestExportRun, ["snapshot_id", "snapshotId", "id"]);
}

async function loadFinalExportsWithSnapshot(refs) {
  const exportRuns = await projectApi.getFinalStoryPackageExportRuns();
  const latestExportRun = firstItem(exportRuns, ["export_runs", "exportRuns", "items", "records"]) || {};
  const snapshotId =
    refs.finalSnapshotId ||
    pickId(latestExportRun, ["snapshot_id", "snapshotId"]) ||
    "";
  const [snapshot, sections, productViews] = await Promise.all([
    snapshotId ? safeRead(() => projectApi.getFinalStoryPackageSnapshot(snapshotId)) : Promise.resolve(null),
    snapshotId ? safeRead(() => projectApi.getFinalStoryPackageSnapshotSections(snapshotId)) : Promise.resolve(null),
    safeRead(() => projectApi.getFinalStoryPackageProductViews(stateParams(refs))),
  ]);
  return compactObject({
    export_runs: exportRuns,
    latest_export_run: latestExportRun,
    snapshot_id: snapshotId,
    snapshot,
    sections,
    product_views: productViews,
  });
}

async function loadFinalViewer(refs) {
  const snapshotId = await resolveFinalSnapshotId(refs);
  if (!snapshotId) {
    return requireRef(refs, "finalSnapshotId", "最终输出快照 ID");
  }
  const [snapshot, sections, viewerState] = await Promise.all([
    projectApi.getFinalStoryPackageSnapshot(snapshotId),
    projectApi.getFinalStoryPackageSnapshotSections(snapshotId),
    projectApi.createFinalStoryPackageViewerState({ snapshotId, selectedSectionType: "complete_story_text" }),
  ]);
  return compactObject({
    snapshot_id: snapshotId,
    snapshot,
    sections,
    viewer_state: viewerState,
  });
}

async function loadFinalReadinessIssues(refs) {
  const readiness = await projectApi.getFinalStoryPackageReadiness();
  const gateId =
    refs.finalReadinessGateId ||
    pickFinalReadinessGateId(readiness) ||
    readiness?.latest_readiness_gate_id ||
    readiness?.latestReadinessGateId ||
    "";
  const issues = gateId ? await safeRead(() => projectApi.getFinalStoryPackageReadinessIssues(gateId)) : null;
  return compactObject({
    readiness,
    readiness_gate_id: gateId,
    issues,
  });
}

async function upsertModelProviderProfile(refs, form) {
  const profileId = firstNonEmptyText(form.profileId, refs.modelProfileId);
  if (profileId) {
    return projectApi.patchModelProviderProfile(profileId, {
      displayName: form.modelProfileName || form.displayName || undefined,
      baseUrl: form.baseUrl || undefined,
      modelName: form.modelName || undefined,
      apiKeyRef: form.apiKeyRef || undefined,
      enabled: form.enabledToggle,
      safeUserNote: defaultPayload.safeUserNote,
    });
  }

  return projectApi.createModelProviderProfile({
    providerType: form.providerType || "deepseek",
    displayName: form.modelProfileName || form.displayName || "Model Provider",
    baseUrl: form.baseUrl || "",
    modelName: form.modelName || "",
    apiKeyRef: form.apiKeyRef || "",
    enabled: form.enabledToggle ?? true,
  });
}

function isChapterPlanAlreadyConfirmedError(error) {
  return Number(error?.status || 0) === 409 && /CHAPTER_PLAN_ALREADY_CONFIRMED|already been confirmed/i.test(
    serializedErrorText(error),
  );
}

async function reviseRoleForTier(refs, form) {
  const [mainDraft, generatedDraft] = await Promise.all([
    safeRead(() => projectApi.getCurrentCharacterDraft()),
    safeRead(() => projectApi.getGeneratedRoleDraft()),
  ]);
  const mainCharacter = mainDraft?.character || mainDraft?.role || {};
  const generatedCharacter = generatedDraft?.character || generatedDraft?.role || {};
  const targetTier = normalizeRoleTier(
    form.roleTier || mainCharacter.tier || generatedCharacter.tier,
    refs.roleTier || "A",
  ) || "A";
  const revisionPrompt = form.characterRevision || form.characterPrompt || "请根据用户补充修订角色草案。";
  if (targetTier === "A") {
    return projectApi.reviseCharacter(revisionPrompt);
  }
  return projectApi.generateRoleDraft({
    userPrompt: revisionPrompt,
    targetTier,
    roleHint: form.roleHint || "",
    storyFunctionHint: form.storyFunctionHint || "",
  });
}

async function loadModelSettingsSurface(actionResult = null) {
  return compactObject({
    action_result: actionResult,
    workbench: await projectApi.getModelSettingsWorkbench(),
    providers: await safeRead(() => projectApi.getModelSettingsProviders()),
    profiles: await safeRead(() => projectApi.getModelProviderProfiles()),
    active_selection: await safeRead(() => projectApi.getActiveModelSelection()),
    secret_policy: await safeRead(() => projectApi.getModelSecretPolicy()),
  });
}

async function loadAnalyzeStoriesSurface(refs = {}, actionResult = null) {
  const importsResponse = await projectApi.getAnalyzeStoriesImports();
  const imports = importsResponse?.imports || [];
  const actionImportId = pickId(actionResult, ["import_id", "importId"]);
  const importId =
    actionImportId ||
    refs.analyzeImportId ||
    pickId(imports[0], ["import_id", "importId"]);
  const selectedImport = importId
    ? await safeRead(() => projectApi.getAnalyzeStoriesImport(importId))
    : null;
  const candidatesResponse = await safeRead(() => projectApi.getAnalyzeStoriesFrameworkCandidates());
  const candidates = candidatesResponse?.candidates || candidatesResponse?.framework_candidates || [];
  const selectedCandidate =
    candidates.find((candidate) => {
      const candidateId = pickId(candidate, ["framework_candidate_id", "frameworkCandidateId", "candidate_id", "candidateId"]);
      const candidateImportId = pickId(candidate, ["import_id", "importId", "source_import_id", "sourceImportId"]);
      return (
        (refs.analyzeCandidateId && candidateId === refs.analyzeCandidateId) ||
        (importId && candidateImportId === importId)
      );
    }) ||
    candidates[0] ||
    null;
  return compactObject({
    action_result: actionResult,
    imports: importsResponse,
    selected_import: selectedImport,
    framework_candidates: candidatesResponse,
    selected_candidate: selectedCandidate,
  });
}

function importedEditSessionFromResult(result) {
  return (
    result?.edit_session ||
    result?.editSession ||
    result?.selected_imported_edit_session?.edit_session ||
    result?.selectedImportedEditSession?.editSession ||
    null
  );
}

async function loadImportedFrameworkSessionSurface(
  refs = {},
  actionResult = null,
  preferredEditSessionId = "",
) {
  const sessionsResponse = await projectApi.getImportedFrameworkEditSessions();
  const sessions = sessionsResponse?.edit_sessions || sessionsResponse?.editSessions || [];
  const actionSession = importedEditSessionFromResult(actionResult);
  const actionSessionId = pickId(actionSession, ["edit_session_id", "editSessionId"]);
  const selectedSessionId =
    preferredEditSessionId ||
    actionSessionId ||
    refs.importedEditSessionId ||
    pickId(
      sessions.find((session) => {
        const candidateId = pickId(session, ["candidate_id", "candidateId"]);
        return Boolean(refs.analyzeCandidateId && candidateId === refs.analyzeCandidateId);
      }),
      ["edit_session_id", "editSessionId"],
    ) ||
    pickId(sessions[0], ["edit_session_id", "editSessionId"]);
  const selectedSession = selectedSessionId
    ? await projectApi.getImportedFrameworkEditSession(selectedSessionId)
    : null;
  return compactObject({
    action_result: actionResult,
    imported_edit_sessions: sessionsResponse,
    selected_imported_edit_session: selectedSession,
    selected_edit_session_id: selectedSessionId,
  });
}

function sameStringList(left, right) {
  const normalize = (items) => [...new Set((items || []).map((item) => String(item || "").trim()).filter(Boolean))].sort();
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right));
}

async function saveImportedFrameworkSession(refs, form) {
  const editSessionId = requireRef(
    {
      ...refs,
      importedEditSessionId: form.importedEditSessionId || refs.importedEditSessionId,
    },
    "importedEditSessionId",
    "导入编辑会话 ID",
  );
  let currentResult = await projectApi.getImportedFrameworkEditSession(editSessionId);
  let session = importedEditSessionFromResult(currentResult) || {};
  const activationMode = String(form.activationMode || "").trim();
  if (activationMode && activationMode !== String(session.activation_mode || session.activationMode || "")) {
    currentResult = await projectApi.patchImportedFrameworkEditSession(editSessionId, {
      operation: "set_activation_mode",
      activationMode,
      userInput: "用户在导入编辑会话中选择激活方式。",
    });
    session = importedEditSessionFromResult(currentResult) || session;
  }

  const componentId = String(form.importedComponentId || "").trim();
  const components =
    session.working_framework_package?.macro_framework?.components ||
    session.workingFrameworkPackage?.macroFramework?.components ||
    [];
  const selectedComponent = components.find((item) => {
    return String(item.component_id || item.componentId || "") === componentId;
  });
  if (selectedComponent) {
    const nextLabel = String(form.componentLabel || "").trim();
    const nextInstruction = String(form.componentInstruction || "").trim();
    const nextOrder = Number(form.componentOrder || 0);
    const changed =
      nextLabel !== String(selectedComponent.label || "") ||
      nextInstruction !== String(selectedComponent.instruction || "") ||
      (Number.isFinite(nextOrder) && nextOrder > 0 && nextOrder !== Number(selectedComponent.order || 0));
    if (changed) {
      currentResult = await projectApi.patchImportedFrameworkEditSession(editSessionId, {
        operation: "update_macro_component",
        componentId,
        patch: {
          label: nextLabel,
          instruction: nextInstruction,
          order: nextOrder,
        },
        userInput: "用户在导入编辑会话中修改宏观 Framework 组件。",
      });
      session = importedEditSessionFromResult(currentResult) || session;
    }
  }

  const chapterIndex = Number(form.importedChapterIndex || 0);
  const linkedMacroComponentIds = String(form.linkedMacroComponentIds || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const assignments =
    session.working_framework_package?.chapter_macro_assignments ||
    session.workingFrameworkPackage?.chapterMacroAssignments ||
    [];
  const selectedAssignment = assignments.find((item) => {
    return Number(item.chapter_index || item.chapterIndex || 0) === chapterIndex;
  });
  const existingLinkedIds =
    selectedAssignment?.linked_macro_component_ids ||
    selectedAssignment?.linkedMacroComponentIds ||
    [];
  if (chapterIndex > 0 && linkedMacroComponentIds.length && !sameStringList(existingLinkedIds, linkedMacroComponentIds)) {
    currentResult = await projectApi.patchImportedFrameworkEditSession(editSessionId, {
      operation: "remap_chapter",
      chapterIndex,
      linkedMacroComponentIds,
      userInput: "用户在导入编辑会话中调整章节与宏观 Framework 组件的轻量映射。",
    });
  }
  return loadImportedFrameworkSessionSurface(refs, currentResult, editSessionId);
}

export async function runWorkspaceAction(actionId, context = {}) {
  const actionWorkspaceId = workspaceIdForAction(actionId);
  const form = context.form || {};
  const actionOnlyIds = new Set([
    "app.progress",
    "navigation.createProject",
    "project.createRequest",
    "projects.openSelected",
    "world.generate",
    "world.current",
    "world.revise",
    "world.confirm",
    "characters.generate",
    "characters.current",
    "characters.confirm",
    "characters.finishMainCast",
    "projects.refresh",
    "template.refresh",
    "framework.workbench",
    "framework.library",
    "framework.openImportedSession",
    "framework.selectImportedSession",
    "framework.saveImportedSession",
    "framework.validateImportedSession",
    "framework.buildActivationPlan",
    "analyze.refresh",
    "roles.refresh",
    "roles.contextPreview",
    "roles.pendingStateChanges",
    "chapter.currentFramework",
    "chapter.currentPlan",
    "scene.current",
    "scene.currentRevision",
    "scene.continuityCheck",
    "plugins.refresh",
    "plugins.artifacts",
    "plugins.safetyReport",
    "settings.workbench",
    "settings.activeModel",
    "settings.secretPolicy",
    "final.evaluate",
    "final.assemble",
    "final.refreshExports",
    "final.viewerState",
    "final.readiness",
    "final.download",
  ]);
  const shouldSkipPreHydrate = Boolean(context.skipPreHydrate) || actionOnlyIds.has(actionId) || actionId.startsWith("storySetup.");
  const shouldSkipShellState = Boolean(context.skipShellState);
  const preserveSceneSelection = Boolean(
    context.refs?.sceneSelectionPinned &&
      [
        "scene.openExisting",
        "scene.current",
        "scene.currentRevision",
        "scene.reviseConfirmed",
        "scene.confirmRevision",
        "scene.rejectRevision",
        "scene.continuityCheck",
        "scene.commit",
      ].includes(actionId),
  );
  const hydratedRefs = shouldSkipPreHydrate
    ? context.refs || {}
    : await hydrateWorkspaceRefs(context.refs || {}, {
        workspaceId: actionWorkspaceId,
        preserveSceneSelection,
      });
  const refs = mergeClientFormRefs(hydratedRefs, form);
  const live = context.apiMode === "live" || runtimeApiMode() === "live";

  if (!live) {
    const result = createDemoResult(actionId, refs);
    return {
      result,
      refs: updateRefsFromResult(refs, result),
      skipped: true,
      message: "演示模式：未调用后端，已模拟成功响应。",
    };
  }

  const actionResult = await callLiveAction(actionId, refs, form);
  const actionProjectId =
    actionId === "projects.openSelected"
      ? pickId(actionResult, ["project_id", "projectId"])
      : "";
  const actionBaseRefs = refsForActiveProject(refs, actionProjectId);
  const refsAfterAction = mergeClientFormRefs(updateRefsFromResult(actionBaseRefs, actionResult), form);
  if (shouldSkipPreHydrate) {
    return {
      result: compactObject({
        action_id: actionId,
        action_result: actionResult,
      }),
      refs: refsAfterAction,
      skipped: false,
      message: "后端接口调用成功。",
    };
  }
  const shellState = shouldSkipShellState
    ? {}
    : (await safeRead(() => loadShellState(refsAfterAction, workspaceIdForAction(actionId)), 12000)) || {};
  const result = compactObject({
    action_id: actionId,
    action_result: actionResult,
    ...shellState,
  });
  const refsAfterShell = updateRefsFromResult(refsAfterAction, result);
  const finalRefs = actionId.startsWith("scene.")
    ? updateRefsFromResult(refsAfterShell, actionResult)
    : refsAfterShell;

  return {
    result,
    refs: finalRefs,
    skipped: false,
    message:
      actionId === "scene.commit" && actionResult?.commit_auto_repair_required
        ? "提交前发现正文与结构化记忆不一致，系统已自动重生成当前幕。请复核新正文后再次确认。"
        : "后端接口调用成功。",
  };
}

async function callLiveAction(actionId, refs, form) {
  switch (actionId) {
    case "app.progress":
      return loadCurrentProjectOverview(refs);
    case "navigation.createProject":
      return compactObject({
        project_creation_modes: await safeRead(() => projectApi.getProjectCreationModes()),
        project_creation_demo_seeds: await safeRead(() => projectApi.getProjectCreationDemoSeeds()),
      });
    case "navigation.templateDemo":
      return loadWorkspaceNavigation(refs, "template_demo");
    case "navigation.framework":
      return loadWorkspaceNavigation(refs, "framework");
    case "navigation.analyzeStories":
      return loadWorkspaceNavigation(refs, "analyze_stories");
    case "navigation.storySetup":
      return loadWorkspaceNavigation(refs, "story_setup");
    case "navigation.worldCanvas":
      return loadWorkspaceNavigation(refs, "world_canvas");
    case "navigation.characters":
      return loadWorkspaceNavigation(refs, "characters");
    case "navigation.chapterPlan":
      return loadWorkspaceNavigation(refs, "chapter_plan");
    case "navigation.scene":
      return loadWorkspaceNavigation(refs, "chapter_scene");
    case "navigation.finalOutputs":
      return loadWorkspaceNavigation(refs, "final_outputs");
    case "navigation.pluginOutputs":
      return loadWorkspaceNavigation(refs, "plugin_outputs");

    case "project.createRequest":
      return createConfirmedProject(form);
    case "project.validateAndDraft": {
      const requestId = requireRef(refs, "creationRequestId", "项目创建请求 ID");
      await projectApi.validateProjectCreationRequest(requestId);
      return projectApi.createProjectCreationDraft(requestId);
    }
    case "project.confirmDraft":
      return confirmExistingProjectDraft(refs);
    case "project.cancelDraft":
      return projectApi.cancelProjectCreationDraft(requireRef(refs, "creationDraftId", "项目草稿 ID"));

    case "projects.refresh":
      return projectApi.getProjects();
    case "projects.openSelected": {
      const projectId = requireRef(refs, "selectedProjectId", "选中项目 ID");
      const openedProject = await projectApi.openProject(projectId);
      const activeSelection = await projectApi.setActiveProjectSelection({
        projectId,
        selectedBy: "user",
      });
      return compactObject({
        project_id: projectId,
        opened_project: openedProject,
        active_project_selection: activeSelection,
      });
    }

    case "template.refresh":
      return compactObject({
        templates: await projectApi.getProjectTemplates(),
        demo_seeds: await safeRead(() => projectApi.getDemoSeeds()),
        project_origin_badge: refs.projectId
          ? await safeRead(() => projectApi.getProjectOriginBadge(refs.projectId))
          : null,
      });
    case "template.createRequest":
      return projectApi.createTemplateInstantiationRequest(refs.templateId || "default", defaultPayload);
    case "template.validateAndInstantiate": {
      return instantiateTemplate(refs);
    }
    case "template.runDemo":
      return projectApi.runDemoSeed(refs.demoSeedId || "default", {
        ...defaultPayload,
        projectId: refs.projectId || refs.selectedProjectId || "",
        creationRequestId: refs.creationRequestId || null,
        creationDecisionId: refs.creationDecisionId || null,
        explicitUserSelection: true,
      });

    case "framework.recommend":
      return projectApi.recommendFrameworkWorkbenchMapping(Number(form.chapterCount || 5), "balanced", true);
    case "framework.workbench":
      return loadFrameworkWorkbenchSurface(refs);
    case "framework.updateChapterCount":
      return projectApi.updateFrameworkWorkbenchChapterCount(Number(form.chapterCount || 5), true, true);
    case "framework.updateAssignment":
      return projectApi.updateFrameworkWorkbenchAssignment(
        Number(form.chapterIndex || 1),
        Array.isArray(form.linkedMacroComponentIds) ? form.linkedMacroComponentIds : [],
        true,
        form.frameworkNote || defaultPayload.safeUserNote,
      );
    case "framework.saveDraft":
      return projectApi.createFrameworkCompositionDraft({
        title: form.frameworkTitle || "用户编排 Framework",
        safeUserNote: form.frameworkNote || "",
      });
    case "framework.validateAndConfirm": {
      return validateAndConfirmFrameworkWorkbench(form);
    }
    case "framework.library":
      return projectApi.getFrameworkLibraryItems();
    case "framework.libraryFromCandidates": {
      const packageArtifact = defaultAnalyzeStoriesFrameworkPackage();
      return projectApi.buildFrameworkLibraryFromVocabularyArtifact(
        {
          macro_components: packageArtifact.macro_framework.components,
          chapter_modules: packageArtifact.component_vocabulary.chapter_modules,
        },
        {
          source_id: refs.analyzeCandidateId || refs.analyzeImportId || "production_ui_live_parity_framework",
          source_import_id: refs.analyzeImportId || "",
          safe_summary: "Production UI Analyze Stories vocabulary import.",
        },
        defaultPayload.safeUserNote,
      );
    }
    case "framework.createPrivate":
      return projectApi.createFrameworkLibraryPrivateFramework({ title: "私有 Framework", safeUserNote: defaultPayload.safeUserNote });
    case "framework.openImportedSession":
      return loadImportedFrameworkSessionSurface(refs);
    case "framework.selectImportedSession":
      return loadImportedFrameworkSessionSurface(refs, null, form.importedEditSessionId);
    case "framework.saveImportedSession":
      return saveImportedFrameworkSession(refs, form);
    case "framework.validateImportedSession":
      {
        const editSessionId = form.importedEditSessionId || requireRef(refs, "importedEditSessionId", "导入编辑会话 ID");
        const validationResult = await projectApi.validateImportedFrameworkEditSession(editSessionId);
        return loadImportedFrameworkSessionSurface(refs, validationResult, editSessionId);
      }
    case "framework.buildActivationPlan":
      {
        const editSessionId = form.importedEditSessionId || requireRef(refs, "importedEditSessionId", "导入编辑会话 ID");
        const planResult = await projectApi.buildImportedFrameworkActivationPlan(editSessionId, form.activationMode || "");
        return loadImportedFrameworkSessionSurface(refs, planResult, editSessionId);
      }
    case "framework.confirmActivationPlan":
      return projectApi.confirmImportedFrameworkActivationPlan(
        form.importedActivationPlanId || requireRef(refs, "importedActivationPlanId", "激活计划 ID"),
        {
          ...defaultPayload,
          acceptWarnings: Boolean(form.acceptWarnings),
        },
      );

    case "analyze.import":
      {
        let artifact = form.storyImportArtifact || null;
        if (!artifact) {
          const sourceText = String(
            form.sourceText ||
            form.storySource ||
            form.storyImportSource ||
            "",
          ).trim();
          if (!sourceText) {
            const error = new Error("请先粘贴或上传 Analyze Stories 导出的 Framework Package JSON。");
            error.code = "ANALYZE_IMPORT_SOURCE_REQUIRED";
            throw error;
          }
          try {
            artifact = JSON.parse(sourceText);
          } catch {
            const error = new Error("当前导入接口需要 Analyze Stories 生成的 JSON 产物，原始故事文本请先在 Analyze Stories 工作台完成分析。");
            error.code = "ANALYZE_IMPORT_JSON_REQUIRED";
            throw error;
          }
        }
        if (!artifact || typeof artifact !== "object" || Array.isArray(artifact)) {
          const error = new Error("Analyze Stories 导入内容必须是有效的 JSON 对象。");
          error.code = "ANALYZE_IMPORT_INVALID_ARTIFACT";
          throw error;
        }
      const importResult = await projectApi.importAnalyzeStoriesArtifact({
        artifact,
        declaredFileKind: "framework_package",
        originalFilename: form.filename || "analyze-stories-framework-package.json",
      });
      return loadAnalyzeStoriesSurface(refs, importResult);
      }
    case "analyze.refresh":
      return loadAnalyzeStoriesSurface(refs);
    case "analyze.createCandidate":
      return projectApi.createAnalyzeStoriesFrameworkCandidate(requireRef(refs, "analyzeImportId", "导入记录 ID"));
    case "analyze.validateBundle":
      return projectApi.validateAnalyzeStoriesBundle(requireRef(refs, "analyzeImportId", "导入记录 ID"), defaultPayload);
    case "analyze.startEditSession":
      {
        const sessionResult = await projectApi.startImportedFrameworkEditSession(
          form.analyzeCandidateId || requireRef(refs, "analyzeCandidateId", "Framework 候选 ID"),
        );
        return loadImportedFrameworkSessionSurface(refs, sessionResult);
      }
    case "analyze.markCandidateReviewed":
      return projectApi.markAnalyzeStoriesAdapterCandidateReviewed(requireRef(refs, "analyzeCandidateId", "Framework 候选 ID"), defaultPayload.safeUserNote);

    case "storySetup.createPrompt":
      return createOrReuseStorySetupPrompt(refs, form);
    case "storySetup.loadProjectPrompt":
      return loadStorySetupProjectPrompt(refs);
    case "storySetup.current":
      return loadCurrentStorySetupSurface(refs);
    case "storySetup.createDraft": {
      return createStorySetupDraftBundleWithQuestions(refs);
    }
    case "storySetup.answerQuestion":
      return answerStorySetupQuestionAndRefresh(refs, form);
    case "storySetup.createDecision":
    case "storySetup.confirmDecision":
      return createOrReuseStorySetupDecision(refs, form);
    case "storySetup.reviseDecision":
      return createOrReuseStorySetupDecision(refs, form, "request_revision");
    case "storySetup.createHandoff":
      return createOrReuseStorySetupHandoff(refs, form);
    case "storySetup.bootstrapHandoff": {
      const handoffId = requireRef(refs, "storySetupHandoffId", "故事设定交接包 ID");
      return projectApi.bootstrapStorySetupHandoff(handoffId, {
        safeUserNote: defaultPayload.safeUserNote,
      });
    }

    case "world.generate": {
      const storyIdea = await resolveWorldGenerationIdea(refs, form);
      return projectApi.generateWorldCanvas(storyIdea);
    }
    case "world.current":
      {
        const projectId = refs.projectId || refs.selectedProjectId || "";
        const [worldCanvas, storyPremise, storySetupState] = await Promise.all([
          safeRead(() => projectApi.getCurrentWorldCanvas()),
          safeRead(() => projectApi.getCurrentProjectStoryPremise()),
          safeRead(() => projectApi.getCurrentStorySetupState({ projectId })),
        ]);
        return compactObject({
          world_canvas: worldCanvas,
          story_premise: storyPremise,
          story_setup_state: storySetupState,
          story_setup_handoff: storySetupState?.story_setup_handoff || storySetupState?.storySetupHandoff || null,
          story_setup_draft_bundle: storySetupState?.story_setup_draft_bundle || storySetupState?.storySetupDraftBundle || null,
          story_setup_prompt: storySetupState?.story_setup_prompt || storySetupState?.storySetupPrompt || null,
        });
      }
    case "world.revise":
      return projectApi.reviseWorldCanvas(form.worldRevision || form.answerText || "请根据用户补充修订世界画布。");
    case "world.confirm":
      return projectApi.confirmWorldCanvas(defaultPayload.userInput);

    case "characters.generate":
      return generateRoleForTier(form);
    case "characters.current":
      return loadRolesSurface(refs);
    case "characters.revise":
      return reviseRoleForTier(refs, form);
    case "characters.confirm":
      return confirmGeneratedRoleAndRefresh(refs, form);
    case "characters.finishMainCast":
      return compactObject({
        finish_main_cast: await projectApi.finishMainCast(defaultPayload.userInput),
        ...(await loadRolesSurface(refs)),
      });
    case "roles.refresh":
      return projectApi.getRoles({ tier: form.roleTier || "", status: form.roleStatus || "", includeArchived: false });
    case "roles.create":
      return projectApi.createRole({ name: form.roleName || "新角色", tier: form.roleTier || "A", safeUserNote: defaultPayload.safeUserNote });
    case "roles.patch":
      return projectApi.patchRole(requireRef(refs, "characterId", "角色 ID"), { safe_user_note: defaultPayload.safeUserNote });
    case "roles.changeTier":
      return projectApi.changeRoleTier(
        requireRef(refs, "characterId", "角色 ID"),
        form.roleTier || "B",
        form.answerText || defaultPayload.userInput,
      );
    case "roles.archive":
      return projectApi.archiveRole(
        requireRef(refs, "characterId", "角色 ID"),
        form.archiveReason || "用户归档",
        form.answerText || defaultPayload.userInput,
      );
    case "roles.contextPreview":
      return projectApi.buildRoleContextPreview({
        character_ids: [requireRef(refs, "characterId", "角色 ID")],
      });
    case "roles.proposeStateChange":
      return projectApi.proposeRoleStateChange({ character_id: requireRef(refs, "characterId", "角色 ID"), safe_user_note: defaultPayload.safeUserNote });
    case "roles.pendingStateChanges":
      return projectApi.getPendingRoleStateChanges();
    case "roles.confirmStateChange":
      return projectApi.confirmRoleStateChange(requireRef(refs, "roleStateChangeId", "角色状态变更 ID"), defaultPayload.userInput);
    case "roles.rejectStateChange":
      return projectApi.rejectRoleStateChange(requireRef(refs, "roleStateChangeId", "角色状态变更 ID"), defaultPayload.userInput);

    case "chapter.buildCurrent": {
      const chapterIndex = await resolveActiveChapterIndex(refs, form);
      return projectApi.buildCurrentChapterFramework({
        chapterIndex,
      });
    }
    case "chapter.currentFramework": {
      const chapterIndex = await resolveActiveChapterIndex(refs, form);
      return projectApi.getCurrentChapterFrameworkBuild(
        null,
        chapterIndex,
      );
    }
    case "chapter.currentPlan": {
      const projectId = refs.projectId || refs.selectedProjectId || "";
      const [chapterPlan, worldCanvas, storyPremise, storySetupState, roles, frameworkWorkbench] = await Promise.all([
        projectApi.getCurrentChapterPlan(),
        safeRead(() => projectApi.getCurrentWorldCanvas()),
        safeRead(() => projectApi.getCurrentProjectStoryPremise()),
        safeRead(() => projectApi.getCurrentStorySetupState({ projectId })),
        safeRead(() => projectApi.getRoles({ includeArchived: false })),
        safeRead(() => projectApi.getFrameworkWorkbench()),
      ]);
      return compactObject({
        chapter_plan: chapterPlan,
        world_canvas: worldCanvas,
        story_premise: storyPremise,
        story_setup_state: storySetupState,
        roles,
        framework_workbench: frameworkWorkbench,
      });
    }
    case "chapter.generatePlan": {
      const scope = await resolveChapterPlanGenerationScope(refs, form);
      await ensureCurrentChapterFramework(refs, scope.chapterIndex);
      const storyPremise = await safeRead(() => projectApi.getCurrentProjectStoryPremise());
      const authoritativePrompt = projectStoryPremiseText(storyPremise);
      return projectApi.generateChapterPlan(
        usableFormText(form.chapterPlanPrompt) ||
          usableFormText(form.storyGoal) ||
          usableFormText(form.storygoal) ||
          authoritativePrompt ||
          defaultPayload.safeUserNote,
        scope.chapterCount,
        scope.chapterIndex,
        refs.frameworkCompositionId || "",
      );
    }
    case "chapter.setSceneCount": {
      const chapterIndex = await resolveActiveChapterIndex(refs, form);
      const sceneCount = Number(form.sceneCount);
      if (!Number.isInteger(sceneCount) || sceneCount < 1 || sceneCount > 20) {
        throw new Error("请输入 1 到 20 之间的有效幕数。");
      }
      return projectApi.setChapterSceneCount(chapterIndex, sceneCount);
    }
    case "chapter.repairRoles":
      return projectApi.repairChapterPlanSupportingRoleReferences();
    case "chapter.revise": {
      const revisionText = usableFormText(form.chapterRevision);
      if (!revisionText) {
        throw new Error("请先填写章节路线修订说明。");
      }
      return projectApi.reviseChapterPlan(revisionText);
    }
    case "chapter.confirm": {
      const currentPlanBeforeConfirm = await projectApi.getCurrentChapterPlan();
      const currentDraftBeforeConfirm =
        currentPlanBeforeConfirm?.draft ||
        currentPlanBeforeConfirm?.chapter_plan?.draft ||
        currentPlanBeforeConfirm?.chapterPlan?.draft ||
        {};
      let confirmation = currentPlanBeforeConfirm;
      if (String(currentDraftBeforeConfirm?.status || "").toLowerCase() !== "confirmed") {
        try {
          confirmation = await projectApi.confirmChapterPlan(
            form.userInput ||
              form.answerText ||
              "用户确认使用当前章节计划草案；如果模型服务暂不可用，接受当前保守草案继续进入场景写作。",
          );
        } catch (error) {
          if (!isChapterPlanAlreadyConfirmedError(error)) {
            throw error;
          }
          confirmation = await projectApi.getCurrentChapterPlan();
        }
      }
      const storyProgress = await safeRead(() => projectApi.getStoryProgressCurrent());
      const activeChapterId = preferRuntimeChapterId(
        storyProgress?.current_chapter_id || storyProgress?.currentChapterId || confirmation?.chapter_id || confirmation?.chapterId,
        refs.chapterId,
      );
      const nextRefs = {
        ...refs,
        chapterId: activeChapterId || refs.chapterId,
        chapterIndex: Number(storyProgress?.current_chapter_index || storyProgress?.currentChapterIndex || refs.chapterIndex || 1) || 1,
        sceneId: "",
        sceneIndex: 1,
        sceneRevisionId: "",
        sceneParticipantSelectionId: "",
        sceneParticipantCandidateId: "",
      };
      const sceneSurface = await loadSceneSurface(nextRefs);
      return compactObject({
        confirmation,
        story_progress: storyProgress,
        ...sceneSurface,
      });
    }

    case "scene.generateFirst":
      return generateFirstSceneWithPrerequisites(refs, form);
    case "scene.regenerateFirst":
      return projectApi.regenerateFirstScene(
        form.regenerationHint ||
          form.sceneRevision ||
          "重新生成当前场景草稿，移除诊断占位文本，并严格使用当前项目提示词、世界画布、角色状态、章节目标和场景记忆。",
        refs.sceneId,
        refs.chapterId,
        refs.sceneIndex,
      );
    case "scene.generateNext":
      return generateNextSceneWithPrerequisites(refs);
    case "scene.current":
      return loadSceneSurface(refs, {
        preferRequestedSceneIndex: Boolean(refs.sceneSelectionPinned),
      });
    case "scene.openExisting":
      return loadSceneSurface(refs, { preferRequestedSceneIndex: true });
    case "scene.currentRevision": {
      const sceneRevision = await safeRead(() =>
        projectApi.getSceneRevisionCandidate(requireRef(refs, "sceneId", "场景 ID")),
      );
      const revisionCandidate = sceneRevision?.candidate || sceneRevision?.current_candidate || {};
      return compactObject({
        ...(await loadSceneSurface(refs, { preferRequestedSceneIndex: true })),
        revision_id: revisionCandidate.revision_id || revisionCandidate.revisionId || "",
        scene_revision: sceneRevision,
      });
    }
    case "scene.revise": {
      const revisionPrompt = String(form.sceneRevision || "").trim();
      if (!revisionPrompt) {
        throw new Error("请先填写希望如何修订当前场景。");
      }
      const sceneRevision = await projectApi.reviseScene(
        requireRef(refs, "sceneId", "场景 ID"),
        revisionPrompt,
      );
      const revisionCandidate = sceneRevision?.candidate || sceneRevision?.current_candidate || {};
      return compactObject({
        revision_id: revisionCandidate.revision_id || revisionCandidate.revisionId || "",
        scene_revision: sceneRevision,
        ...(await loadSceneSurface(refs, { preferRequestedSceneIndex: true })),
      });
    }
    case "scene.reviseConfirmed": {
      const revisionPrompt = String(form.sceneRevision || "").trim();
      if (!revisionPrompt) {
        throw new Error("请先填写希望如何修改已确认场景。");
      }
      const previewResponse = await projectApi.createModificationImpactPreview({
        sourceObjectType: "confirmed_scene",
        sourceObjectId: requireRef(refs, "sceneId", "场景 ID"),
        modificationSourceType: "user_intent",
        modificationText: revisionPrompt,
        modificationSummary: revisionPrompt,
      });
      const preview = previewResponse?.preview || {};
      const previewId = preview.preview_id || preview.previewId;
      if (!previewId) {
        throw new Error("后端没有返回修改影响预览 ID。");
      }
      const modificationChoice = await projectApi.chooseModificationImpactOption(previewId, {
        actionType: "rewrite_affected_current_scene",
        userInput: revisionPrompt,
        revisionPrompt,
        acceptWarnings: true,
      });
      return compactObject({
        ...(await loadSceneSurface(refs, { preferRequestedSceneIndex: true })),
        modification_preview_id: previewId,
        modification_preview: previewResponse,
        modification_choice: modificationChoice,
        scene_revision: modificationChoice,
      });
    }
    case "scene.confirmRevision": {
      const sceneRevision = await projectApi.confirmSceneRevision(
        requireRef(refs, "sceneId", "场景 ID"),
        requireRef(refs, "sceneRevisionId", "场景修订候选 ID"),
        form.userInput || "确认采用当前场景修订候选。",
      );
      return compactObject({
        scene_revision: sceneRevision,
        ...(await loadSceneSurface(refs, { preferRequestedSceneIndex: true })),
      });
    }
    case "scene.rejectRevision": {
      const sceneRevision = await projectApi.rejectSceneRevision(
        requireRef(refs, "sceneId", "场景 ID"),
        requireRef(refs, "sceneRevisionId", "场景修订候选 ID"),
        form.userInput || "放弃当前场景修订候选。",
      );
      return compactObject({
        scene_revision: sceneRevision,
        ...(await loadSceneSurface(refs, { preferRequestedSceneIndex: true })),
      });
    }
    case "scene.participantRefresh":
      return projectApi.refreshSceneParticipantSelection(requireRef(refs, "sceneParticipantSelectionId", "参与角色候选 ID"));
    case "scene.modificationPreview":
      return projectApi.createModificationImpactPreview({
        sourceObjectType: "confirmed_scene",
        sourceObjectId: refs.sceneId || "",
        modificationSourceType: "user_intent",
        modificationText: form.sceneRevision || "",
      });
    case "scene.continuityCheck":
      return compactObject({
        continuity_state: await projectApi.getContinuityState({ sceneId: requireRef(refs, "sceneId", "场景 ID"), mode: "user_blocker" }),
        ...(await loadSceneSurface(refs, { preferRequestedSceneIndex: true })),
      });
    case "scene.commit":
      return commitSceneAndRefresh(refs);
    case "scene.chooseModification":
      return projectApi.chooseModificationImpactOption(requireRef(refs, "modificationPreviewId", "修改影响预览 ID"), {
        selected_option_id: form.selectedOptionId || "default",
        safe_user_note: defaultPayload.safeUserNote,
      });
    case "scene.futureQuestion":
      return projectApi.getFutureIssues();
    case "scene.acceptContinuity":
      return projectApi.acceptContinuityIssue(requireRef(refs, "continuityIssueId", "连续性问题 ID"), defaultPayload.userInput);
    case "scene.resolveContinuity":
      return projectApi.resolveContinuityIssue(requireRef(refs, "continuityIssueId", "连续性问题 ID"), {
        resolutionText: form.answerText || defaultPayload.answerText,
      });
    case "scene.archivePreview":
      return archiveCurrentChapter(refs, form);
    case "scene.archiveCurrent": {
      const target = await resolveActiveChapterArchiveTarget(refs, form);
      return projectApi.previewChapterArchive(target.chapterId, target.chapterIndex);
    }
    case "scene.confirmParticipant": {
      const { confirmations, nextRefs } = await confirmPendingSceneParticipantCandidates(refs);
      return compactObject({
        confirmation: confirmations.at(-1) || null,
        confirmations,
        roles: await safeRead(() => projectApi.getRoles({ includeArchived: false })),
        ...(await loadSceneSurface(nextRefs)),
      });
    }
    case "scene.rejectParticipant":
      return compactObject({
        rejection: await projectApi.rejectSceneParticipantCreationCandidate(await resolveSceneParticipantCandidateId(refs)),
        participant_selection: refs.sceneParticipantSelectionId
          ? await safeRead(() => projectApi.refreshSceneParticipantSelection(refs.sceneParticipantSelectionId))
          : null,
      });
    case "scene.acceptPreModify":
      return projectApi.acceptPreModifyCandidate(requireRef(refs, "preModifyCandidateId", "预修改候选 ID"), defaultPayload);
    case "scene.confirmNextChapter":
      return continueToNextChapter(refs, form);
    case "scene.confirmStoryComplete":
      {
        const storyComplete = await projectApi.confirmStoryDraftComplete(true);
        const readinessResult = await evaluateFinalReadiness();
        return compactObject({
          story_complete: storyComplete,
          ...readinessResult,
        });
      }

    case "final.evaluate":
      return evaluateFinalReadiness();
    case "final.assemble":
      return assembleFinalStoryPackage(refs, form);
    case "final.export":
      return exportFinalStoryPackageAndLoadPreview(refs, form);
    case "final.refreshExports":
      return loadFinalExportsWithSnapshot(refs);
    case "final.viewerState":
      return loadFinalViewer(refs);
    case "final.readiness":
      return loadFinalReadinessIssues(refs);
    case "final.download": {
      const snapshotId = await resolveFinalSnapshotId(refs);
      const downloadResult = await projectApi.downloadFinalStoryPackageSnapshot(
        snapshotId || requireRef(refs, "finalSnapshotId", "最终输出快照 ID"),
        form.exportFormat || "txt",
      );
      return compactObject({
        download_result: downloadResult,
        selected_format: form.exportFormat || "txt",
        ...(await loadFinalExportsWithSnapshot(refs)),
      });
    }

    case "plugins.refresh":
      return projectApi.getPlugins();
    case "plugins.validateInput": {
      const snapshotId = await resolveFinalSnapshotId(refs);
      return projectApi.validatePluginInput(refs.pluginId || "script_forging", {
        snapshotId,
        safeUserNote: defaultPayload.safeUserNote,
      });
    }
    case "plugins.createRun": {
      const snapshotId = await resolveFinalSnapshotId(refs);
      return projectApi.createPluginRun(refs.pluginId || "script_forging", {
        snapshotId,
        safeUserNote: defaultPayload.safeUserNote,
      });
    }
    case "plugins.run":
      return refs.pluginRunId ? projectApi.getPluginRun(refs.pluginRunId) : projectApi.getPluginRuns();
    case "plugins.confirmCheckpoint":
      return projectApi.confirmPluginCheckpoint(requireRef(refs, "pluginRunId", "插件运行 ID"), requireRef(refs, "pluginCheckpointId", "检查点 ID"), defaultPayload);
    case "plugins.reviseCheckpoint":
      return projectApi.revisePluginCheckpoint(requireRef(refs, "pluginRunId", "插件运行 ID"), requireRef(refs, "pluginCheckpointId", "检查点 ID"), defaultPayload);
    case "plugins.rejectCheckpoint":
      return projectApi.rejectPluginCheckpoint(requireRef(refs, "pluginRunId", "插件运行 ID"), requireRef(refs, "pluginCheckpointId", "检查点 ID"), defaultPayload);
    case "plugins.artifacts":
      return refs.pluginRunId ? projectApi.getPluginRunArtifacts(refs.pluginRunId) : projectApi.getPluginOutputProductViews();
    case "plugins.safetyReport":
      return projectApi.getPluginRunSafetyReport(requireRef(refs, "pluginRunId", "插件运行 ID"));

    case "settings.workbench":
      return loadModelSettingsSurface();
    case "settings.activeModel":
      return projectApi.getActiveModelSelection();
    case "settings.secretPolicy":
      return projectApi.getModelSecretPolicy();
    case "settings.createProfile":
      return loadModelSettingsSurface(await projectApi.createModelProviderProfile({
        providerType: form.providerType || "deepseek",
        displayName: form.modelProfileName || form.displayName || "Model Provider",
        baseUrl: form.baseUrl || "",
        modelName: form.modelName || "",
        apiKeyRef: form.apiKeyRef || "",
        enabled: form.enabledToggle ?? true,
      }));
    case "settings.patchProfile": {
      const updatedProfile = await upsertModelProviderProfile(refs, form);
      return loadModelSettingsSurface(updatedProfile);
    }
    case "settings.setActive": {
      const profileId = firstNonEmptyText(form.profileId, refs.modelProfileId);
      return loadModelSettingsSurface(await projectApi.setActiveModelSelection({
        providerProfileId: profileId || requireRef(refs, "modelProfileId", "模型配置 ID"),
        selectedBy: "user",
      }));
    }
    case "settings.healthCheck": {
      const profileId = firstNonEmptyText(form.profileId, refs.modelProfileId);
      return loadModelSettingsSurface(await projectApi.runModelProviderHealthCheck(
        profileId || requireRef(refs, "modelProfileId", "模型配置 ID"),
      ));
    }
    case "settings.preferences":
      return compactObject({
        navigation_preferences: await projectApi.patchProductNavigationPreferences({ lastWorkspaceId: "settings" }),
        mode_profile: await safeRead(() => projectApi.patchProductModeProfile({ modeProfileId: form.modeProfileId || "ordinary" })),
      });

    default:
      return projectApi.getProductNavigationState();
  }
}

export function getApiMode() {
  return runtimeApiMode();
}
