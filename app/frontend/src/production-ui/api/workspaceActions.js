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

function firstNonEmptyText(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) {
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
  const projectTitle = firstNonEmptyText(form.projectTitle, form.requestedTitle, form.projectName);
  const roleTier = normalizeRoleTier(form.roleTier, refs.roleTier);
  return compactObject({
    ...refs,
    setupPrompt: promptText || refs.setupPrompt,
    promptText: promptText || refs.promptText,
    projectPrompt: promptText || refs.projectPrompt,
    projectTitle: projectTitle || refs.projectTitle,
    requestedTitle: projectTitle || refs.requestedTitle,
    roleTier: roleTier || refs.roleTier,
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

function updateRefsFromResult(refs, result) {
  const nestedActionResult = result?.action_result || result?.actionResult || {};
  const activeProject = result?.active_project_selection || result?.activeProjectSelection || {};
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
  const generatedRoleDraft = result?.draft || result?.generated_role_draft || result?.generatedRoleDraft || result?.role_draft || result?.roleDraft || {};
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
  const currentScene = result?.current_scene || result?.currentScene || result?.scene || {};
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
    chapterFramework?.chapter_index ||
    chapterFramework?.chapterIndex ||
    refs.chapterIndex ||
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
      pickId(firstAnalyzeCandidate, ["candidate_id", "candidateId", "framework_candidate_id", "id"]) ||
      refs.analyzeCandidateId,
    importedEditSessionId: pickId(result, ["edit_session_id", "editSessionId", "id"]) || refs.importedEditSessionId,
    importedActivationPlanId: pickId(result, ["activation_plan_id", "activationPlanId", "plan_id", "id"]) || refs.importedActivationPlanId,
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
      pickId(generatedRoleDraft, ["character_id", "characterId", "role_id", "id"]) ||
      pickId(generatedRoleDraft?.character, ["character_id", "characterId", "role_id", "id"]) ||
      pickId(generatedRoleDraft?.role, ["character_id", "characterId", "role_id", "id"]) ||
      pickId(firstRole, ["character_id", "characterId", "role_id", "id"]) ||
      refs.characterId,
    roleTier:
      String(
        result?.target_tier ||
        result?.targetTier ||
        currentCharacterDraft?.target_tier ||
        currentCharacterDraft?.targetTier ||
        currentCharacter?.tier ||
        refs.roleTier ||
        generatedRoleDraft?.target_tier ||
        generatedRoleDraft?.targetTier ||
        generatedRoleDraft?.complexity_profile?.tier ||
        generatedRoleDraft?.complexityProfile?.tier ||
        generatedRoleDraft?.character?.tier ||
        generatedRoleDraft?.role?.tier ||
        firstRole?.tier ||
        "",
      ).toUpperCase(),
    roleStateChangeId: pickId(result, ["change_id", "role_state_change_id", "id"]) || refs.roleStateChangeId,
    chapterId:
      pickId(result, ["chapter_id", "chapterId", "id"]) ||
      pickId(chapterFramework, ["chapter_id", "chapterId", "id"]) ||
      refs.chapterId,
    chapterIndex: chapterIndex || refs.chapterIndex,
    chapterFrameworkId:
      pickId(result, ["chapter_framework_id", "chapterFrameworkId", "id"]) ||
      pickId(chapterFramework, ["chapter_framework_id", "chapterFrameworkId", "id"]) ||
      refs.chapterFrameworkId,
    sceneId:
      pickId(result, ["scene_id", "sceneId", "id"]) ||
      pickId(currentScene, ["scene_id", "sceneId", "id"]) ||
      refs.sceneId,
    sceneIndex:
      Number(result?.scene_index || result?.sceneIndex || currentScene?.scene_index || currentScene?.sceneIndex || 0) ||
      refs.sceneIndex,
    sceneRevisionId: pickId(result, ["revision_id", "revisionId", "id"]) || refs.sceneRevisionId,
    continuityIssueId: pickId(result, ["issue_id", "issueId", "id"]) || refs.continuityIssueId,
    modificationPreviewId: pickId(result, ["preview_id", "previewId", "id"]) || refs.modificationPreviewId,
    preModifyCandidateId: pickId(result, ["candidate_id", "candidateId", "id"]) || refs.preModifyCandidateId,
    sceneParticipantSelectionId:
      pickId(result, ["selection_id", "selectionId", "scene_participant_selection_id", "id"]) ||
      pickId(firstSceneParticipantSelection, ["selection_id", "selectionId", "scene_participant_selection_id", "id"]) ||
      refs.sceneParticipantSelectionId,
    sceneParticipantCandidateId:
      pickId(result, sceneParticipantCandidateIdKeys) ||
      pickId(firstSceneParticipantCandidate, sceneParticipantCandidateIdKeys) ||
      firstIdFromList(result, ["pending_creation_candidate_ids", "candidate_ids"], sceneParticipantCandidateIdKeys) ||
      firstIdFromList(participantSelection, ["pending_creation_candidate_ids", "candidate_ids"], sceneParticipantCandidateIdKeys) ||
      refs.sceneParticipantCandidateId,
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
  let hydrated = mergeHydratedRefs(refs, activeSelection);
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
    shouldHydrateScene ? safeRead(() => projectApi.getCurrentScene()) : Promise.resolve(null),
    shouldHydrateScene ? safeRead(() => projectApi.getSceneProgress()) : Promise.resolve(null),
    shouldHydrateScene ? safeRead(() => projectApi.getStoryProgressCurrent()) : Promise.resolve(null),
    shouldHydrateScene
      ? safeRead(() => projectApi.getCurrentSceneParticipantSelection(hydrated.chapterId || null, Number(hydrated.sceneIndex || 1)))
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

  const [storySetupQuestions, storySetupSafetyReport] = await Promise.all([
    shouldHydrateStorySetup && hydrated.storySetupDraftBundleId
      ? safeRead(() => projectApi.getStorySetupQuestions(hydrated.storySetupDraftBundleId))
      : Promise.resolve(null),
    shouldHydrateStorySetup && hydrated.storySetupDraftBundleId
      ? safeRead(() => projectApi.getStorySetupSafetyReport(hydrated.storySetupDraftBundleId))
      : Promise.resolve(null),
  ]);

  hydrated = mergeHydratedRefs(hydrated, storySetupQuestions, storySetupSafetyReport);

  return {
    ...hydrated,
    pluginId: hydrated.pluginId || "script_forging",
  };
}

function projectCreationPayload(form) {
  const promptText = firstNonEmptyText(form.projectPrompt, form.promptText, form.setupPrompt, form.storyPrompt);
  const modeType = form.modeType || (promptText ? "prompt_first_project" : "blank_project");
  return {
    requestedTitle: firstNonEmptyText(form.projectTitle, form.requestedTitle, form.projectName) || "未命名故事项目",
    requestedLanguage: form.projectLanguage || form.requestedLanguage || "zh",
    promptText,
    modeType,
    explicitUserSelection: true,
  };
}

async function createConfirmedProject(form) {
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
  if (!promptText) {
    const current = await safeRead(() => projectApi.getCurrentStorySetupState({ projectId }), 8000);
    if (current?.story_setup_prompt || current?.storySetupPrompt || current?.story_setup_draft_bundle || current?.storySetupDraftBundle) {
      return current;
    }
  }
  return projectApi.createStorySetupPromptFromProject({
    projectId,
    promptText,
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
    if (existing && storySetupPromptIdFor(existing) === promptId) {
      return loadStorySetupDraftBundleSurface(refs, existing);
    }
  }

  const currentSurface = recoveredCurrentSurface || (await readCurrentStorySetupDraftBundleSurface(refs));
  if (currentSurface?.story_setup_draft_bundle_id && storySetupSurfaceMatchesPrompt(currentSurface, promptId)) {
    return currentSurface;
  }

  let draftBundle = null;
  try {
    draftBundle = await withActionTimeout(
      projectApi.createStorySetupDraftBundleFromPrompt(promptId),
      85000,
      "STORY_SETUP_DRAFT_TIMEOUT",
    );
  } catch (error) {
    if (error?.code !== "API_REQUEST_TIMEOUT" && error?.code !== "STORY_SETUP_DRAFT_TIMEOUT") {
      throw error;
    }
    const recovered = await readCurrentStorySetupDraftBundleSurface(refs);
    if (recovered?.story_setup_draft_bundle_id && storySetupSurfaceMatchesPrompt(recovered, promptId)) {
      return recovered;
    }
  }
  return loadStorySetupDraftBundleSurface(refs, draftBundle);
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
  const questions = refs.storySetupDraftBundleId
    ? await safeRead(() => projectApi.getStorySetupQuestions(refs.storySetupDraftBundleId))
    : null;
  return compactObject({
    answer,
    questions,
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
  return compactObject({
    roles,
    character_draft: characterDraft,
    generated_role_draft: generatedRoleDraft,
    pending_state_changes: pendingStateChanges,
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

async function loadSceneSurface(refs = {}) {
  const sceneId = refs.sceneId || "";
  const [currentScene, sceneProgress, storyProgress, gateReadiness, participantSelection] = await Promise.all([
    projectApi.getCurrentScene(),
    safeRead(() => projectApi.getSceneProgress()),
    safeRead(() => projectApi.getStoryProgressCurrent()),
    sceneId ? safeRead(() => projectApi.getSceneGateReadiness(sceneId)) : Promise.resolve(null),
    safeRead(() => projectApi.getCurrentSceneParticipantSelection(refs.chapterId || null, Number(refs.sceneIndex || 1))),
  ]);
  return compactObject({
    current_scene: currentScene,
    scene_progress: sceneProgress,
    story_progress: storyProgress,
    gate_readiness: gateReadiness,
    participant_selection: participantSelection,
  });
}

async function resolveSceneParticipantCandidateId(refs = {}) {
  if (refs.sceneParticipantCandidateId) {
    return refs.sceneParticipantCandidateId;
  }
  const selection = await safeRead(() =>
    projectApi.getCurrentSceneParticipantSelection(refs.chapterId || null, Number(refs.sceneIndex || 1)),
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

async function commitSceneAndRefresh(refs) {
  const sceneId = requireRef(refs, "sceneId", "场景 ID");
  const gateReadiness = await safeRead(() => projectApi.getSceneGateReadiness(sceneId));
  const commit = await projectApi.commitScene(
    sceneId,
    "confirmed",
    defaultPayload.userInput,
    refs.sceneRevisionId || null,
    [],
  );
  const sceneSurface = await loadSceneSurface(updateRefsFromResult(refs, commit));
  return compactObject({
    gate_readiness: gateReadiness,
    commit,
    ...sceneSurface,
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
  const chapterIndex = Number(form.chapterIndex || refs.chapterIndex || 0) || null;
  const archivePreview = await projectApi.previewChapterArchive(refs.chapterId || null, chapterIndex);
  const archive = await projectApi.archiveChapter({
    chapterId: refs.chapterId || null,
    chapterIndex,
    archiveMode: "stable",
    userInput: form.answerText || defaultPayload.userInput,
    acceptWarnings: true,
  });
  return compactObject({
    archive_preview: archivePreview,
    archive,
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

async function resolveFinalSnapshotId(refs) {
  if (refs.finalSnapshotId) {
    return refs.finalSnapshotId;
  }
  const exportRuns = await safeRead(() => projectApi.getFinalStoryPackageExportRuns());
  const latestExportRun = firstItem(exportRuns, ["export_runs", "exportRuns", "items", "records"]) || {};
  return pickId(latestExportRun, ["snapshot_id", "snapshotId", "id"]);
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
  if (refs.modelProfileId) {
    return projectApi.patchModelProviderProfile(refs.modelProfileId, {
      displayName: form.modelProfileName || undefined,
      baseUrl: form.baseUrl || undefined,
      modelName: form.modelName || undefined,
      apiKeyRef: form.apiKeyRef || undefined,
      safeUserNote: defaultPayload.safeUserNote,
    });
  }

  return projectApi.createModelProviderProfile({
    providerType: form.providerType || "deepseek",
    displayName: form.modelProfileName || "DeepSeek",
    baseUrl: form.baseUrl || "",
    modelName: form.modelName || "",
    apiKeyRef: form.apiKeyRef || "",
    enabled: true,
  });
}

export async function runWorkspaceAction(actionId, context = {}) {
  const actionWorkspaceId = workspaceIdForAction(actionId);
  const form = context.form || {};
  const actionOnlyIds = new Set([
    "project.createRequest",
    "world.generate",
    "world.current",
    "world.revise",
    "world.confirm",
    "characters.generate",
    "characters.current",
    "characters.confirm",
    "characters.finishMainCast",
  ]);
  const shouldSkipPreHydrate = Boolean(context.skipPreHydrate) || actionOnlyIds.has(actionId) || actionId.startsWith("storySetup.");
  const shouldSkipShellState = Boolean(context.skipShellState);
  const hydratedRefs = shouldSkipPreHydrate
    ? context.refs || {}
    : await hydrateWorkspaceRefs(context.refs || {}, { workspaceId: actionWorkspaceId });
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
  const refsAfterAction = mergeClientFormRefs(updateRefsFromResult(refs, actionResult), form);
  if (shouldSkipPreHydrate) {
    return {
      result: compactObject({
        action_id: actionId,
        action_result: actionResult,
      }),
      refs: refsAfterAction,
      skipped: false,
      message: "åŽç«¯æŽ¥å£è°ƒç”¨æˆåŠŸã€‚",
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

  return {
    result,
    refs: updateRefsFromResult(refsAfterAction, result),
    skipped: false,
    message: "后端接口调用成功。",
  };
}

async function callLiveAction(actionId, refs, form) {
  switch (actionId) {
    case "app.progress":
      return getAppProgress();
    case "navigation.createProject":
      return loadWorkspaceNavigation(refs, "create_project");
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
    case "projects.openSelected":
      return projectApi.openProject(requireRef(refs, "selectedProjectId", "选中项目 ID"));

    case "template.refresh":
      return compactObject({
        templates: await projectApi.getProjectTemplates(),
        demo_seeds: await safeRead(() => projectApi.getDemoSeeds()),
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
      return projectApi.getImportedFrameworkEditSessions();
    case "framework.validateImportedSession":
      return projectApi.validateImportedFrameworkEditSession(requireRef(refs, "importedEditSessionId", "导入编辑会话 ID"));
    case "framework.buildActivationPlan":
      return projectApi.buildImportedFrameworkActivationPlan(requireRef(refs, "importedEditSessionId", "导入编辑会话 ID"));
    case "framework.confirmActivationPlan":
      return projectApi.confirmImportedFrameworkActivationPlan(requireRef(refs, "importedActivationPlanId", "激活计划 ID"), defaultPayload);

    case "analyze.import":
      return projectApi.importAnalyzeStoriesArtifact({
        artifact: form.storyImportArtifact || defaultAnalyzeStoriesFrameworkPackage(),
        declaredFileKind: "framework_package",
        originalFilename: "production-ui-live-parity-framework-package.json",
      });
    case "analyze.refresh":
      return projectApi.getAnalyzeStoriesImports();
    case "analyze.createCandidate":
      return projectApi.createAnalyzeStoriesFrameworkCandidate(requireRef(refs, "analyzeImportId", "导入记录 ID"));
    case "analyze.validateBundle":
      return projectApi.validateAnalyzeStoriesBundle(requireRef(refs, "analyzeImportId", "导入记录 ID"), defaultPayload);
    case "analyze.startEditSession":
      return projectApi.startImportedFrameworkEditSession(requireRef(refs, "analyzeCandidateId", "Framework 候选 ID"));
    case "analyze.markCandidateReviewed":
      return projectApi.markAnalyzeStoriesAdapterCandidateReviewed(requireRef(refs, "analyzeCandidateId", "Framework 候选 ID"), defaultPayload.safeUserNote);

    case "storySetup.createPrompt":
      return createOrReuseStorySetupPrompt(refs, form);
    case "storySetup.current":
      return projectApi.getCurrentStorySetupState({ projectId: refs.projectId || refs.selectedProjectId || "" });
    case "storySetup.createDraft": {
      return createStorySetupDraftBundleWithQuestions(refs);
    }
    case "storySetup.answerQuestion":
      return answerStorySetupQuestionAndRefresh(refs, form);
    case "storySetup.createDecision":
    case "storySetup.confirmDecision":
      return projectApi.createStorySetupDecision(requireRef(refs, "storySetupDraftBundleId", "故事设定草案 ID"), {
        decisionType: "confirm_for_handoff",
      });
    case "storySetup.reviseDecision":
      return projectApi.createStorySetupDecision(requireRef(refs, "storySetupDraftBundleId", "故事设定草案 ID"), {
        decisionType: "request_revision",
        requestedChanges: defaultPayload.requestedChanges,
      });
    case "storySetup.bootstrapHandoff": {
      const decisionId = requireRef(refs, "storySetupDecisionId", "故事设定决策 ID");
      let handoff = null;
      try {
        handoff = await projectApi.createStorySetupHandoff(decisionId);
      } catch (error) {
        if (error?.code !== "API_REQUEST_TIMEOUT") {
          throw error;
        }
        handoff = await recoverStorySetupHandoffAfterTimeout(refs);
        if (!handoff) {
          throw error;
        }
      }
      const handoffId = pickId(handoff, ["story_setup_handoff_id", "storySetupHandoffId", "id"]);
      return projectApi.bootstrapStorySetupHandoff(handoffId);
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
      return projectApi.generateRoleDraft({
        userPrompt: form.characterRevision || form.characterPrompt || "请根据用户补充修订角色草案。",
        targetTier: form.roleTier || "A",
        roleHint: form.roleHint || "",
        storyFunctionHint: form.storyFunctionHint || "",
      });
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
      return projectApi.buildRoleContextPreview({ character_id: requireRef(refs, "characterId", "角色 ID") });
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
      return projectApi.generateChapterPlan(
        usableFormText(form.chapterPlanPrompt) || usableFormText(form.storyGoal) || usableFormText(form.storygoal) || defaultPayload.safeUserNote,
        scope.chapterCount,
        scope.chapterIndex,
        refs.frameworkCompositionId || "",
      );
    }
    case "chapter.setSceneCount": {
      const chapterIndex = await resolveActiveChapterIndex(refs, form);
      return projectApi.setChapterSceneCount(chapterIndex, Number(form.sceneCount || 5));
    }
    case "chapter.repairRoles":
      return projectApi.repairChapterPlanSupportingRoleReferences();
    case "chapter.revise":
      return projectApi.reviseChapterPlan(form.chapterRevision || "请根据用户意见修订章节计划。");
    case "chapter.confirm":
      return projectApi.confirmChapterPlan(defaultPayload.userInput);

    case "scene.generateFirst":
      return projectApi.generateFirstScene(null, Number(form.sceneIndex || 1));
    case "scene.generateNext":
      return projectApi.generateNextScene(null, false, null);
    case "scene.current":
      return loadSceneSurface(refs);
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
    case "scene.confirmParticipant":
      return compactObject({
        confirmation: await projectApi.confirmSceneParticipantCreationCandidate(await resolveSceneParticipantCandidateId(refs)),
        roles: await safeRead(() => projectApi.getRoles({ includeArchived: false })),
      });
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
      return compactObject({
        story_complete: await projectApi.confirmStoryDraftComplete(true),
        final_readiness: await safeRead(() => projectApi.getFinalStoryPackageReadiness()),
      });

    case "final.evaluate":
      return evaluateFinalReadiness();
    case "final.export":
      return exportFinalStoryPackageAndLoadPreview(refs, form);
    case "final.refreshExports":
      return compactObject({
        export_runs: await projectApi.getFinalStoryPackageExportRuns(),
        product_views: await safeRead(() => projectApi.getFinalStoryPackageProductViews(stateParams(refs))),
      });
    case "final.viewerState":
      return loadFinalViewer(refs);
    case "final.readiness":
      return loadFinalReadinessIssues(refs);
    case "final.download": {
      const snapshotId = await resolveFinalSnapshotId(refs);
      return projectApi.downloadFinalStoryPackageSnapshot(
        snapshotId || requireRef(refs, "finalSnapshotId", "最终输出快照 ID"),
        form.exportFormat || "txt",
      );
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
      return compactObject({
        workbench: await projectApi.getModelSettingsWorkbench(),
        providers: await safeRead(() => projectApi.getModelSettingsProviders()),
        profiles: await safeRead(() => projectApi.getModelProviderProfiles()),
        active_selection: await safeRead(() => projectApi.getActiveModelSelection()),
        secret_policy: await safeRead(() => projectApi.getModelSecretPolicy()),
      });
    case "settings.activeModel":
      return projectApi.getActiveModelSelection();
    case "settings.secretPolicy":
      return projectApi.getModelSecretPolicy();
    case "settings.createProfile":
      return projectApi.createModelProviderProfile({
        provider_type: form.providerType || "deepseek",
        display_name: form.modelProfileName || "DeepSeek",
        safe_user_note: defaultPayload.safeUserNote,
      });
    case "settings.patchProfile":
      return upsertModelProviderProfile(refs, form);
    case "settings.setActive":
      return projectApi.setActiveModelSelection({
        providerProfileId: requireRef(refs, "modelProfileId", "模型配置 ID"),
        selectedBy: "user",
      });
    case "settings.healthCheck":
      return projectApi.runModelProviderHealthCheck(requireRef(refs, "modelProfileId", "模型配置 ID"));
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
