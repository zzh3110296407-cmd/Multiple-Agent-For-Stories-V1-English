import { STORY_CAPACITY } from "../utils/storyCapacity.js";

const DEFAULT_API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const DEFAULT_GET_TIMEOUT_MS = 8000;

function apiBaseUrl() {
  const search = globalThis.location?.search || "";
  const runtimeBaseUrl = new URLSearchParams(search).get("apiBaseUrl");
  return String(runtimeBaseUrl || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

function apiFetch() {
  return globalThis.fetch.bind(globalThis);
}

export async function request(path, options = {}) {
  const { acceptedStatuses = [], timeoutMs = 0, ...fetchOptions } = options;
  const method = String(fetchOptions.method || "GET").toUpperCase();
  const effectiveTimeoutMs = timeoutMs > 0 ? timeoutMs : method === "GET" ? DEFAULT_GET_TIMEOUT_MS : 0;
  const headers = {
    ...fetchOptions.headers,
  };
  if (fetchOptions.body !== undefined && fetchOptions.body !== null && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const controller = effectiveTimeoutMs > 0 ? new AbortController() : null;
  const timeoutId = controller
    ? globalThis.setTimeout(() => controller.abort(), effectiveTimeoutMs)
    : null;
  let response;
  try {
    response = await apiFetch()(`${apiBaseUrl()}${path}`, {
      headers,
      ...fetchOptions,
      signal: fetchOptions.signal || controller?.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error("API request timed out");
      timeoutError.code = "API_REQUEST_TIMEOUT";
      timeoutError.path = path;
      throw timeoutError;
    }
    throw error;
  } finally {
    if (timeoutId) {
      globalThis.clearTimeout(timeoutId);
    }
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    const detail = body?.detail || response.statusText || "Request failed";
    const message = detail && typeof detail === "object"
      ? detail.message || detail.error_code || JSON.stringify(detail)
      : detail;
    const requestError = new Error(message);
    requestError.status = response.status;
    requestError.detail = detail;
    requestError.body = body;
    if (detail && typeof detail === "object") {
      throw requestError;
    }
    throw requestError;
  }

  return body;
}

async function rawJsonPost(path, payload) {
  const options = { method: "POST" };
  if (payload !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(payload);
  }
  const response = await apiFetch()(`${apiBaseUrl()}${path}`, options);
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body?.detail || response.statusText || "Request failed";
    const message = detail && typeof detail === "object"
      ? detail.message || detail.error_code || JSON.stringify(detail)
      : detail;
    const requestError = new Error(message);
    requestError.status = response.status;
    requestError.detail = detail;
    requestError.body = body;
    throw requestError;
  }
  return body;
}

export function getHealth() {
  return request("/health");
}

export function getProjectStatus() {
  return request("/api/project/status");
}

export function initializeProject() {
  return request("/api/project/init", { method: "POST" });
}

export function getProjectData() {
  return request("/api/project/data");
}

export function getABCDRuntimeOverview(sceneId) {
  return request(`/api/abcd-runtime/scenes/${encodeURIComponent(sceneId)}/overview`);
}

export function getCompositeRuntimeLatest(params = {}) {
  const query = new URLSearchParams();
  if (params.chapterId || params.chapter_id) {
    query.set("chapter_id", params.chapterId || params.chapter_id);
  }
  if (params.sceneId || params.scene_id) {
    query.set("scene_id", params.sceneId || params.scene_id);
  }
  if (params.sceneIndex !== undefined && params.sceneIndex !== null) {
    query.set("scene_index", String(params.sceneIndex));
  } else if (params.scene_index !== undefined && params.scene_index !== null) {
    query.set("scene_index", String(params.scene_index));
  }
  if (params.includeExpert || params.include_expert) {
    query.set("include_expert", "true");
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/composite-runtime/runs/latest${suffix}`);
}

export function getSceneRuntimeRefreshState(sceneId) {
  return request(`/api/scenes/${encodeURIComponent(sceneId)}/runtime-refresh-state`);
}

export function getSceneWriterQualitySurface(sceneId, options = {}) {
  const query = new URLSearchParams();
  if (options.includeExpert || options.include_expert) {
    query.set("include_expert", "true");
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/scenes/${encodeURIComponent(sceneId)}/writer-quality-surface${suffix}`);
}

export function refreshSceneRuntimeRefreshState(sceneId, params = {}) {
  const query = new URLSearchParams();
  if (params.forceRefresh || params.force_refresh) {
    query.set("force_refresh", "true");
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(
    `/api/scenes/${encodeURIComponent(sceneId)}/runtime-refresh-state/refresh${suffix}`,
    { method: "POST" },
  );
}

export function runSceneGateRepair(sceneId, payload = {}, options = {}) {
  const query = new URLSearchParams();
  if (options.includeExpert || options.include_expert) {
    query.set("include_expert", "true");
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/scene-gate-repair/scenes/${encodeURIComponent(sceneId)}/runs${suffix}`, {
    method: "POST",
    body: JSON.stringify({
      scene_id: payload.sceneId || payload.scene_id || sceneId,
      project_id: payload.projectId || payload.project_id || "",
      chapter_id: payload.chapterId || payload.chapter_id || "",
      initial_revision_id: payload.initialRevisionId || payload.initial_revision_id || "",
      max_rounds: payload.maxRounds || payload.max_rounds || 3,
      force_runtime_refresh: payload.forceRuntimeRefresh ?? payload.force_runtime_refresh ?? true,
    }),
  });
}

export function getCompositeRuntimeRun(graphRunId) {
  return request(`/api/composite-runtime/runs/${encodeURIComponent(graphRunId)}`);
}

export function getCompositeRuntimeNodeReceipts(graphRunId) {
  return request(`/api/composite-runtime/runs/${encodeURIComponent(graphRunId)}/node-receipts`);
}

export function getCompositeRuntimeAuthorityAudit(graphRunId) {
  return request(`/api/composite-runtime/runs/${encodeURIComponent(graphRunId)}/authority-audit`);
}

export function getCompositeRuntimeExpertSummary(graphRunId) {
  return request(`/api/composite-runtime/runs/${encodeURIComponent(graphRunId)}/expert-summary`);
}

export function getProjectCreationModes() {
  return request("/api/project-creation/modes");
}

export function getProjectCreationDemoSeeds() {
  return request("/api/project-creation/demo-seeds");
}

export function getCurrentProjectCreationState({
  creationRequestId = "",
  creationDraftId = "",
  projectId = "",
} = {}) {
  const query = new URLSearchParams();
  if (creationRequestId) {
    query.set("creation_request_id", creationRequestId);
  }
  if (creationDraftId) {
    query.set("creation_draft_id", creationDraftId);
  }
  if (projectId) {
    query.set("project_id", projectId);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/project-creation/current${suffix}`);
}

export function createProjectCreationRequest(payload = {}) {
  return request("/api/project-creation/requests", {
    method: "POST",
    body: JSON.stringify({
      mode_type: payload.modeType || payload.mode_type || "blank_project",
      requested_title: payload.requestedTitle || payload.requested_title || "Untitled Story Project",
      requested_language: payload.requestedLanguage || payload.requested_language || "zh",
      prompt_text: payload.promptText ?? payload.prompt_text ?? null,
      template_id: payload.templateId ?? payload.template_id ?? null,
      analyze_stories_import_ref:
        payload.analyzeStoriesImportRef ?? payload.analyze_stories_import_ref ?? null,
      demo_seed_id: payload.demoSeedId ?? payload.demo_seed_id ?? null,
      existing_project_id: payload.existingProjectId ?? payload.existing_project_id ?? null,
      explicit_user_selection:
        payload.explicitUserSelection ?? payload.explicit_user_selection ?? false,
    }),
  });
}

export function getProjectCreationRequest(creationRequestId) {
  return request(`/api/project-creation/requests/${creationRequestId}`);
}

export function validateProjectCreationRequest(creationRequestId) {
  return request(`/api/project-creation/requests/${creationRequestId}/validate`, {
    method: "POST",
  });
}

export function createProjectCreationDraft(creationRequestId) {
  return request(`/api/project-creation/requests/${creationRequestId}/draft`, {
    method: "POST",
    timeoutMs: 15000,
  });
}

export async function createProjectCreationDraftRecoverable(creationRequestId) {
  try {
    return await createProjectCreationDraft(creationRequestId);
  } catch (error) {
    if (error?.code !== "API_REQUEST_TIMEOUT") {
      throw error;
    }
    const current = await getCurrentProjectCreationState({ creationRequestId });
    if (current?.creation_draft) {
      return current.creation_draft;
    }
    return createProjectCreationDraft(creationRequestId);
  }
}

export function getProjectCreationDraft(creationDraftId) {
  return request(`/api/project-creation/drafts/${creationDraftId}`);
}

export function confirmProjectCreationDraft(creationDraftId, payload = {}) {
  return request(`/api/project-creation/drafts/${creationDraftId}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function cancelProjectCreationDraft(creationDraftId) {
  return request(`/api/project-creation/drafts/${creationDraftId}/cancel`, {
    method: "POST",
  });
}

export function getProjects() {
  return request("/api/projects");
}

export function getProjectSummary(projectId) {
  return request(`/api/projects/${projectId}`);
}

export function getProjectOrigin(projectId) {
  return request(`/api/projects/${projectId}/origin`);
}

export function openProject(projectId) {
  return request(`/api/projects/${projectId}/open`, { method: "POST" });
}

export function getActiveProjectSelection() {
  return request("/api/projects/active-selection");
}

export function setActiveProjectSelection(payload = {}) {
  return request("/api/projects/active-selection", {
    method: "POST",
    body: JSON.stringify({
      project_id: payload.projectId || payload.project_id || "",
      selected_by: payload.selectedBy || payload.selected_by || "user",
    }),
  });
}

export function getProjectTemplates() {
  return request("/api/project-templates");
}

export function getProjectTemplate(templateId) {
  return request(`/api/project-templates/${templateId}`);
}

export function createTemplateInstantiationRequest(templateId, payload = {}) {
  return request(`/api/project-templates/${templateId}/instantiation-requests`, {
    method: "POST",
    body: JSON.stringify({
      project_id: payload.projectId || payload.project_id || "",
      creation_request_id: payload.creationRequestId ?? payload.creation_request_id ?? null,
      creation_decision_id: payload.creationDecisionId ?? payload.creation_decision_id ?? null,
      target_workspace: payload.targetWorkspace || payload.target_workspace || "world_canvas",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getTemplateInstantiationRequest(templateInstantiationRequestId) {
  return request(`/api/template-instantiation/requests/${templateInstantiationRequestId}`);
}

export function validateTemplateInstantiationRequest(templateInstantiationRequestId) {
  return request(`/api/template-instantiation/requests/${templateInstantiationRequestId}/validate`, {
    method: "POST",
  });
}

export function instantiateTemplateRequest(templateInstantiationRequestId) {
  return request(`/api/template-instantiation/requests/${templateInstantiationRequestId}/instantiate`, {
    method: "POST",
  });
}

export function getTemplateInstantiationReport(templateInstantiationReportId) {
  return request(`/api/template-instantiation/reports/${templateInstantiationReportId}`);
}

export function getDemoSeeds() {
  return request("/api/demo-seeds");
}

export function getDemoSeed(demoSeedId) {
  return request(`/api/demo-seeds/${demoSeedId}`);
}

export function runDemoSeed(demoSeedId, payload = {}) {
  return request(`/api/demo-seeds/${demoSeedId}/run`, {
    method: "POST",
    body: JSON.stringify({
      project_id: payload.projectId || payload.project_id || "",
      creation_request_id: payload.creationRequestId ?? payload.creation_request_id ?? null,
      creation_decision_id: payload.creationDecisionId ?? payload.creation_decision_id ?? null,
      explicit_user_selection:
        payload.explicitUserSelection ?? payload.explicit_user_selection ?? false,
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getDemoSeedRun(demoSeedRunId) {
  return request(`/api/demo-seeds/runs/${demoSeedRunId}`);
}

export function createDemoSeedIsolationAudit(demoSeedRunId) {
  return request(`/api/demo-seeds/runs/${demoSeedRunId}/isolation-audit`, {
    method: "POST",
  });
}

export function getDemoSeedIsolationAudit(demoSeedIsolationAuditId) {
  return request(`/api/demo-seeds/isolation-audits/${demoSeedIsolationAuditId}`);
}

export function getProjectOriginBadge(projectId) {
  return request(`/api/project-origin-badges/${projectId}`);
}

export function getProductNavigationWorkspaces() {
  return request("/api/product-navigation/workspaces");
}

export function getProductNavigationGroups() {
  return request("/api/product-navigation/groups");
}

export function getProductNavigationState(params = {}) {
  const query = new URLSearchParams();
  if (params.projectId || params.project_id) {
    query.set("project_id", params.projectId || params.project_id);
  }
  if (params.workspaceId || params.workspace_id) {
    query.set("workspace_id", params.workspaceId || params.workspace_id);
  }
  if (params.modeProfileId || params.mode_profile_id) {
    query.set("mode_profile_id", params.modeProfileId || params.mode_profile_id);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/product-navigation/state${suffix}`);
}

export function getProductNavigationAvailability(params = {}) {
  const query = new URLSearchParams();
  if (params.projectId || params.project_id) {
    query.set("project_id", params.projectId || params.project_id);
  }
  if (params.modeProfileId || params.mode_profile_id) {
    query.set("mode_profile_id", params.modeProfileId || params.mode_profile_id);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/product-navigation/availability${suffix}`);
}

export function getProductWorkspaceAccess(workspaceId, params = {}) {
  const query = new URLSearchParams();
  if (params.projectId || params.project_id) {
    query.set("project_id", params.projectId || params.project_id);
  }
  if (params.modeProfileId || params.mode_profile_id) {
    query.set("mode_profile_id", params.modeProfileId || params.mode_profile_id);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/product-navigation/workspaces/${workspaceId}/access${suffix}`);
}

export function getProductNavigationPreferences() {
  return request("/api/product-navigation/preferences");
}

export function patchProductNavigationPreferences(payload = {}) {
  return request("/api/product-navigation/preferences", {
    method: "PATCH",
    body: JSON.stringify({
      mode_profile_id: payload.modeProfileId ?? payload.mode_profile_id ?? undefined,
      last_workspace_id: payload.lastWorkspaceId ?? payload.last_workspace_id ?? undefined,
      collapsed_group_ids:
        payload.collapsedGroupIds ?? payload.collapsed_group_ids ?? undefined,
      pinned_workspace_ids:
        payload.pinnedWorkspaceIds ?? payload.pinned_workspace_ids ?? undefined,
    }),
  });
}

function productProgressQuery(params = {}) {
  const query = new URLSearchParams();
  if (params.projectId || params.project_id) {
    query.set("project_id", params.projectId || params.project_id);
  }
  if (params.modeProfileId || params.mode_profile_id) {
    query.set("mode_profile_id", params.modeProfileId || params.mode_profile_id);
  }
  return query.toString() ? `?${query.toString()}` : "";
}

export function getProductModeProfile(params = {}) {
  const query = new URLSearchParams();
  if (params.modeProfileId || params.mode_profile_id) {
    query.set("mode_profile_id", params.modeProfileId || params.mode_profile_id);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/product-mode/profile${suffix}`);
}

export function patchProductModeProfile(payload = {}) {
  return request("/api/product-mode/profile", {
    method: "PATCH",
    body: JSON.stringify({
      mode_profile_id: payload.modeProfileId || payload.mode_profile_id || "ordinary",
    }),
  });
}

export function getProductProgressState(params = {}) {
  return request(`/api/product-progress/state${productProgressQuery(params)}`, { timeoutMs: 4500 });
}

export function getProductProgressSummary(params = {}) {
  return request(`/api/product-progress/summary${productProgressQuery(params)}`, { timeoutMs: 4500 });
}

export function getProductProgressNextActions(params = {}) {
  return request(`/api/product-progress/next-actions${productProgressQuery(params)}`, { timeoutMs: 4500 });
}

export function getProductProgressDecisionSurfaces(params = {}) {
  return request(`/api/product-progress/decision-surfaces${productProgressQuery(params)}`, { timeoutMs: 4500 });
}

export function getProductProgressBlockingIssues(params = {}) {
  return request(`/api/product-progress/blocking-issues${productProgressQuery(params)}`, { timeoutMs: 4500 });
}

export function getProductProgressExpertEvidence(params = {}) {
  return request(`/api/product-progress/expert-evidence${productProgressQuery(params)}`);
}

export function getProductProgressSafetyReport(params = {}) {
  return request(`/api/product-progress/safety-report${productProgressQuery(params)}`, { timeoutMs: 4500 });
}

export function createStorySetupPromptFromProject(payload = {}) {
  return request("/api/story-setup/prompts/from-project", {
    method: "POST",
    body: JSON.stringify({
      project_id: payload.projectId || payload.project_id || "",
      creation_request_id: payload.creationRequestId ?? payload.creation_request_id ?? null,
      prompt_text: payload.promptText ?? payload.prompt_text ?? null,
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getCurrentStorySetupState({ projectId = "" } = {}) {
  const query = new URLSearchParams();
  if (projectId) {
    query.set("project_id", projectId);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/story-setup/current${suffix}`);
}

export function getStorySetupPrompt(storySetupPromptId) {
  return request(`/api/story-setup/prompts/${encodeURIComponent(storySetupPromptId)}`);
}

export function createStorySetupIntake(storySetupPromptId) {
  return request("/api/story-setup/intakes", {
    method: "POST",
    timeoutMs: 60000,
    body: JSON.stringify({ story_setup_prompt_id: storySetupPromptId || "" }),
  });
}

export function getStorySetupIntake(storySetupIntakeId) {
  return request(`/api/story-setup/intakes/${encodeURIComponent(storySetupIntakeId)}`);
}

export function createStorySetupDraftBundle(payload = {}) {
  return request("/api/story-setup/draft-bundles", {
    method: "POST",
    timeoutMs: 90000,
    body: JSON.stringify({
      story_setup_prompt_id: payload.storySetupPromptId || payload.story_setup_prompt_id || "",
      story_setup_intake_id: payload.storySetupIntakeId ?? payload.story_setup_intake_id ?? null,
      selected_framework_composition_id:
        payload.selectedFrameworkCompositionId ?? payload.selected_framework_composition_id ?? null,
    }),
  });
}

export function createStorySetupDraftBundleFromPrompt(storySetupPromptId) {
  return rawJsonPost(`/api/story-setup/prompts/${encodeURIComponent(storySetupPromptId)}/draft-bundle`);
}

export function getStorySetupDraftBundle(storySetupDraftBundleId) {
  return request(`/api/story-setup/draft-bundles/${encodeURIComponent(storySetupDraftBundleId)}`);
}

export function patchStorySetupDraftBundle(storySetupDraftBundleId, payload = {}) {
  return request(`/api/story-setup/draft-bundles/${encodeURIComponent(storySetupDraftBundleId)}`, {
    method: "PATCH",
    body: JSON.stringify({
      world_canvas_draft_suggestion:
        payload.worldCanvasDraftSuggestion ?? payload.world_canvas_draft_suggestion ?? null,
      main_cast_draft_direction:
        payload.mainCastDraftDirection ?? payload.main_cast_draft_direction ?? null,
      framework_setup_suggestion:
        payload.frameworkSetupSuggestion ?? payload.framework_setup_suggestion ?? null,
      chapter_route_suggestion:
        payload.chapterRouteSuggestion ?? payload.chapter_route_suggestion ?? null,
      selected_framework_composition_id:
        payload.selectedFrameworkCompositionId ?? payload.selected_framework_composition_id ?? null,
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getStorySetupQuestions(storySetupDraftBundleId) {
  return request(`/api/story-setup/draft-bundles/${encodeURIComponent(storySetupDraftBundleId)}/questions`);
}

export function answerStorySetupQuestion(questionId, payload = {}) {
  return request(`/api/story-setup/questions/${encodeURIComponent(questionId)}/answer`, {
    method: "POST",
    body: JSON.stringify({
      answer_text: payload.answerText || payload.answer_text || "",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function createStorySetupDecision(storySetupDraftBundleId, payload = {}) {
  return request(`/api/story-setup/draft-bundles/${encodeURIComponent(storySetupDraftBundleId)}/decisions`, {
    method: "POST",
    body: JSON.stringify({
      decision_type: payload.decisionType || payload.decision_type || "confirm_for_handoff",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      requested_changes: Array.isArray(payload.requestedChanges || payload.requested_changes)
        ? payload.requestedChanges || payload.requested_changes
        : [],
    }),
  });
}

export function getStorySetupDecision(storySetupDecisionId) {
  return request(`/api/story-setup/decisions/${encodeURIComponent(storySetupDecisionId)}`);
}

export function createStorySetupHandoff(storySetupDecisionId, payload = {}) {
  return request(`/api/story-setup/decisions/${encodeURIComponent(storySetupDecisionId)}/handoff`, {
    method: "POST",
    timeoutMs: 30000,
    body: JSON.stringify({
      target_workspace: payload.targetWorkspace || payload.target_workspace || "world_canvas_workspace",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getStorySetupHandoff(storySetupHandoffId) {
  return request(`/api/story-setup/handoffs/${encodeURIComponent(storySetupHandoffId)}`);
}

export function bootstrapStorySetupHandoff(storySetupHandoffId, payload = {}) {
  return request(`/api/story-setup/handoffs/${encodeURIComponent(storySetupHandoffId)}/bootstrap-active-project`, {
    method: "POST",
    timeoutMs: 45000,
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getStorySetupSafetyReport(storySetupDraftBundleId) {
  return request(`/api/story-setup/draft-bundles/${encodeURIComponent(storySetupDraftBundleId)}/safety-report`);
}

export function getPhase2Debug() {
  return request("/api/debug/phase2");
}

export function getModelGatewayStatus() {
  return request("/api/model-gateway/status");
}

export function seedModelGatewayConfig() {
  return request("/api/model-gateway/seed", { method: "POST" });
}

export function configureDeepSeekModelGateway() {
  return request("/api/model-gateway/configure-deepseek", { method: "POST" });
}

export function getModelRuntimeStatus() {
  return request("/api/model-runtime/status");
}

export function getModelRuntimeCalls(limit = 10) {
  return request(`/api/model-runtime/calls?limit=${limit}`);
}

export function getModelRuntimeErrors(limit = 10) {
  return request(`/api/model-runtime/errors?limit=${limit}`);
}

export function runModelRuntimeHealthCheck() {
  return request("/api/model-runtime/health-check", { method: "POST" });
}

export function getModelSettingsProviders() {
  return request("/api/settings/model/providers");
}

export function getModelSettingsWorkbench() {
  return request("/api/settings/model/workbench");
}

export function createModelProviderProfile(payload = {}) {
  return request("/api/settings/model/profiles", {
    method: "POST",
    body: JSON.stringify({
      provider_type: payload.providerType || payload.provider_type || "local",
      display_name: payload.displayName || payload.display_name || "",
      base_url: payload.baseUrl || payload.base_url || "",
      model_name: payload.modelName || payload.model_name || "",
      api_key_ref: payload.apiKeyRef || payload.api_key_ref || "",
      enabled: payload.enabled ?? true,
    }),
  });
}

export function getModelProviderProfiles() {
  return request("/api/settings/model/profiles");
}

export function getModelProviderProfile(profileId) {
  return request(`/api/settings/model/profiles/${profileId}`);
}

export function patchModelProviderProfile(profileId, payload = {}) {
  const body = {};
  if (payload.displayName !== undefined || payload.display_name !== undefined) {
    body.display_name = payload.displayName ?? payload.display_name;
  }
  if (payload.baseUrl !== undefined || payload.base_url !== undefined) {
    body.base_url = payload.baseUrl ?? payload.base_url;
  }
  if (payload.modelName !== undefined || payload.model_name !== undefined) {
    body.model_name = payload.modelName ?? payload.model_name;
  }
  if (payload.apiKeyRef !== undefined || payload.api_key_ref !== undefined) {
    body.api_key_ref = payload.apiKeyRef ?? payload.api_key_ref;
  }
  if (payload.enabled !== undefined) {
    body.enabled = payload.enabled;
  }
  return request(`/api/settings/model/profiles/${profileId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function runModelProviderHealthCheck(profileId) {
  return request(`/api/settings/model/profiles/${profileId}/health-check`, {
    method: "POST",
    timeoutMs: 30000,
  });
}

export function setActiveModelSelection(payload = {}) {
  return request("/api/settings/model/active-selection", {
    method: "POST",
    body: JSON.stringify({
      provider_profile_id: payload.providerProfileId || payload.provider_profile_id || "",
      selected_by: payload.selectedBy || payload.selected_by || "user",
      deterministic_fallback_allowed: payload.deterministicFallbackAllowed ?? payload.deterministic_fallback_allowed ?? true,
      real_model_required: payload.realModelRequired ?? payload.real_model_required ?? false,
    }),
  });
}

export function getActiveModelSelection() {
  return request("/api/settings/model/active-selection");
}

export function getModelSecretPolicy() {
  return request("/api/settings/model/secret-policy");
}

export function seedFrameworkPackage() {
  return request("/api/framework-package/seed", { method: "POST" });
}

export function getFrameworkPackage() {
  return request("/api/framework-package");
}

export function assignFrameworkMacroComponents(chapterCount = STORY_CAPACITY.defaultChapterCount) {
  return request("/api/framework-package/macro-assignments", {
    method: "POST",
    body: JSON.stringify({ chapter_count: chapterCount }),
  });
}

export function getFrameworkWorkbench() {
  return request("/api/framework-package/workbench");
}

export function recommendFrameworkWorkbenchMapping(chapterCount = STORY_CAPACITY.defaultChapterCount, strategy = "balanced", acceptWarnings = false) {
  return request("/api/framework-package/workbench/recommend", {
    method: "POST",
    body: JSON.stringify({
      chapter_count: chapterCount,
      strategy,
      accept_warnings: acceptWarnings,
    }),
  });
}

export function updateFrameworkWorkbenchChapterCount(chapterCount = STORY_CAPACITY.defaultChapterCount, recomputeMapping = true, acceptWarnings = false) {
  return request("/api/framework-package/workbench/chapter-count", {
    method: "POST",
    body: JSON.stringify({
      chapter_count: chapterCount,
      recompute_mapping: recomputeMapping,
      accept_warnings: acceptWarnings,
    }),
  });
}

export function updateFrameworkWorkbenchAssignment(
  chapterIndex,
  linkedMacroComponentIds,
  acceptWarnings = false,
  userInput = "",
) {
  return request(`/api/framework-package/workbench/assignments/${chapterIndex}`, {
    method: "PATCH",
    body: JSON.stringify({
      linked_macro_component_ids: linkedMacroComponentIds,
      accept_warnings: acceptWarnings,
      user_input: userInput,
    }),
  });
}

export function validateFrameworkWorkbenchMapping() {
  return request("/api/framework-package/workbench/validate");
}

export function confirmFrameworkWorkbenchMapping(userInput = "", acceptWarnings = false) {
  return request("/api/framework-package/workbench/confirm", {
    method: "POST",
    body: JSON.stringify({
      user_input: userInput,
      accept_warnings: acceptWarnings,
    }),
  });
}

export function importAnalyzeStoriesArtifact({
  artifact,
  declaredFileKind = "",
  originalFilename = "",
} = {}) {
  return request("/api/analyze-stories/imports", {
    method: "POST",
    body: JSON.stringify({
      declared_file_kind: declaredFileKind || null,
      original_filename: originalFilename || null,
      artifact: artifact || {},
    }),
  });
}

export function getAnalyzeStoriesImports() {
  return request("/api/analyze-stories/imports");
}

export function getAnalyzeStoriesImport(importId) {
  return request(`/api/analyze-stories/imports/${importId}`);
}

export function revalidateAnalyzeStoriesImport(importId) {
  return request(`/api/analyze-stories/imports/${importId}/revalidate`, {
    method: "POST",
  });
}

export function validateAnalyzeStoriesBundle(importId, payload = {}) {
  return request(`/api/analyze-stories/imports/${importId}/bundle-validation`, {
    method: "POST",
    body: JSON.stringify({
      artifact_id: payload.artifactId || payload.artifact_id || null,
      linked_framework_candidate_id: payload.linkedFrameworkCandidateId || payload.linked_framework_candidate_id || null,
      linked_story_analysis_report_ref_id: payload.linkedStoryAnalysisReportRefId || payload.linked_story_analysis_report_ref_id || null,
    }),
  });
}

export function getAnalyzeStoriesBundles() {
  return request("/api/analyze-stories/bundles");
}

export function getAnalyzeStoriesBundle(bundleManifestId) {
  return request(`/api/analyze-stories/bundles/${bundleManifestId}`);
}

export function getAnalyzeStoriesBundleValidationReport(bundleManifestId) {
  return request(`/api/analyze-stories/bundles/${bundleManifestId}/validation-report`);
}

export function getAnalyzeStoriesBundleChapterInventory(bundleManifestId) {
  return request(`/api/analyze-stories/bundles/${bundleManifestId}/chapter-inventory`);
}

export function getAnalyzeStoriesBundleCrossChapterRefChecks(bundleManifestId) {
  return request(`/api/analyze-stories/bundles/${bundleManifestId}/cross-chapter-ref-checks`);
}

export function revalidateAnalyzeStoriesBundle(bundleManifestId) {
  return request(`/api/analyze-stories/bundles/${bundleManifestId}/revalidate`, {
    method: "POST",
  });
}

export function deriveAnalyzeStoriesAdapterCandidates(bundleManifestId, payload = {}) {
  return request(`/api/analyze-stories/bundles/${bundleManifestId}/adapter-derivations`, {
    method: "POST",
    acceptedStatuses: [409],
    body: JSON.stringify({
      viewer_state_ids: payload.viewerStateIds || payload.viewer_state_ids || [],
      include_candidate_families: payload.includeCandidateFamilies || payload.include_candidate_families || [],
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getAnalyzeStoriesAdapterDerivations() {
  return request("/api/analyze-stories/adapter-derivations");
}

export function getAnalyzeStoriesAdapterDerivation(derivationReportId) {
  return request(`/api/analyze-stories/adapter-derivations/${derivationReportId}`);
}

export function getAnalyzeStoriesAdapterCandidates(filters = {}) {
  const params = new URLSearchParams();
  if (filters.family) {
    params.set("family", filters.family);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.bundleManifestId || filters.bundle_manifest_id) {
    params.set("bundle_manifest_id", filters.bundleManifestId || filters.bundle_manifest_id);
  }
  if (filters.derivationReportId || filters.derivation_report_id) {
    params.set("derivation_report_id", filters.derivationReportId || filters.derivation_report_id);
  }
  const query = params.toString();
  return request(`/api/analyze-stories/adapter-candidates${query ? `?${query}` : ""}`);
}

export function getAnalyzeStoriesAdapterCandidate(candidateId) {
  return request(`/api/analyze-stories/adapter-candidates/${candidateId}`);
}

export function markAnalyzeStoriesAdapterCandidateReviewed(candidateId, safeUserNote = "") {
  return request(`/api/analyze-stories/adapter-candidates/${candidateId}/mark-reviewed`, {
    method: "POST",
    body: JSON.stringify({ safe_user_note: safeUserNote }),
  });
}

export function deferAnalyzeStoriesAdapterCandidate(candidateId, safeUserNote = "") {
  return request(`/api/analyze-stories/adapter-candidates/${candidateId}/defer`, {
    method: "POST",
    body: JSON.stringify({ safe_user_note: safeUserNote }),
  });
}

export function rejectAnalyzeStoriesAdapterCandidate(candidateId, safeUserNote = "") {
  return request(`/api/analyze-stories/adapter-candidates/${candidateId}/reject`, {
    method: "POST",
    body: JSON.stringify({ safe_user_note: safeUserNote }),
  });
}

export function buildFrameworkLibraryFromConfirmedImport(importedFrameworkDecisionId, safeUserNote = "") {
  return request("/api/framework-library/items/from-confirmed-import", {
    method: "POST",
    acceptedStatuses: [409],
    body: JSON.stringify({
      imported_framework_decision_id: importedFrameworkDecisionId,
      safe_user_note: safeUserNote,
    }),
  });
}

export function buildFrameworkLibraryFromAdapterDerivation(derivationReportId, safeUserNote = "") {
  return request("/api/framework-library/items/from-adapter-derivation", {
    method: "POST",
    acceptedStatuses: [409],
    body: JSON.stringify({
      derivation_report_id: derivationReportId,
      safe_user_note: safeUserNote,
    }),
  });
}

export function buildFrameworkLibraryFromSelectedCandidates(candidateIds = [], safeUserNote = "") {
  return request("/api/framework-library/items/from-selected-candidates", {
    method: "POST",
    acceptedStatuses: [409],
    body: JSON.stringify({
      candidate_ids: candidateIds,
      safe_user_note: safeUserNote,
    }),
  });
}

export function buildFrameworkLibraryFromVocabularyArtifact(artifact = {}, sourceRef = {}, safeUserNote = "") {
  return request("/api/framework-library/items/from-vocabulary-artifact", {
    method: "POST",
    acceptedStatuses: [409],
    body: JSON.stringify({
      artifact,
      source_ref: sourceRef,
      safe_user_note: safeUserNote,
    }),
  });
}

export function getFrameworkLibraryItems(filters = {}) {
  const params = new URLSearchParams();
  ["item_type", "source_type", "visibility", "maturity_level", "risk_level"].forEach((key) => {
    const camelKey = key.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    const value = filters[key] || filters[camelKey];
    if (value) {
      params.set(key, value);
    }
  });
  const query = params.toString();
  return request(`/api/framework-library/items${query ? `?${query}` : ""}`);
}

export function getFrameworkLibraryItem(libraryItemId) {
  return request(`/api/framework-library/items/${libraryItemId}`);
}

export function patchFrameworkLibraryItem(libraryItemId, payload = {}) {
  return request(`/api/framework-library/items/${libraryItemId}`, {
    method: "PATCH",
    body: JSON.stringify({
      visibility: payload.visibility || null,
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function archiveFrameworkLibraryItem(libraryItemId, safeUserNote = "") {
  return request(`/api/framework-library/items/${libraryItemId}/archive`, {
    method: "POST",
    body: JSON.stringify({ safe_user_note: safeUserNote }),
  });
}

export function getFrameworkLibraryPatterns(filters = {}) {
  const params = new URLSearchParams();
  if (filters.patternType || filters.pattern_type) {
    params.set("pattern_type", filters.patternType || filters.pattern_type);
  }
  if (filters.sourceType || filters.source_type) {
    params.set("source_type", filters.sourceType || filters.source_type);
  }
  const query = params.toString();
  return request(`/api/framework-library/patterns${query ? `?${query}` : ""}`);
}

export function getFrameworkLibraryCompositionRules(filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  const query = params.toString();
  return request(`/api/framework-library/composition-rules${query ? `?${query}` : ""}`);
}

export function markFrameworkLibraryCompositionRuleReviewed(ruleId, safeUserNote = "") {
  return request(`/api/framework-library/composition-rules/${ruleId}/mark-reviewed`, {
    method: "POST",
    body: JSON.stringify({ safe_user_note: safeUserNote }),
  });
}

export function rejectFrameworkLibraryCompositionRule(ruleId, safeUserNote = "") {
  return request(`/api/framework-library/composition-rules/${ruleId}/reject`, {
    method: "POST",
    body: JSON.stringify({ safe_user_note: safeUserNote }),
  });
}

export function getFrameworkLibraryMaturityRecords() {
  return request("/api/framework-library/maturity-records");
}

export function getFrameworkLibraryCopyrightSources(filters = {}) {
  const params = new URLSearchParams();
  if (filters.riskLevel || filters.risk_level) {
    params.set("risk_level", filters.riskLevel || filters.risk_level);
  }
  const query = params.toString();
  return request(`/api/framework-library/copyright-sources${query ? `?${query}` : ""}`);
}

export function createFrameworkLibraryPrivateFramework(payload = {}) {
  return request("/api/framework-library/private-frameworks", {
    method: "POST",
    body: JSON.stringify({
      title: payload.title || "Private framework collection",
      item_ids: payload.itemIds || payload.item_ids || [],
      pattern_ids: payload.patternIds || payload.pattern_ids || [],
      composition_rule_ids: payload.compositionRuleIds || payload.composition_rule_ids || [],
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getFrameworkLibraryPrivateFrameworks() {
  return request("/api/framework-library/private-frameworks");
}

export function getFrameworkLibrarySystemRecommendations() {
  return request("/api/framework-library/system-recommendations");
}

export function getFrameworkCompositionDrafts() {
  return request("/api/framework-compositions/drafts");
}

export function getFrameworkCompositionDraft(compositionId) {
  return request(`/api/framework-compositions/drafts/${encodeURIComponent(compositionId)}`);
}

export function getFrameworkCompositionGeneratorContext(compositionId) {
  return request(`/api/framework-compositions/drafts/${encodeURIComponent(compositionId)}/generator-context`);
}

export function createFrameworkCompositionDraft(payload = {}) {
  return request("/api/framework-compositions/drafts", {
    method: "POST",
    body: JSON.stringify({
      title: payload.title || "Framework composition draft",
      user_mode: payload.userMode || payload.user_mode || "original_writing",
      project_id: payload.projectId || payload.project_id || "local_project",
      full_book_framework_slots:
        payload.fullBookFrameworkSlots || payload.full_book_framework_slots || [],
      chapter_framework_slots:
        payload.chapterFrameworkSlots || payload.chapter_framework_slots || [],
    }),
  });
}

export function validateFrameworkCompositionDraft(compositionId) {
  return request(`/api/framework-compositions/drafts/${encodeURIComponent(compositionId)}/validate`, {
    method: "POST",
  });
}

export function confirmFrameworkCompositionDraft(compositionId) {
  return request(`/api/framework-compositions/drafts/${encodeURIComponent(compositionId)}/confirm`, {
    method: "POST",
  });
}

export function createAnalyzeStoriesFrameworkCandidate(importId) {
  return request(`/api/analyze-stories/imports/${importId}/framework-candidates`, {
    method: "POST",
  });
}

export function getAnalyzeStoriesFrameworkCandidates() {
  return request("/api/analyze-stories/framework-candidates");
}

export function getAnalyzeStoriesFrameworkCandidate(candidateId) {
  return request(`/api/analyze-stories/framework-candidates/${candidateId}`);
}

export function revalidateAnalyzeStoriesFrameworkCandidate(candidateId) {
  return request(`/api/analyze-stories/framework-candidates/${candidateId}/revalidate`, {
    method: "POST",
  });
}

export function createAnalyzeStoriesReportViewer(reportRefId) {
  return request("/api/analyze-stories/report-viewers", {
    method: "POST",
    body: JSON.stringify({ report_ref_id: reportRefId }),
  });
}

export function getAnalyzeStoriesReportViewerByReport(reportRefId) {
  return request(`/api/analyze-stories/reports/${reportRefId}/viewer-state`);
}

export function getAnalyzeStoriesReportViewers() {
  return request("/api/analyze-stories/report-viewers");
}

export function getAnalyzeStoriesReportViewer(viewerStateId) {
  return request(`/api/analyze-stories/report-viewers/${viewerStateId}`);
}

export function markAnalyzeStoriesReportViewerReviewed(viewerStateId) {
  return request(`/api/analyze-stories/report-viewers/${viewerStateId}/mark-reviewed`, {
    method: "POST",
  });
}

export function flagAnalyzeStoriesReportViewer(viewerStateId, note = "") {
  return request(`/api/analyze-stories/report-viewers/${viewerStateId}/flag`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
}

export function dismissAnalyzeStoriesReportViewer(viewerStateId, note = "") {
  return request(`/api/analyze-stories/report-viewers/${viewerStateId}/dismiss`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });
}

export function getImportedFrameworkWorkbench(candidateId) {
  return request(`/api/analyze-stories/framework-candidates/${candidateId}/imported-workbench`);
}

export function startImportedFrameworkEditSession(candidateId) {
  return request(`/api/analyze-stories/framework-candidates/${candidateId}/edit-sessions`, {
    method: "POST",
  });
}

export function getImportedFrameworkEditSessions() {
  return request("/api/analyze-stories/imported-framework-edit-sessions");
}

export function getImportedFrameworkEditSession(editSessionId) {
  return request(`/api/analyze-stories/imported-framework-edit-sessions/${editSessionId}`);
}

export function patchImportedFrameworkEditSession(editSessionId, payload = {}) {
  return request(`/api/analyze-stories/imported-framework-edit-sessions/${editSessionId}`, {
    method: "PATCH",
    body: JSON.stringify({
      operation: payload.operation || null,
      activation_mode: payload.activationMode || null,
      component_id: payload.componentId || null,
      chapter_index: payload.chapterIndex || null,
      patch: payload.patch || {},
      linked_macro_component_ids: payload.linkedMacroComponentIds || [],
      chapter_count: payload.chapterCount || null,
      user_input: payload.userInput || "",
      accept_warnings: Boolean(payload.acceptWarnings),
    }),
  });
}

export function validateImportedFrameworkEditSession(editSessionId) {
  return request(`/api/analyze-stories/imported-framework-edit-sessions/${editSessionId}/validate`, {
    method: "POST",
  });
}

export function buildImportedFrameworkActivationPlan(editSessionId, activationMode = "") {
  return request(`/api/analyze-stories/imported-framework-edit-sessions/${editSessionId}/activation-plan`, {
    method: "POST",
    body: JSON.stringify({
      activation_mode: activationMode || null,
    }),
  });
}

export function confirmImportedFrameworkActivationPlan(planId, payload = {}) {
  return request(`/api/analyze-stories/imported-framework-activation-plans/${planId}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      user_input: payload.userInput || "",
      accept_warnings: Boolean(payload.acceptWarnings),
    }),
  });
}

export function rejectImportedFrameworkEditSession(editSessionId, userInput = "") {
  return request(`/api/analyze-stories/imported-framework-edit-sessions/${editSessionId}/reject`, {
    method: "POST",
    body: JSON.stringify({
      user_input: userInput || "",
    }),
  });
}

export function buildCurrentChapterFramework(payload = {}) {
  return request("/api/framework-package/chapter-framework/build-current", {
    method: "POST",
    body: JSON.stringify({
      chapter_id: payload.chapterId || null,
      chapter_index: payload.chapterIndex || null,
      latest_user_intent_summary: payload.latestUserIntentSummary || "",
      previous_chapter_archive_id: payload.previousChapterArchiveId || "",
      previous_chapter_archive_status: payload.previousChapterArchiveStatus || "",
      previous_chapter_outcome_summary: payload.previousChapterOutcomeSummary || "",
      force_rebuild: Boolean(payload.forceRebuild),
    }),
  });
}

export function getCurrentChapterFrameworkBuild(chapterId = null, chapterIndex = null) {
  const params = new URLSearchParams();
  if (chapterId) {
    params.set("chapter_id", chapterId);
  }
  if (chapterIndex) {
    params.set("chapter_index", String(chapterIndex));
  }
  const query = params.toString();
  return request(`/api/framework-package/chapter-framework/current${query ? `?${query}` : ""}`);
}

export function getChapterFrameworkBuildContext(chapterFrameworkId) {
  return request(`/api/framework-package/chapter-framework/${chapterFrameworkId}/build-context`);
}

export function getChapterFrameworkBuildReasons(chapterFrameworkId) {
  return request(`/api/framework-package/chapter-framework/${chapterFrameworkId}/build-reasons`);
}

export function getCurrentWorldCanvas() {
  return request("/api/world-canvas/current");
}

export function getCurrentProjectStoryPremise() {
  return request("/api/project-story-premise/current");
}

export function generateWorldCanvas(storyIdea) {
  return request("/api/world-canvas/generate", {
    method: "POST",
    body: JSON.stringify({ story_idea: storyIdea }),
  });
}

export function reviseWorldCanvas(revisionPrompt) {
  return request("/api/world-canvas/revise", {
    method: "POST",
    body: JSON.stringify({ revision_prompt: revisionPrompt }),
  });
}

export function confirmWorldCanvas(userInput = "") {
  return request("/api/world-canvas/confirm", {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function getCurrentCharacters() {
  return request("/api/characters/current");
}

export function getCurrentCharacterDraft() {
  return request("/api/characters/draft");
}

export function generateCharacter(userPrompt, roleHint = "", storyFunctionHint = "") {
  return request("/api/characters/generate", {
    method: "POST",
    body: JSON.stringify({
      user_prompt: userPrompt,
      role_hint: roleHint,
      story_function_hint: storyFunctionHint,
    }),
  });
}

export function reviseCharacter(revisionPrompt) {
  return request("/api/characters/revise", {
    method: "POST",
    body: JSON.stringify({ revision_prompt: revisionPrompt }),
  });
}

export function confirmCharacter(userInput = "") {
  return request("/api/characters/confirm", {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function finishMainCast(userInput = "") {
  return request("/api/characters/finish-main-cast", {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function getRoles({ tier = "", status = "", includeArchived = false } = {}) {
  const params = new URLSearchParams();
  if (tier) {
    params.set("tier", tier);
  }
  if (status) {
    params.set("status", status);
  }
  if (includeArchived) {
    params.set("include_archived", "true");
  }
  const query = params.toString();
  return request(`/api/roles${query ? `?${query}` : ""}`);
}

export function createRole(payload) {
  return request("/api/roles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateRoleDraft(payload) {
  return request("/api/roles/generate", {
    method: "POST",
    body: JSON.stringify({
      user_prompt: payload.userPrompt || payload.user_prompt || "",
      target_tier: payload.targetTier || payload.target_tier || "B",
      role_hint: payload.roleHint || payload.role_hint || "",
      story_function_hint: payload.storyFunctionHint || payload.story_function_hint || "",
    }),
  });
}

export function getGeneratedRoleDraft() {
  return request("/api/roles/generated-draft");
}

export function confirmGeneratedRoleDraft(userInput = "") {
  return request("/api/roles/generated-draft/confirm", {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function clearGeneratedRoleDraft() {
  return request("/api/roles/generated-draft", {
    method: "DELETE",
  });
}

export function patchRole(characterId, payload) {
  return request(`/api/roles/${characterId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function changeRoleTier(characterId, tier, userInput = "") {
  return request(`/api/roles/${characterId}/change-tier`, {
    method: "POST",
    body: JSON.stringify({ tier, user_input: userInput }),
  });
}

export function archiveRole(characterId, reason = "", userInput = "") {
  return request(`/api/roles/${characterId}/archive`, {
    method: "POST",
    body: JSON.stringify({ reason, user_input: userInput }),
  });
}

export function buildRoleContextPreview(payload) {
  return request("/api/roles/context-preview", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getPendingRoleStateChanges() {
  return request("/api/roles/state-changes/pending");
}

export function proposeRoleStateChange(payload) {
  return request("/api/roles/state-changes/propose", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function confirmRoleStateChange(changeId, userInput = "") {
  return request(`/api/roles/state-changes/${changeId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function rejectRoleStateChange(changeId, userInput = "") {
  return request(`/api/roles/state-changes/${changeId}/reject`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function getCurrentChapterPlan() {
  return request("/api/chapter-plan/current");
}

export function generateChapterPlan(
  storyGoal,
  chapterCount = STORY_CAPACITY.defaultChapterCount,
  currentChapterIndex = 1,
  frameworkCompositionId = "",
) {
  return request("/api/chapter-plan/generate", {
    method: "POST",
    body: JSON.stringify({
      story_goal: storyGoal,
      chapter_count: chapterCount,
      current_chapter_index: currentChapterIndex,
      framework_composition_id: frameworkCompositionId || "",
    }),
  });
}

export function reviseChapterPlan(revisionPrompt) {
  return request("/api/chapter-plan/revise", {
    method: "POST",
    body: JSON.stringify({ revision_prompt: revisionPrompt }),
  });
}

export function setChapterSceneCount(chapterIndex = 1, sceneCount = STORY_CAPACITY.defaultSceneCount) {
  return request("/api/chapter-plan/set-scene-count", {
    method: "POST",
    body: JSON.stringify({
      chapter_index: chapterIndex,
      scene_count: sceneCount,
    }),
  });
}

export function repairChapterPlanSupportingRoleReferences() {
  return request("/api/chapter-plan/repair-supporting-role-references", {
    method: "POST",
  });
}

export function confirmChapterPlan(userInput = "") {
  return request("/api/chapter-plan/confirm", {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function getCurrentScene(chapterId = null, sceneIndex = null) {
  const query = new URLSearchParams();
  if (chapterId) {
    query.set("chapter_id", chapterId);
  }
  if (sceneIndex !== undefined && sceneIndex !== null && Number(sceneIndex) > 0) {
    query.set("scene_index", String(Number(sceneIndex)));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/api/scenes/current${suffix}`);
}

export function getSceneGateReadiness(sceneId) {
  return request(`/api/scenes/${encodeURIComponent(sceneId)}/gate-readiness`);
}

export function getSceneProgress(chapterId = null) {
  const query = chapterId ? `?chapter_id=${encodeURIComponent(chapterId)}` : "";
  return request(`/api/scenes/progress${query}`);
}

export function previewChapterArchive(chapterId = null, chapterIndex = null) {
  const params = new URLSearchParams();
  if (chapterId) {
    params.set("chapter_id", chapterId);
  }
  if (chapterIndex) {
    params.set("chapter_index", String(chapterIndex));
  }
  const query = params.toString();
  return request(`/api/chapter-archive/preview${query ? `?${query}` : ""}`);
}

export function archiveChapter({
  chapterId = null,
  chapterIndex = null,
  archiveMode = "stable",
  userInput = "",
  acceptWarnings = false,
} = {}) {
  return request("/api/chapter-archive/archive", {
    method: "POST",
    body: JSON.stringify({
      chapter_id: chapterId,
      chapter_index: chapterIndex,
      archive_mode: archiveMode,
      user_input: userInput,
      accept_warnings: acceptWarnings,
    }),
  });
}

export function getChapterArchiveByChapter(chapterId) {
  return request(`/api/chapter-archive/by-chapter/${chapterId}`);
}

export function listChapterArchives() {
  return request("/api/chapter-archive/list");
}

export function getStoryProgressCurrent() {
  return request("/api/story-progress/current");
}

export function previewNextChapter() {
  return request("/api/story-progress/next-chapter-preview");
}

export function prepareNextChapter(payload = {}) {
  return request("/api/story-progress/prepare-next-chapter", {
    method: "POST",
    body: JSON.stringify({
      latest_user_intent_summary: payload.latestUserIntentSummary || "",
      story_goal: payload.storyGoal || "",
      scene_count_proposal: payload.sceneCountProposal ?? null,
      acknowledge_provisional_archive: Boolean(payload.acknowledgeProvisionalArchive),
      force_rebuild: Boolean(payload.forceRebuild),
    }),
  });
}

export function confirmNextChapter(payload = {}) {
  return request("/api/story-progress/confirm-next-chapter", {
    method: "POST",
    body: JSON.stringify({
      preparation_id: payload.preparationId || "",
      scene_count: payload.sceneCount ?? null,
      confirm_chapter_plan: payload.confirmChapterPlan ?? true,
    }),
  });
}

export function confirmStoryDraftComplete(acknowledgeCompletion = true) {
  return request("/api/story-progress/confirm-story-draft-complete", {
    method: "POST",
    body: JSON.stringify({
      acknowledge_completion: Boolean(acknowledgeCompletion),
    }),
  });
}

export function generateFirstScene(chapterId = null, sceneIndex = 1) {
  return request("/api/scenes/generate-first", {
    method: "POST",
    body: JSON.stringify({
      chapter_id: chapterId,
      scene_index: sceneIndex,
    }),
  });
}

export function getCurrentSceneParticipantSelection(chapterId, sceneIndex = 1) {
  const query = new URLSearchParams({
    chapter_id: chapterId || "",
    scene_index: String(sceneIndex || 1),
  });
  return request(`/api/scene-participants/selections/current?${query.toString()}`);
}

export function refreshSceneParticipantSelection(selectionId) {
  return request(
    `/api/scene-participants/selections/${encodeURIComponent(selectionId)}/refresh`,
    { method: "POST" },
  );
}

export function confirmSceneParticipantCreationCandidate(candidateId) {
  return request(
    `/api/scene-participants/creation-candidates/${encodeURIComponent(candidateId)}/confirm`,
    { method: "POST" },
  );
}

export function rejectSceneParticipantCreationCandidate(candidateId) {
  return request(
    `/api/scene-participants/creation-candidates/${encodeURIComponent(candidateId)}/reject`,
    { method: "POST" },
  );
}

export function generateNextScene(
  chapterId = null,
  forceRefreshPacks = false,
  includeProvisional = null,
) {
  return request("/api/scenes/generate-next", {
    method: "POST",
    body: JSON.stringify({
      chapter_id: chapterId,
      force_refresh_packs: forceRefreshPacks,
      include_provisional: includeProvisional,
    }),
  });
}

export function regenerateFirstScene(
  regenerationHint = "",
  sceneId = "",
  chapterId = "",
  sceneIndex = null,
) {
  return request("/api/scenes/regenerate-first", {
    method: "POST",
    body: JSON.stringify({
      regeneration_hint: regenerationHint,
      scene_id: sceneId || null,
      chapter_id: chapterId || null,
      scene_index: Number(sceneIndex) || null,
    }),
  });
}

export function confirmSceneDraft(userInput = "") {
  return request("/api/scenes/confirm-draft", {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function getSceneRevisionCandidate(sceneId) {
  return request(`/api/scenes/${encodeURIComponent(sceneId)}/revision-candidate`);
}

export function reviseScene(sceneId, revisionPrompt, forceHardRuleOverride = false) {
  return request(`/api/scenes/${encodeURIComponent(sceneId)}/revise`, {
    method: "POST",
    body: JSON.stringify({
      revision_prompt: revisionPrompt,
      force_hard_rule_override: Boolean(forceHardRuleOverride),
    }),
  });
}

export function confirmSceneRevision(sceneId, revisionId, userInput = "") {
  return request(`/api/scenes/${encodeURIComponent(sceneId)}/confirm-revision`, {
    method: "POST",
    body: JSON.stringify({
      revision_id: revisionId,
      user_input: userInput,
      accepted_abcd_runtime_issue_ids: [],
    }),
  });
}

export function rejectSceneRevision(sceneId, revisionId, userInput = "") {
  return request(`/api/scenes/${encodeURIComponent(sceneId)}/reject-revision`, {
    method: "POST",
    body: JSON.stringify({
      revision_id: revisionId,
      user_input: userInput,
    }),
  });
}

export function commitScene(
  sceneId,
  commitType = "confirmed",
  userInput = "",
  revisionId = null,
  acceptedABCDRuntimeIssueIds = [],
) {
  return request(`/api/scenes/${sceneId}/commit`, {
    method: "POST",
    body: JSON.stringify({
      commit_type: commitType,
      user_input: userInput,
      revision_id: revisionId,
      accepted_abcd_runtime_issue_ids: acceptedABCDRuntimeIssueIds,
    }),
  });
}

export function temporaryConfirmScene(sceneId, userInput = "") {
  return request(`/api/scenes/${sceneId}/temporary-confirm`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function createMemoryUpdatePlanFromRevision(sceneId, revisionId, dryRun = false) {
  return request(`/api/memory-sync/scene/${sceneId}/plan-from-revision`, {
    method: "POST",
    body: JSON.stringify({
      revision_id: revisionId,
      dry_run: dryRun,
    }),
  });
}

export function getMemoryUpdatePlan(planId) {
  return request(`/api/memory-sync/plans/${planId}`);
}

export function confirmMemoryUpdatePlan(planId, userInput = "") {
  return request(`/api/memory-sync/plans/${planId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function applyMemoryUpdatePlan(planId) {
  return request(`/api/memory-sync/plans/${planId}/apply`, {
    method: "POST",
  });
}

export function rejectMemoryUpdatePlan(planId, userInput = "") {
  return request(`/api/memory-sync/plans/${planId}/reject`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function confirmAndApplyMemoryUpdatePlan(planId, userInput = "") {
  return request(`/api/memory-sync/plans/${planId}/confirm-and-apply`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function createModificationImpactPreview(payload = {}) {
  return request("/api/modification-impact/preview", {
    method: "POST",
    body: JSON.stringify({
      source_object_type: payload.sourceObjectType || "confirmed_scene",
      source_object_id: payload.sourceObjectId || "",
      modification_source_type: payload.modificationSourceType || "user_intent",
      modification_text: payload.modificationText || "",
      modification_summary: payload.modificationSummary || "",
      revision_id: payload.revisionId || null,
      change_summary: payload.changeSummary || [],
    }),
  });
}

export function getModificationImpactPreview(previewId) {
  return request(`/api/modification-impact/previews/${previewId}`);
}

export function listModificationImpactPreviews(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sourceObjectType) {
    params.set("source_object_type", filters.sourceObjectType);
  }
  if (filters.sourceObjectId) {
    params.set("source_object_id", filters.sourceObjectId);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  const query = params.toString();
  return request(`/api/modification-impact/previews${query ? `?${query}` : ""}`);
}

export function chooseModificationImpactOption(previewId, payload = {}) {
  return request(`/api/modification-impact/previews/${previewId}/choose`, {
    method: "POST",
    body: JSON.stringify({
      action_type: payload.actionType || "keep_current_change",
      user_input: payload.userInput || "",
      revision_prompt: payload.revisionPrompt || "",
      accept_warnings: Boolean(payload.acceptWarnings),
    }),
  });
}

export function getCurrentQualityReport() {
  return request("/api/quality-reports/current");
}

export function getContinuityState({
  sceneId = null,
  targetType = null,
  targetId = null,
  revisionId = null,
  mode = "manual",
} = {}) {
  const params = new URLSearchParams();
  if (sceneId) {
    params.set("scene_id", sceneId);
  }
  if (targetType) {
    params.set("target_type", targetType);
  }
  if (targetId) {
    params.set("target_id", targetId);
  }
  if (revisionId) {
    params.set("revision_id", revisionId);
  }
  if (mode) {
    params.set("mode", mode);
  }
  const query = params.toString();
  return request(`/api/continuity/state${query ? `?${query}` : ""}`);
}

export function getContinuityResolutionOptionsMatrix() {
  return request("/api/continuity/resolution-options/matrix");
}

export function getContinuityIssueResolutionOptions(issueId) {
  return request(`/api/continuity/issues/${issueId}/resolution-options`);
}

export function createContinuityResolutionDecision(issueId, payload = {}) {
  return request(`/api/continuity/issues/${issueId}/resolution-decisions`, {
    method: "POST",
    body: JSON.stringify({
      option_type: payload.optionType || payload.option_type || "",
      user_input: payload.userInput || payload.user_input || "",
      revision_prompt: payload.revisionPrompt || payload.revision_prompt || "",
      truth_status: payload.truthStatus || payload.truth_status || "misinformation",
      perception_type: payload.perceptionType || payload.perception_type || "",
      create_narrative_debt: Boolean(payload.createNarrativeDebt || payload.create_narrative_debt),
      user_confirmation: Boolean(payload.userConfirmation || payload.user_confirmation),
    }),
  });
}

export function rerunSceneQualityCheck(sceneId) {
  return request(`/api/quality-check/scene/${sceneId}`, {
    method: "POST",
  });
}

export function rerunRevisionQualityCheck(sceneId, revisionId) {
  return request(`/api/quality-check/scene/${sceneId}/revision/${revisionId}`, {
    method: "POST",
  });
}

export function checkSceneContinuity(sceneId, mode = "manual") {
  return request(`/api/continuity/check/scene/${sceneId}?mode=${encodeURIComponent(mode)}`, {
    method: "POST",
  });
}

export function checkSceneRevisionContinuity(sceneId, revisionId, mode = "manual") {
  return request(
    `/api/continuity/check/scene/${sceneId}/revision/${revisionId}?mode=${encodeURIComponent(mode)}`,
    { method: "POST" },
  );
}

export function listContinuityIssues(sceneId = null, targetType = null, status = null) {
  const params = new URLSearchParams();
  if (sceneId) {
    params.set("scene_id", sceneId);
  }
  if (targetType) {
    params.set("target_type", targetType);
  }
  if (status) {
    params.set("status", status);
  }
  const query = params.toString();
  return request(`/api/continuity/issues${query ? `?${query}` : ""}`);
}

export function acceptContinuityIssue(issueId, userInput = "") {
  return request(`/api/continuity/issues/${issueId}/accept`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function resolveContinuityIssue(
  issueId,
  actionType,
  userInput = "",
  revisionPrompt = "",
  truthStatus = "",
) {
  return request(`/api/continuity/issues/${issueId}/resolve`, {
    method: "POST",
    body: JSON.stringify({
      action_type: actionType,
      user_input: userInput,
      revision_prompt: revisionPrompt,
      truth_status: truthStatus,
    }),
  });
}

export function confirmPriorStoryCompletionCandidate(candidateId, userInput = "") {
  return request(`/api/continuity/prior-story-completion-candidates/${candidateId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function rejectPriorStoryCompletionCandidate(candidateId, userInput = "") {
  return request(`/api/continuity/prior-story-completion-candidates/${candidateId}/reject`, {
    method: "POST",
    body: JSON.stringify({ user_input: userInput }),
  });
}

export function getNarrativeDebts(filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.scene_id) {
    params.set("scene_id", filters.scene_id);
  }
  if (filters.chapter_id) {
    params.set("chapter_id", filters.chapter_id);
  }
  const query = params.toString();
  return request(`/api/narrative-layer/debts${query ? `?${query}` : ""}`);
}

export function getNarrativeDebt(debtId) {
  return request(`/api/narrative-layer/debts/${debtId}`);
}

export function getNarrativeDebtVisibilitySummary(filters = {}) {
  const params = new URLSearchParams();
  if (filters.scene_id) {
    params.set("scene_id", filters.scene_id);
  }
  if (filters.chapter_id) {
    params.set("chapter_id", filters.chapter_id);
  }
  const query = params.toString();
  return request(`/api/narrative-layer/debts/visibility-summary${query ? `?${query}` : ""}`);
}

export function updateNarrativeDebt(debtId, patch) {
  return request(`/api/narrative-layer/debts/${debtId}`, {
    method: "PATCH",
    body: JSON.stringify({ record: patch }),
  });
}

export function markNarrativeDebtPaidOff(debtId, payload = {}) {
  return request(`/api/narrative-layer/debts/${debtId}/mark-paid-off`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function markNarrativeDebtIntentionallyOpen(debtId, payload = {}) {
  return request(`/api/narrative-layer/debts/${debtId}/mark-intentionally-open`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function rejectNarrativeDebt(debtId, payload = {}) {
  return request(`/api/narrative-layer/debts/${debtId}/reject`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createSceneSnapshotForScene(payload = {}) {
  return request("/api/scene-snapshots/create-for-scene", {
    method: "POST",
    body: JSON.stringify({
      scene_id: payload.sceneId || payload.scene_id || "",
      snapshot_type: payload.snapshotType || payload.snapshot_type || "manual_validation",
      target_scene_id: payload.targetSceneId || payload.target_scene_id || "",
      extra_refs: payload.extraRefs || payload.extra_refs || [],
    }),
  });
}

export function getSceneSnapshot(snapshotId) {
  return request(`/api/scene-snapshots/${snapshotId}`);
}

export function listSceneSnapshotsByScene(sceneId, filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.snapshotType || filters.snapshot_type) {
    params.set("snapshot_type", filters.snapshotType || filters.snapshot_type);
  }
  const query = params.toString();
  return request(`/api/scene-snapshots/by-scene/${sceneId}${query ? `?${query}` : ""}`);
}

export function listSceneSnapshotsUsingRef(refType, refId, status = "") {
  const params = new URLSearchParams();
  params.set("ref_type", refType);
  params.set("ref_id", refId);
  if (status) {
    params.set("status", status);
  }
  return request(`/api/scene-snapshots/using-ref?${params.toString()}`);
}

export function invalidateSceneSnapshotsByRef(payload = {}) {
  return request("/api/scene-snapshots/invalidate-by-ref", {
    method: "POST",
    body: JSON.stringify({
      changed_ref_type: payload.changedRefType || payload.changed_ref_type || "",
      changed_ref_id: payload.changedRefId || payload.changed_ref_id || "",
      old_version_id: payload.oldVersionId || payload.old_version_id || "",
      new_version_id: payload.newVersionId || payload.new_version_id || "",
      reason: payload.reason || "",
    }),
  });
}

export function getSceneDependencyGraphSummary(filters = {}) {
  const params = new URLSearchParams();
  if (filters.chapterId || filters.chapter_id) {
    params.set("chapter_id", filters.chapterId || filters.chapter_id);
  }
  if (filters.sceneId || filters.scene_id) {
    params.set("scene_id", filters.sceneId || filters.scene_id);
  }
  const query = params.toString();
  return request(`/api/scene-dependency-graph/summary${query ? `?${query}` : ""}`);
}

export function createBackgroundThinkingTask(payload = {}) {
  return request("/api/background-thinking/tasks", {
    method: "POST",
    body: JSON.stringify({
      source_scene_id: payload.sourceSceneId || payload.source_scene_id || "",
      target_scene_id: payload.targetSceneId || payload.target_scene_id || "",
      target_chapter_id: payload.targetChapterId || payload.target_chapter_id || "",
      target_scene_index: payload.targetSceneIndex ?? payload.target_scene_index ?? null,
      task_type: payload.taskType || payload.task_type || "prepare_next_scene_thinking",
      input_snapshot_ids: payload.inputSnapshotIds || payload.input_snapshot_ids || [],
      execute_now: payload.executeNow ?? payload.execute_now ?? true,
      execution_strategy: payload.executionStrategy || payload.execution_strategy || "deterministic_fallback",
      budget_profile: payload.budgetProfile || payload.budget_profile || "background_standard",
    }),
  });
}

export function executeBackgroundThinkingTask(taskId, payload = {}) {
  return request(`/api/background-thinking/tasks/${taskId}/execute`, {
    method: "POST",
    body: JSON.stringify({
      execution_strategy: payload.executionStrategy || payload.execution_strategy || null,
    }),
  });
}

export function getBackgroundThinkingTask(taskId) {
  return request(`/api/background-thinking/tasks/${taskId}`);
}

export function listBackgroundThinkingTasks(filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.sourceSceneId || filters.source_scene_id) {
    params.set("source_scene_id", filters.sourceSceneId || filters.source_scene_id);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/background-thinking/tasks${query ? `?${query}` : ""}`);
}

export function listThinkingCandidates(filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.sourceSceneId || filters.source_scene_id) {
    params.set("source_scene_id", filters.sourceSceneId || filters.source_scene_id);
  }
  if (filters.taskId || filters.task_id) {
    params.set("task_id", filters.taskId || filters.task_id);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/background-thinking/candidates${query ? `?${query}` : ""}`);
}

export function getThinkingCandidate(candidateId) {
  return request(`/api/background-thinking/candidates/${candidateId}`);
}

export function getBackgroundThinkingQueueSummary(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sourceSceneId || filters.source_scene_id) {
    params.set("source_scene_id", filters.sourceSceneId || filters.source_scene_id);
  }
  const query = params.toString();
  return request(`/api/background-thinking/queue-summary${query ? `?${query}` : ""}`);
}

export function createPreModifyCandidatesFromPreview(payload = {}) {
  return request("/api/pre-modify/candidates/from-preview", {
    method: "POST",
    body: JSON.stringify({
      preview_id: payload.previewId || payload.preview_id || "",
      target_scene_ids: payload.targetSceneIds || payload.target_scene_ids || [],
      include_current_scene: Boolean(payload.includeCurrentScene || payload.include_current_scene),
      include_confirmed_targets: payload.includeConfirmedTargets ?? payload.include_confirmed_targets ?? true,
      execution_strategy: payload.executionStrategy || payload.execution_strategy || "deterministic_fallback",
    }),
  });
}

export function listPreModifyCandidates(filters = {}) {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.sourcePreviewId || filters.source_preview_id) {
    params.set("source_preview_id", filters.sourcePreviewId || filters.source_preview_id);
  }
  if (filters.targetSceneId || filters.target_scene_id) {
    params.set("target_scene_id", filters.targetSceneId || filters.target_scene_id);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/pre-modify/candidates${query ? `?${query}` : ""}`);
}

export function getPreModifyCandidate(candidateId) {
  return request(`/api/pre-modify/candidates/${candidateId}`);
}

export function getPreModifyAdjustmentPlan(planId) {
  return request(`/api/pre-modify/adjustment-plans/${planId}`);
}

export function getPreModifyImpactReason(reasonId) {
  return request(`/api/pre-modify/impact-reasons/${reasonId}`);
}

export function getPreModifySummary(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sourcePreviewId || filters.source_preview_id) {
    params.set("source_preview_id", filters.sourcePreviewId || filters.source_preview_id);
  }
  if (filters.targetSceneId || filters.target_scene_id) {
    params.set("target_scene_id", filters.targetSceneId || filters.target_scene_id);
  }
  const query = params.toString();
  return request(`/api/pre-modify/summary${query ? `?${query}` : ""}`);
}

export function getPreModifyWorkspace(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sceneId || filters.scene_id) {
    params.set("scene_id", filters.sceneId || filters.scene_id);
  }
  if (filters.chapterId || filters.chapter_id) {
    params.set("chapter_id", filters.chapterId || filters.chapter_id);
  }
  if (filters.includeStale !== undefined || filters.include_stale !== undefined) {
    params.set("include_stale", String(filters.includeStale ?? filters.include_stale));
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/pre-modify/workspace${query ? `?${query}` : ""}`);
}

export function buildPreModifyApplyPlan(candidateId, payload = {}) {
  return request(`/api/pre-modify/candidates/${candidateId}/apply-plan`, {
    method: "POST",
    body: JSON.stringify({
      cached_candidate_id: payload.cachedCandidateId || payload.cached_candidate_id || "",
      force_refresh: Boolean(payload.forceRefresh || payload.force_refresh),
    }),
  });
}

export function acceptPreModifyCandidate(candidateId, payload = {}) {
  return request(`/api/pre-modify/candidates/${candidateId}/accept`, {
    method: "POST",
    body: JSON.stringify({
      cached_candidate_id: payload.cachedCandidateId || payload.cached_candidate_id || "",
      apply_plan_id: payload.applyPlanId || payload.apply_plan_id || "",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      archive_after_accept: Boolean(payload.archiveAfterAccept || payload.archive_after_accept),
    }),
  });
}

export function rejectPreModifyCandidate(candidateId, payload = {}) {
  return request(`/api/pre-modify/candidates/${candidateId}/reject`, {
    method: "POST",
    body: JSON.stringify({
      cached_candidate_id: payload.cachedCandidateId || payload.cached_candidate_id || "",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      cache_action: payload.cacheAction || payload.cache_action || "hide",
    }),
  });
}

export function revisePreModifyCandidate(candidateId, payload = {}) {
  return request(`/api/pre-modify/candidates/${candidateId}/revise`, {
    method: "POST",
    body: JSON.stringify({
      cached_candidate_id: payload.cachedCandidateId || payload.cached_candidate_id || "",
      safe_revision_note: payload.safeRevisionNote || payload.safe_revision_note || "",
      requested_change_summary: payload.requestedChangeSummary || payload.requested_change_summary || "",
    }),
  });
}

export function deferPreModifyCandidate(candidateId, payload = {}) {
  return request(`/api/pre-modify/candidates/${candidateId}/defer`, {
    method: "POST",
    body: JSON.stringify({
      cached_candidate_id: payload.cachedCandidateId || payload.cached_candidate_id || "",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      reveal_condition: payload.revealCondition || payload.reveal_condition || "when_user_opens_scene",
      create_delayed_question: payload.createDelayedQuestion ?? payload.create_delayed_question ?? true,
      question_text: payload.questionText || payload.question_text || "",
      create_future_todo: Boolean(payload.createFutureTodo || payload.create_future_todo),
    }),
  });
}

export function registerThinkingCandidateInSceneCache(candidateId) {
  return request("/api/scene-candidate-cache/register-thinking-candidate", {
    method: "POST",
    body: JSON.stringify({ candidate_id: candidateId || "" }),
  });
}

export function registerPreModifyCandidateInSceneCache(candidateId) {
  return request("/api/scene-candidate-cache/register-pre-modify-candidate", {
    method: "POST",
    body: JSON.stringify({ candidate_id: candidateId || "" }),
  });
}

export function backfillSceneCandidateCache(payload = {}) {
  return request("/api/scene-candidate-cache/backfill", {
    method: "POST",
    body: JSON.stringify({
      target_scene_id: payload.targetSceneId || payload.target_scene_id || "",
      chapter_id: payload.chapterId || payload.chapter_id || "",
      limit: payload.limit || 200,
    }),
  });
}

export function getSceneCandidateCache(sceneId, filters = {}) {
  const params = new URLSearchParams();
  if (filters.includeStale || filters.include_stale) {
    params.set("include_stale", "true");
  }
  const query = params.toString();
  return request(`/api/scene-candidate-cache/scene/${sceneId}${query ? `?${query}` : ""}`);
}

export function getChapterCandidateCache(chapterId, filters = {}) {
  const params = new URLSearchParams();
  if (filters.includeStale || filters.include_stale) {
    params.set("include_stale", "true");
  }
  const query = params.toString();
  return request(`/api/scene-candidate-cache/chapter/${chapterId}${query ? `?${query}` : ""}`);
}

export function getCachedSceneCandidate(cachedCandidateId) {
  return request(`/api/scene-candidate-cache/candidates/${cachedCandidateId}`);
}

export function invalidateSceneCandidateCacheBySnapshot(payload = {}) {
  return request("/api/scene-candidate-cache/invalidate-by-snapshot", {
    method: "POST",
    body: JSON.stringify({
      snapshot_ids: payload.snapshotIds || payload.snapshot_ids || [],
      trigger_invalidation_id: payload.triggerInvalidationId || payload.trigger_invalidation_id || "",
      reason: payload.reason || "",
    }),
  });
}

export function invalidateSceneCandidateCacheByRef(payload = {}) {
  return request("/api/scene-candidate-cache/invalidate-by-ref", {
    method: "POST",
    body: JSON.stringify({
      changed_ref_type: payload.changedRefType || payload.changed_ref_type || "",
      changed_ref_id: payload.changedRefId || payload.changed_ref_id || "",
      trigger_invalidation_id: payload.triggerInvalidationId || payload.trigger_invalidation_id || "",
      reason: payload.reason || "",
    }),
  });
}

export function getSceneCandidateCacheSummary(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sceneId || filters.scene_id) {
    params.set("scene_id", filters.sceneId || filters.scene_id);
  }
  if (filters.chapterId || filters.chapter_id) {
    params.set("chapter_id", filters.chapterId || filters.chapter_id);
  }
  if (filters.includeStale || filters.include_stale) {
    params.set("include_stale", "true");
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/scene-candidate-cache/summary${query ? `?${query}` : ""}`);
}

export function createFutureIssue(payload = {}) {
  return request("/api/future-review/future-issues", {
    method: "POST",
    body: JSON.stringify({
      issue_type: payload.issueType || payload.issue_type || "manual_future_issue",
      source_type: payload.sourceType || payload.source_type || "manual",
      source_id: payload.sourceId || payload.source_id || "",
      target_chapter_id: payload.targetChapterId || payload.target_chapter_id || "",
      target_scene_id: payload.targetSceneId || payload.target_scene_id || "",
      target_scene_index: payload.targetSceneIndex ?? payload.target_scene_index ?? null,
      reveal_condition: payload.revealCondition || payload.reveal_condition || "manual_review",
      severity: payload.severity || "medium",
      safe_summary: payload.safeSummary || payload.safe_summary || {},
      user_visible_question_hint: payload.userVisibleQuestionHint || payload.user_visible_question_hint || "",
      related_cache_ids: payload.relatedCacheIds || payload.related_cache_ids || [],
      related_cached_candidate_ids: payload.relatedCachedCandidateIds || payload.related_cached_candidate_ids || [],
      related_invalidation_record_ids: payload.relatedInvalidationRecordIds || payload.related_invalidation_record_ids || [],
      related_candidate_ids: payload.relatedCandidateIds || payload.related_candidate_ids || [],
      related_snapshot_ids: payload.relatedSnapshotIds || payload.related_snapshot_ids || [],
      related_memory_ids: payload.relatedMemoryIds || payload.related_memory_ids || [],
      related_narrative_debt_ids: payload.relatedNarrativeDebtIds || payload.related_narrative_debt_ids || [],
      related_continuity_issue_ids: payload.relatedContinuityIssueIds || payload.related_continuity_issue_ids || [],
    }),
  });
}

export function createFutureIssueFromCachedCandidate(cachedCandidateId, revealCondition = "when_user_opens_scene") {
  return request(`/api/future-review/future-issues/from-cached-candidate/${cachedCandidateId}`, {
    method: "POST",
    body: JSON.stringify({ reveal_condition: revealCondition }),
  });
}

export function createFutureIssueFromInvalidation(invalidationRecordId, revealCondition = "when_user_opens_scene") {
  return request(`/api/future-review/future-issues/from-invalidation/${invalidationRecordId}`, {
    method: "POST",
    body: JSON.stringify({ reveal_condition: revealCondition }),
  });
}

export function backfillFutureIssuesFromCache(payload = {}) {
  return request("/api/future-review/future-issues/backfill-from-cache", {
    method: "POST",
    body: JSON.stringify({
      scene_id: payload.sceneId || payload.scene_id || "",
      chapter_id: payload.chapterId || payload.chapter_id || "",
      include_stale: payload.includeStale ?? payload.include_stale ?? true,
      limit: payload.limit || 100,
    }),
  });
}

export function getFutureIssues(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sceneId || filters.scene_id) {
    params.set("scene_id", filters.sceneId || filters.scene_id);
  }
  if (filters.chapterId || filters.chapter_id) {
    params.set("chapter_id", filters.chapterId || filters.chapter_id);
  }
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/future-review/future-issues${query ? `?${query}` : ""}`);
}

export function createDelayedQuestionFromFutureIssue(futureIssueId, payload = {}) {
  return request(`/api/future-review/future-issues/${futureIssueId}/delayed-question`, {
    method: "POST",
    body: JSON.stringify({
      reveal_condition: payload.revealCondition || payload.reveal_condition || "",
      question_text: payload.questionText || payload.question_text || "",
      context_summary: payload.contextSummary || payload.context_summary || {},
      options: payload.options || [],
    }),
  });
}

export function getReadyDelayedQuestions(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sceneId || filters.scene_id) {
    params.set("scene_id", filters.sceneId || filters.scene_id);
  }
  if (filters.chapterId || filters.chapter_id) {
    params.set("chapter_id", filters.chapterId || filters.chapter_id);
  }
  if (filters.revealCondition || filters.reveal_condition) {
    params.set("reveal_condition", filters.revealCondition || filters.reveal_condition);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/future-review/delayed-questions/ready${query ? `?${query}` : ""}`);
}

export function answerDelayedQuestion(delayedQuestionId, payload = {}) {
  return request(`/api/future-review/delayed-questions/${delayedQuestionId}/answer`, {
    method: "POST",
    body: JSON.stringify({
      selected_option_id: payload.selectedOptionId || payload.selected_option_id || "",
      answer_text: payload.answerText || payload.answer_text || "",
      decision_summary: payload.decisionSummary || payload.decision_summary || "",
      deferred_until_reveal_condition: payload.deferredUntilRevealCondition || payload.deferred_until_reveal_condition || "",
    }),
  });
}

export function getFutureTodos(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sceneId || filters.scene_id) {
    params.set("scene_id", filters.sceneId || filters.scene_id);
  }
  if (filters.chapterId || filters.chapter_id) {
    params.set("chapter_id", filters.chapterId || filters.chapter_id);
  }
  if (filters.status !== undefined) {
    params.set("status", filters.status);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/future-review/future-todos${query ? `?${query}` : ""}`);
}

export function getFutureReviewSummary(filters = {}) {
  const params = new URLSearchParams();
  if (filters.sceneId || filters.scene_id) {
    params.set("scene_id", filters.sceneId || filters.scene_id);
  }
  if (filters.chapterId || filters.chapter_id) {
    params.set("chapter_id", filters.chapterId || filters.chapter_id);
  }
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return request(`/api/future-review/summary${query ? `?${query}` : ""}`);
}

export function getBackgroundBudgetStatus() {
  return request("/api/background-budget/status");
}

export function getBackgroundBudgetProfiles() {
  return request("/api/background-budget/profiles");
}

export function getBackgroundBudgetTaskPolicies() {
  return request("/api/background-budget/task-policies");
}

export function getBackgroundBudgetUsage(filters = {}) {
  const params = new URLSearchParams();
  if (filters.limit) {
    params.set("limit", String(filters.limit));
  }
  if (filters.taskType || filters.task_type) {
    params.set("task_type", filters.taskType || filters.task_type);
  }
  if (filters.taskId || filters.task_id) {
    params.set("task_id", filters.taskId || filters.task_id);
  }
  const query = params.toString();
  return request(`/api/background-budget/usage${query ? `?${query}` : ""}`);
}

export function evaluateBackgroundBudgetTask(payload = {}) {
  return request("/api/background-budget/evaluate-task", {
    method: "POST",
    body: JSON.stringify({
      task_type: payload.taskType || payload.task_type || "",
      task_id: payload.taskId || payload.task_id || "",
      requested_profile_id: payload.requestedProfileId || payload.requested_profile_id || "",
      requested_execution_strategy: payload.requestedExecutionStrategy || payload.requested_execution_strategy || "",
      snapshot_ids: payload.snapshotIds || payload.snapshot_ids || [],
      source_object_type: payload.sourceObjectType || payload.source_object_type || "",
      source_object_id: payload.sourceObjectId || payload.source_object_id || "",
    }),
  });
}

export function getPhase6ReplayGateStatus() {
  return request("/api/phase6/replay-gate/status");
}

export function runPhase6ReplayGate(payload = {}) {
  return request("/api/phase6/replay-gate/run", {
    method: "POST",
    acceptedStatuses: [409],
    body: JSON.stringify({
      run_mode: payload.runMode || payload.run_mode || "no_stable_clean_available",
      source_import_id: payload.sourceImportId || payload.source_import_id || null,
      bundle_manifest_id: payload.bundleManifestId || payload.bundle_manifest_id || null,
      framework_candidate_id: payload.frameworkCandidateId || payload.framework_candidate_id || null,
      viewer_state_ids: payload.viewerStateIds || payload.viewer_state_ids || [],
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getPhase6ReplayGateReports() {
  return request("/api/phase6/replay-gate/reports");
}

export function getPhase6ReplayGateKnownGaps() {
  return request("/api/phase6/replay-gate/known-gaps");
}

export function getFormalApplyEligibilityStatus() {
  return request("/api/phase6/formal-apply/eligibility/status");
}

export function inspectFormalApplyEligibility(payload = {}) {
  return request("/api/phase6/formal-apply/eligibility/inspect", {
    method: "POST",
    body: JSON.stringify({
      target_type: payload.targetType || payload.target_type || "unsupported_target",
      source_type: payload.sourceType || payload.source_type || "",
      source_id: payload.sourceId || payload.source_id || "",
      source_family: payload.sourceFamily || payload.source_family || "",
      candidate_id: payload.candidateId || payload.candidate_id || null,
      project_id: payload.projectId || payload.project_id || "local_project",
      safe_note: payload.safeNote || payload.safe_note || "",
    }),
  });
}

export function getFormalApplyEligibilityTargets() {
  return request("/api/phase6/formal-apply/eligibility/targets");
}

export function getFormalApplyEligibilityReports() {
  return request("/api/phase6/formal-apply/eligibility/eligibility-reports");
}

export function getFormalApplyEligibilityBlockReasons() {
  return request("/api/phase6/formal-apply/eligibility/block-reasons");
}

export function getFormalApplyDryRunStatus() {
  return request("/api/phase6/formal-apply/dry-run/status");
}

export function createFormalApplyDryRunPlan(payload = {}) {
  return request("/api/phase6/formal-apply/dry-run/plans", {
    method: "POST",
    body: JSON.stringify({
      eligibility_report_id: payload.eligibilityReportId || payload.eligibility_report_id || "",
      target_id: payload.targetId || payload.target_id || null,
      project_id: payload.projectId || payload.project_id || "local_project",
      safe_note: payload.safeNote || payload.safe_note || "",
    }),
  });
}

export function getFormalApplyDryRunPlans() {
  return request("/api/phase6/formal-apply/dry-run/plans");
}

export function getFormalApplyDryRunPlanItems(planId) {
  return request(`/api/phase6/formal-apply/dry-run/plans/${encodeURIComponent(planId)}/items`);
}

export function getFormalApplyDryRunDiffSummaries() {
  return request("/api/phase6/formal-apply/dry-run/diff-summaries");
}

export function getFormalApplyDryRunImpactPreviews() {
  return request("/api/phase6/formal-apply/dry-run/impact-previews");
}

export function getFormalApplyDryRunSafetyChecks() {
  return request("/api/phase6/formal-apply/dry-run/safety-checks");
}

export function getFormalApplyDecisionStatus() {
  return request("/api/phase6/formal-apply/decisions/status");
}

export function getFormalApplyDecisionReadiness(planId) {
  return request(`/api/phase6/formal-apply/decisions/plans/${encodeURIComponent(planId)}/readiness`);
}

export function submitFormalApplyDecision(planId, payload = {}) {
  return request(`/api/phase6/formal-apply/decisions/plans/${encodeURIComponent(planId)}/decisions`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      decision_type: payload.decisionType || payload.decision_type || "defer",
      approved_next_step: payload.approvedNextStep || payload.approved_next_step || null,
      user_note: payload.userNote || payload.user_note || "",
      override_reason: payload.overrideReason || payload.override_reason || "",
      acknowledged_warning_codes: payload.acknowledgedWarningCodes || payload.acknowledged_warning_codes || [],
      question_text: payload.questionText || payload.question_text || "",
      rejection_reason: payload.rejectionReason || payload.rejection_reason || "",
    }),
  });
}

export function getFormalApplyDecisions() {
  return request("/api/phase6/formal-apply/decisions/decisions");
}

export function getFormalApplyDecision(decisionRecordId) {
  return request(`/api/phase6/formal-apply/decisions/decisions/${encodeURIComponent(decisionRecordId)}`);
}

export function getFormalApplyDecisionEvidenceSnapshot(decisionRecordId) {
  return request(`/api/phase6/formal-apply/decisions/decisions/${encodeURIComponent(decisionRecordId)}/evidence-snapshot`);
}

export function getFormalApplyApprovals() {
  return request("/api/phase6/formal-apply/decisions/approvals");
}

export function getFormalApplyRejections() {
  return request("/api/phase6/formal-apply/decisions/rejections");
}

export function getFormalApplyOverrides() {
  return request("/api/phase6/formal-apply/decisions/overrides");
}

export function getFormalApplyQuestions() {
  return request("/api/phase6/formal-apply/decisions/questions");
}

export function getFormalApplyQuestion(questionId) {
  return request(`/api/phase6/formal-apply/decisions/questions/${encodeURIComponent(questionId)}`);
}

export function answerFormalApplyQuestion(questionId, payload = {}) {
  return request(`/api/phase6/formal-apply/decisions/questions/${encodeURIComponent(questionId)}/answer`, {
    method: "POST",
    body: JSON.stringify({
      answer_text: payload.answerText || payload.answer_text || "",
      user_note: payload.userNote || payload.user_note || "",
    }),
  });
}

export function getFormalApplyExecutionStatus() {
  return request("/api/phase6/formal-apply/executions/status");
}

export function getFormalApplyExecutionReadiness(approvalId) {
  return request(`/api/phase6/formal-apply/executions/approvals/${encodeURIComponent(approvalId)}/readiness`);
}

export function executeFormalApplyApproval(approvalId, payload = {}) {
  return request(`/api/phase6/formal-apply/executions/approvals/${encodeURIComponent(approvalId)}/execute`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getFormalApplyExecutionResults() {
  return request("/api/phase6/formal-apply/executions/executions");
}

export function getFormalApplyExecutionResult(executionResultId) {
  return request(`/api/phase6/formal-apply/executions/executions/${encodeURIComponent(executionResultId)}`);
}

export function getFormalApplyRollbackRefs() {
  return request("/api/phase6/formal-apply/executions/rollback-refs");
}

export function getFormalApplyWriteAudits() {
  return request("/api/phase6/formal-apply/executions/write-audits");
}

export function getFormalApplyProposalStatus() {
  return request("/api/phase6/formal-apply/proposals/status");
}

export function getFormalApplyProposals() {
  return request("/api/phase6/formal-apply/proposals/");
}

export function getFormalApplyFrameworkProposals() {
  return request("/api/phase6/formal-apply/proposals/framework");
}

export function getFormalApplyChapterArchiveProposals() {
  return request("/api/phase6/formal-apply/proposals/chapter-archive");
}

export function getFormalApplyNarrativeDebtProposals() {
  return request("/api/phase6/formal-apply/proposals/narrative-debt");
}

export function getFormalApplyProposal(proposalId) {
  return request(`/api/phase6/formal-apply/proposals/items/${encodeURIComponent(proposalId)}`);
}

export function getPropagationGovernanceStatus() {
  return request("/api/phase6/propagation/status");
}

export function getPropagationExecutionReadiness(executionResultId) {
  return request(`/api/phase6/propagation/executions/${encodeURIComponent(executionResultId)}/readiness`);
}

export function reviewPropagationExecution(executionResultId, payload = {}) {
  return request(`/api/phase6/propagation/executions/${encodeURIComponent(executionResultId)}/review`, {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getPropagationImpactRecords() {
  return request("/api/phase6/propagation/impact-records");
}

export function getPropagationImpactRecord(impactRecordId) {
  return request(`/api/phase6/propagation/impact-records/${encodeURIComponent(impactRecordId)}`);
}

export function getPropagationReviewTasks(status = "") {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : "";
  return request(`/api/phase6/propagation/review-tasks${suffix}`);
}

export function markPropagationTaskReviewed(taskId, payload = {}) {
  return request(`/api/phase6/propagation/review-tasks/${encodeURIComponent(taskId)}/mark-reviewed`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      status_note: payload.statusNote || payload.status_note || "",
    }),
  });
}

export function deferPropagationTask(taskId, payload = {}) {
  return request(`/api/phase6/propagation/review-tasks/${encodeURIComponent(taskId)}/defer`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      status_note: payload.statusNote || payload.status_note || "",
    }),
  });
}

export function dismissPropagationTask(taskId, payload = {}) {
  return request(`/api/phase6/propagation/review-tasks/${encodeURIComponent(taskId)}/dismiss`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      status_note: payload.statusNote || payload.status_note || "",
    }),
  });
}

export function getPropagationRecheckPlans() {
  return request("/api/phase6/propagation/recheck-plans");
}

export function getFrameworkChangePropagationReports() {
  return request("/api/phase6/propagation/framework-reports");
}

export function getRecommendationGovernanceStatus() {
  return request("/api/phase6/recommendation-governance/status");
}

export function evaluateRecommendationEligibility(payload = {}) {
  return request("/api/phase6/recommendation-governance/evaluate", {
    method: "POST",
    acceptedStatuses: [404, 422],
    body: JSON.stringify({
      source_object_type: payload.sourceObjectType || payload.source_object_type || "framework_module_library_item",
      source_object_id: payload.sourceObjectId || payload.source_object_id || "",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getRecommendationEligibilityReports() {
  return request("/api/phase6/recommendation-governance/eligibility-reports");
}

export function getRecommendationEligibilityReport(reportId) {
  return request(`/api/phase6/recommendation-governance/eligibility-reports/${encodeURIComponent(reportId)}`);
}

export function openRecommendationReview(payload = {}) {
  return request("/api/phase6/recommendation-governance/reviews", {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      eligibility_report_id: payload.eligibilityReportId || payload.eligibility_report_id || "",
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
    }),
  });
}

export function getRecommendationReviews() {
  return request("/api/phase6/recommendation-governance/reviews");
}

export function getRecommendationReview(reviewId) {
  return request(`/api/phase6/recommendation-governance/reviews/${encodeURIComponent(reviewId)}`);
}

export function approveRecommendationCandidate(reviewId, payload = {}) {
  return request(`/api/phase6/recommendation-governance/reviews/${encodeURIComponent(reviewId)}/approve-candidate`, {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      reviewer_note: payload.reviewerNote || payload.reviewer_note || "",
      acknowledged_warning_codes: payload.acknowledgedWarningCodes || payload.acknowledged_warning_codes || [],
    }),
  });
}

export function rejectRecommendationReview(reviewId, payload = {}) {
  return request(`/api/phase6/recommendation-governance/reviews/${encodeURIComponent(reviewId)}/reject`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      reviewer_note: payload.reviewerNote || payload.reviewer_note || "",
      acknowledged_warning_codes: payload.acknowledgedWarningCodes || payload.acknowledged_warning_codes || [],
    }),
  });
}

export function requestRecommendationMoreEvidence(reviewId, payload = {}) {
  return request(`/api/phase6/recommendation-governance/reviews/${encodeURIComponent(reviewId)}/request-more-evidence`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      reviewer_note: payload.reviewerNote || payload.reviewer_note || "",
      acknowledged_warning_codes: payload.acknowledgedWarningCodes || payload.acknowledged_warning_codes || [],
    }),
  });
}

export function keepRecommendationPrivate(reviewId, payload = {}) {
  return request(`/api/phase6/recommendation-governance/reviews/${encodeURIComponent(reviewId)}/keep-private`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      reviewer_note: payload.reviewerNote || payload.reviewer_note || "",
      acknowledged_warning_codes: payload.acknowledgedWarningCodes || payload.acknowledged_warning_codes || [],
    }),
  });
}

export function keepRecommendationProjectLocal(reviewId, payload = {}) {
  return request(`/api/phase6/recommendation-governance/reviews/${encodeURIComponent(reviewId)}/keep-project-local`, {
    method: "POST",
    acceptedStatuses: [422],
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "",
      reviewer_note: payload.reviewerNote || payload.reviewer_note || "",
      acknowledged_warning_codes: payload.acknowledgedWarningCodes || payload.acknowledged_warning_codes || [],
    }),
  });
}

export function getRecommendationRiskProfiles() {
  return request("/api/phase6/recommendation-governance/risk-profiles");
}

export function getRecommendationRiskProfile(riskProfileId) {
  return request(`/api/phase6/recommendation-governance/risk-profiles/${encodeURIComponent(riskProfileId)}`);
}

export function getRecommendationPromotionDecisions() {
  return request("/api/phase6/recommendation-governance/promotion-decisions");
}

export function getRecommendationPromotionDecision(decisionId) {
  return request(`/api/phase6/recommendation-governance/promotion-decisions/${encodeURIComponent(decisionId)}`);
}

export function getReleaseGateStatus() {
  return request("/api/phase6/release-gate/status");
}

export function runReleaseGate(payload = {}) {
  return request("/api/phase6/release-gate/run", {
    method: "POST",
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "M8 release gate evidence run.",
      verifier_marker_observations: payload.verifierMarkerObservations || payload.verifier_marker_observations || [],
    }),
  });
}

export function getReleaseGateReports() {
  return request("/api/phase6/release-gate/reports");
}

export function getReleaseGateReport(reportId) {
  return request(`/api/phase6/release-gate/reports/${encodeURIComponent(reportId)}`);
}

export function getReleaseGateRegressionManifests() {
  return request("/api/phase6/release-gate/regression-manifests");
}

export function getReleaseGateRegressionManifest(manifestId) {
  return request(`/api/phase6/release-gate/regression-manifests/${encodeURIComponent(manifestId)}`);
}

export function getReleaseGateVerifierRuns() {
  return request("/api/phase6/release-gate/verifier-runs");
}

export function getReleaseGateVerifierRun(verifierRunId) {
  return request(`/api/phase6/release-gate/verifier-runs/${encodeURIComponent(verifierRunId)}`);
}

export function getReleaseGateEvidenceIndexes() {
  return request("/api/phase6/release-gate/evidence-indexes");
}

export function getReleaseGateEvidenceIndex(evidenceIndexId) {
  return request(`/api/phase6/release-gate/evidence-indexes/${encodeURIComponent(evidenceIndexId)}`);
}

export function getReleaseGateCloseoutReadinessReports() {
  return request("/api/phase6/release-gate/closeout-readiness");
}

export function getReleaseGateCloseoutReadinessReport(closeoutReportId) {
  return request(`/api/phase6/release-gate/closeout-readiness/${encodeURIComponent(closeoutReportId)}`);
}

export function getReleaseGateSafetyAuthorityAudits() {
  return request("/api/phase6/release-gate/safety-authority-audits");
}

export function getReleaseGateSafetyAuthorityAudit(auditId) {
  return request(`/api/phase6/release-gate/safety-authority-audits/${encodeURIComponent(auditId)}`);
}

export function getReleaseGateFormalFilePollutionAudits() {
  return request("/api/phase6/release-gate/formal-file-pollution-audits");
}

export function getReleaseGateFormalFilePollutionAudit(auditId) {
  return request(`/api/phase6/release-gate/formal-file-pollution-audits/${encodeURIComponent(auditId)}`);
}

export function getReleaseGateKnownResiduals() {
  return request("/api/phase6/release-gate/known-residuals");
}

export function getReleaseGateKnownResidual(residualReportId) {
  return request(`/api/phase6/release-gate/known-residuals/${encodeURIComponent(residualReportId)}`);
}

export function getPhase7ReleaseGateStatus() {
  return request("/api/phase7/release-gate/status");
}

export function runPhase7ReleaseGate(payload = {}) {
  return request("/api/phase7/release-gate/run", {
    method: "POST",
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "Phase 7 M8 release gate evidence run.",
      verifier_marker_observations: payload.verifierMarkerObservations || payload.verifier_marker_observations || [],
    }),
  });
}

export function listPhase7ReleaseGateReports() {
  return request("/api/phase7/release-gate/reports");
}

export function getPhase7ReleaseGateReport(reportId) {
  return request(`/api/phase7/release-gate/reports/${encodeURIComponent(reportId)}`);
}

export function listPhase7PluginE2EReports() {
  return request("/api/phase7/release-gate/e2e-reports");
}

export function getPhase7PluginE2EReport(e2eReportId) {
  return request(`/api/phase7/release-gate/e2e-reports/${encodeURIComponent(e2eReportId)}`);
}

export function listPhase7RegressionManifests() {
  return request("/api/phase7/release-gate/regression-manifests");
}

export function listPhase7VerifierRuns() {
  return request("/api/phase7/release-gate/verifier-runs");
}

export function listPhase7EvidenceIndexes() {
  return request("/api/phase7/release-gate/evidence-indexes");
}

export function listPhase7NoWriteAudits() {
  return request("/api/phase7/release-gate/no-write-audits");
}

export function listPhase7ArtifactVersioningAudits() {
  return request("/api/phase7/release-gate/artifact-versioning-audits");
}

export function listPhase7CheckpointAuthorityAudits() {
  return request("/api/phase7/release-gate/checkpoint-authority-audits");
}

export function listPhase7LicenseTemplateAudits() {
  return request("/api/phase7/release-gate/license-template-audits");
}

export function listPhase7ExternalProviderNoCallAudits() {
  return request("/api/phase7/release-gate/external-provider-no-call-audits");
}

export function listPhase7CloseoutReadinessReports() {
  return request("/api/phase7/release-gate/closeout-readiness");
}

export function listPhase7KnownResiduals() {
  return request("/api/phase7/release-gate/known-residuals");
}

export function getPhase8ReleaseGateStatus() {
  return request("/api/phase8/release-gate/status");
}

export function runPhase8ReleaseGate(payload = {}) {
  return request("/api/phase8/release-gate/run", {
    method: "POST",
    body: JSON.stringify({
      safe_user_note: payload.safeUserNote || payload.safe_user_note || "Phase 8 M8 product workbench closeout evidence run.",
      verifier_marker_observations: payload.verifierMarkerObservations || payload.verifier_marker_observations || [],
    }),
  });
}

export function listPhase8ReleaseGateReports() {
  return request("/api/phase8/release-gate/reports");
}

export function getPhase8ReleaseGateReport(reportId) {
  return request(`/api/phase8/release-gate/reports/${encodeURIComponent(reportId)}`);
}

export function listPhase8ProductWorkbenchE2EReports() {
  return request("/api/phase8/release-gate/e2e-reports");
}

export function getPhase8ProductWorkbenchE2EReport(e2eReportId) {
  return request(`/api/phase8/release-gate/e2e-reports/${encodeURIComponent(e2eReportId)}`);
}

export function listPhase8RegressionManifests() {
  return request("/api/phase8/release-gate/regression-manifests");
}

export function listPhase8VerifierRuns() {
  return request("/api/phase8/release-gate/verifier-runs");
}

export function listPhase8EvidenceIndexes() {
  return request("/api/phase8/release-gate/evidence-indexes");
}

export function listPhase8SecretSafetyAudits() {
  return request("/api/phase8/release-gate/secret-safety-audits");
}

export function listPhase8DemoSeedIsolationAudits() {
  return request("/api/phase8/release-gate/demo-seed-isolation-audits");
}

export function listPhase8ProgressViewModelAudits() {
  return request("/api/phase8/release-gate/progress-view-model-audits");
}

export function listPhase8DebugIsolationAudits() {
  return request("/api/phase8/release-gate/debug-isolation-audits");
}

export function listPhase8ArtifactAuthorityAudits() {
  return request("/api/phase8/release-gate/artifact-authority-audits");
}

export function listPhase8ScopeBoundaryAudits() {
  return request("/api/phase8/release-gate/scope-boundary-audits");
}

export function listPhase8CloseoutReadinessReports() {
  return request("/api/phase8/release-gate/closeout-readiness");
}

export function listPhase8KnownResiduals() {
  return request("/api/phase8/release-gate/known-residuals");
}

export function listPhase8HandoffIndexes() {
  return request("/api/phase8/release-gate/handoff-indexes");
}

export function getFinalStoryPackageReadiness() {
  return request("/api/final-story-package/readiness");
}

export function evaluateFinalStoryPackageReadiness({
  allowFixture = false,
  persist = true,
  safeUserNote = "",
} = {}) {
  return request("/api/final-story-package/readiness/evaluate", {
    method: "POST",
    body: JSON.stringify({
      allow_fixture: allowFixture,
      persist,
      safe_user_note: safeUserNote,
    }),
  });
}

export function getFinalStoryPackageReadinessGate(readinessGateId) {
  return request(`/api/final-story-package/readiness/${encodeURIComponent(readinessGateId)}`);
}

export function getFinalStoryPackageReadinessIssues(readinessGateId) {
  return request(`/api/final-story-package/readiness/${encodeURIComponent(readinessGateId)}/issues`);
}

export function exportFinalStoryPackage({
  readinessGateId,
  allowFixtureExport = false,
  exportFormat = "json_snapshot",
  safeUserNote = "",
} = {}) {
  return request("/api/final-story-package/export", {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      readiness_gate_id: readinessGateId || "",
      allow_fixture_export: Boolean(allowFixtureExport),
      export_format: exportFormat,
      safe_user_note: safeUserNote || "",
    }),
  });
}

export function getFinalStoryPackageExportRuns() {
  return request("/api/final-story-package/exports");
}

export function getFinalStoryPackageExportRun(exportRunId) {
  return request(`/api/final-story-package/exports/${encodeURIComponent(exportRunId)}`);
}

export function getFinalStoryPackageSnapshot(snapshotId) {
  return request(`/api/final-story-package/snapshots/${encodeURIComponent(snapshotId)}`);
}

export function getFinalStoryPackageSnapshotSections(snapshotId) {
  return request(`/api/final-story-package/snapshots/${encodeURIComponent(snapshotId)}/sections`);
}

export function getFinalStoryPackageEvidenceIndex(snapshotId) {
  return request(`/api/final-story-package/snapshots/${encodeURIComponent(snapshotId)}/evidence-index`);
}

export function getFinalStoryPackageSafetyAudit(snapshotId) {
  return request(`/api/final-story-package/snapshots/${encodeURIComponent(snapshotId)}/safety-audit`);
}

function downloadFilenameFromHeader(headerValue, fallbackName) {
  if (!headerValue) {
    return fallbackName;
  }
  const encodedMatch = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1].replace(/"/g, ""));
    } catch {
      return fallbackName;
    }
  }
  const quotedMatch = headerValue.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }
  const plainMatch = headerValue.match(/filename=([^;]+)/i);
  return plainMatch?.[1]?.trim() || fallbackName;
}

export async function downloadFinalStoryPackageSnapshot(snapshotId, format = "txt") {
  const safeFormat = ["txt", "markdown", "json"].includes(format) ? format : "txt";
  const response = await apiFetch()(
    `${apiBaseUrl()}/api/final-story-package/snapshots/${encodeURIComponent(snapshotId)}/download?format=${encodeURIComponent(safeFormat)}`,
    { headers: { Accept: "*/*" } },
  );
  if (!response.ok) {
    let detail = response.statusText || "Download failed";
    try {
      const body = await response.json();
      detail = body?.detail || detail;
    } catch {
      try {
        detail = (await response.text()) || detail;
      } catch {
        // Keep the HTTP status text as the safe fallback.
      }
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const blob = await response.blob();
  const filename = downloadFilenameFromHeader(
    response.headers.get("Content-Disposition"),
    `final_story.${safeFormat === "markdown" ? "md" : safeFormat}`,
  );
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
  return { filename, mediaType: blob.type, byteSize: blob.size };
}

export function createFinalStoryPackageViewerState({
  snapshotId,
  selectedSectionType = "complete_story_text",
  visiblePanels = ["preview", "sections"],
  showSourceLineage = true,
  showEvidenceIndex = true,
  showSafetyAudit = true,
} = {}) {
  return request("/api/final-story-package/viewer-states", {
    method: "POST",
    body: JSON.stringify({
      snapshot_id: snapshotId || "",
      selected_section_type: selectedSectionType,
      visible_panels: visiblePanels,
      show_source_lineage: Boolean(showSourceLineage),
      show_evidence_index: Boolean(showEvidenceIndex),
      show_safety_audit: Boolean(showSafetyAudit),
    }),
  });
}

export function getFinalStoryPackageViewerState(viewerStateId) {
  return request(`/api/final-story-package/viewer-states/${encodeURIComponent(viewerStateId)}`);
}

function queryProjectId(projectId) {
  return projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
}

export function getProductArtifactLibrary({ projectId = "" } = {}) {
  return request(`/api/product-artifacts/library${queryProjectId(projectId)}`);
}

export function getProductArtifactEntries({ projectId = "" } = {}) {
  return request(`/api/product-artifacts/entries${queryProjectId(projectId)}`);
}

export function getProductArtifactEntry(artifactEntryId, { projectId = "" } = {}) {
  return request(`/api/product-artifacts/entries/${encodeURIComponent(artifactEntryId)}${queryProjectId(projectId)}`);
}

export function getProductArtifactAuthorityBadge(artifactEntryId, { projectId = "" } = {}) {
  return request(`/api/product-artifacts/entries/${encodeURIComponent(artifactEntryId)}/authority-badge${queryProjectId(projectId)}`);
}

export function getProductArtifactSafePreview(artifactEntryId, { projectId = "" } = {}) {
  return request(`/api/product-artifacts/entries/${encodeURIComponent(artifactEntryId)}/safe-preview${queryProjectId(projectId)}`);
}

export function getProductArtifactSafetySummary(artifactEntryId, { projectId = "" } = {}) {
  return request(`/api/product-artifacts/entries/${encodeURIComponent(artifactEntryId)}/safety-summary${queryProjectId(projectId)}`);
}

export function getFinalStoryPackageProductViews({ projectId = "" } = {}) {
  return request(`/api/product-artifacts/final-story-packages${queryProjectId(projectId)}`);
}

export function getFinalStoryPackageProductView(viewId, { projectId = "" } = {}) {
  return request(`/api/product-artifacts/final-story-packages/${encodeURIComponent(viewId)}${queryProjectId(projectId)}`);
}

export function getPluginOutputProductViews({ projectId = "" } = {}) {
  return request(`/api/product-artifacts/plugin-outputs${queryProjectId(projectId)}`);
}

export function getPluginOutputProductView(viewId, { projectId = "" } = {}) {
  return request(`/api/product-artifacts/plugin-outputs/${encodeURIComponent(viewId)}${queryProjectId(projectId)}`);
}

export function getDebugVisibilityPolicy() {
  return request("/api/debug-visibility/policy");
}

export function getDebugVisibilityAudit({ projectId = "" } = {}) {
  return request(`/api/debug-visibility/audit${queryProjectId(projectId)}`);
}

export function getPlugins() {
  return request("/api/plugins");
}

export function getPlugin(pluginId) {
  return request(`/api/plugins/${encodeURIComponent(pluginId)}`);
}

export function getPluginManifest(pluginId) {
  return request(`/api/plugins/${encodeURIComponent(pluginId)}/manifest`);
}

export function getPluginInputSchema(pluginId) {
  return request(`/api/plugins/${encodeURIComponent(pluginId)}/input-schema`);
}

export function getPluginOutputSchemas(pluginId) {
  return request(`/api/plugins/${encodeURIComponent(pluginId)}/output-schemas`);
}

export function getPluginRiskDeclaration(pluginId) {
  return request(`/api/plugins/${encodeURIComponent(pluginId)}/risk-declaration`);
}

export function validatePluginInput(pluginId, {
  snapshotId,
  persistValidationReport = true,
  safeUserNote = "",
} = {}) {
  return request(`/api/plugins/${encodeURIComponent(pluginId)}/validate-input`, {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      snapshot_id: snapshotId || "",
      persist_validation_report: Boolean(persistValidationReport),
      safe_user_note: safeUserNote || "",
    }),
  });
}

export function createPluginRun(pluginId, {
  snapshotId,
  safeUserNote = "",
} = {}) {
  return request(`/api/plugins/${encodeURIComponent(pluginId)}/runs`, {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      snapshot_id: snapshotId || "",
      safe_user_note: safeUserNote || "",
    }),
  });
}

export function getPluginRuns() {
  return request("/api/plugin-runs");
}

export function getPluginRun(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}`);
}

export function cancelPluginRun(pluginRunId, { safeUserNote = "" } = {}) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/cancel`, {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      safe_user_note: safeUserNote || "",
    }),
  });
}

export function getPluginRunSteps(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/steps`);
}

export function getPluginRunCheckpoints(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/checkpoints`);
}

export function getPluginRunArtifacts(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/artifacts`);
}

export function getPluginRunSafetyReport(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/safety-report`);
}

function submitPluginCheckpoint(pluginRunId, checkpointId, action, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/checkpoints/${encodeURIComponent(checkpointId)}/${action}`, {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      safe_user_note: safeUserNote || "",
      requested_changes: Array.isArray(requestedChanges) ? requestedChanges : [],
    }),
  });
}

export function confirmPluginCheckpoint(pluginRunId, checkpointId, { safeUserNote = "" } = {}) {
  return submitPluginCheckpoint(pluginRunId, checkpointId, "confirm", { safeUserNote });
}

export function revisePluginCheckpoint(pluginRunId, checkpointId, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return submitPluginCheckpoint(pluginRunId, checkpointId, "revise", { safeUserNote, requestedChanges });
}

export function rejectPluginCheckpoint(pluginRunId, checkpointId, { safeUserNote = "" } = {}) {
  return submitPluginCheckpoint(pluginRunId, checkpointId, "reject", { safeUserNote });
}

export function deferPluginCheckpoint(pluginRunId, checkpointId, { safeUserNote = "" } = {}) {
  return submitPluginCheckpoint(pluginRunId, checkpointId, "defer", { safeUserNote });
}

export function getPluginArtifact(artifactId) {
  return request(`/api/plugin-artifacts/${encodeURIComponent(artifactId)}`);
}

export function getPluginArtifactVersions(artifactId) {
  return request(`/api/plugin-artifacts/${encodeURIComponent(artifactId)}/versions`);
}

export function getPluginArtifactVersion(artifactId, artifactVersionId) {
  return request(`/api/plugin-artifacts/${encodeURIComponent(artifactId)}/versions/${encodeURIComponent(artifactVersionId)}`);
}

export function createScriptForgingContext(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/context`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptForgingContext(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/context`);
}

export function createScriptShapePackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/shape-package`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptShapePackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/shape-package`);
}

function submitScriptForgingCheckpoint(pluginRunId, packageKind, action, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/${packageKind}/checkpoint/${action}`, {
    method: "POST",
    acceptedStatuses: [409, 422],
    body: JSON.stringify({
      safe_user_note: safeUserNote || "",
      requested_changes: Array.isArray(requestedChanges) ? requestedChanges : [],
    }),
  });
}

export function confirmScriptShapePackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "shape-package", "confirm", { safeUserNote });
}

export function reviseScriptShapePackage(pluginRunId, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "shape-package", "revise", { safeUserNote, requestedChanges });
}

export function rejectScriptShapePackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "shape-package", "reject", { safeUserNote });
}

export function deferScriptShapePackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "shape-package", "defer", { safeUserNote });
}

export function createScriptAdaptationPromptPackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/adaptation-prompt-package`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptAdaptationPromptPackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/adaptation-prompt-package`);
}

export function confirmScriptAdaptationPromptPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "adaptation-prompt-package", "confirm", { safeUserNote });
}

export function reviseScriptAdaptationPromptPackage(pluginRunId, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "adaptation-prompt-package", "revise", { safeUserNote, requestedChanges });
}

export function rejectScriptAdaptationPromptPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "adaptation-prompt-package", "reject", { safeUserNote });
}

export function deferScriptAdaptationPromptPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "adaptation-prompt-package", "defer", { safeUserNote });
}

export function getScriptForgingRiskNote(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/risk-note`);
}

export function createScriptSceneOutline(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/scene-outline`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptSceneOutline(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/scene-outline`);
}

export function confirmScriptSceneOutline(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "scene-outline", "confirm", { safeUserNote });
}

export function reviseScriptSceneOutline(pluginRunId, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "scene-outline", "revise", { safeUserNote, requestedChanges });
}

export function rejectScriptSceneOutline(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "scene-outline", "reject", { safeUserNote });
}

export function deferScriptSceneOutline(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "scene-outline", "defer", { safeUserNote });
}

export function createScriptScreenplayDraft(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/screenplay-draft`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptScreenplayDraft(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/screenplay-draft`);
}

export function confirmScriptScreenplayDraft(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "screenplay-draft", "confirm", { safeUserNote });
}

export function reviseScriptScreenplayDraft(pluginRunId, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "screenplay-draft", "revise", { safeUserNote, requestedChanges });
}

export function rejectScriptScreenplayDraft(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "screenplay-draft", "reject", { safeUserNote });
}

export function deferScriptScreenplayDraft(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "screenplay-draft", "defer", { safeUserNote });
}

export function createScriptScreenplaySelfCheck(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/screenplay-self-check`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptScreenplaySelfCheck(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/screenplay-self-check`);
}

export function createScriptScreenplayRevisionCandidate(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/screenplay-revision-candidate`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptScreenplayRevisionCandidates(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/screenplay-revision-candidates`);
}

export function createScriptStoryboardPackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/storyboard-package`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptStoryboardPackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/storyboard-package`);
}

export function confirmScriptStoryboardPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "storyboard-package", "confirm", { safeUserNote });
}

export function reviseScriptStoryboardPackage(pluginRunId, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "storyboard-package", "revise", { safeUserNote, requestedChanges });
}

export function rejectScriptStoryboardPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "storyboard-package", "reject", { safeUserNote });
}

export function deferScriptStoryboardPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "storyboard-package", "defer", { safeUserNote });
}

export function getScriptKeyStoryboards(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/key-storyboards`);
}

export function getScriptSceneStoryboards(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/scene-storyboards`);
}

export function getScriptShotList(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/shot-list`);
}

export function createScriptDigitalAssetPackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/digital-asset-package`, {
    method: "POST",
    acceptedStatuses: [409, 422],
  });
}

export function getScriptDigitalAssetPackage(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/digital-asset-package`);
}

export function confirmScriptDigitalAssetPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "digital-asset-package", "confirm", { safeUserNote });
}

export function reviseScriptDigitalAssetPackage(pluginRunId, {
  safeUserNote = "",
  requestedChanges = [],
} = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "digital-asset-package", "revise", { safeUserNote, requestedChanges });
}

export function rejectScriptDigitalAssetPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "digital-asset-package", "reject", { safeUserNote });
}

export function deferScriptDigitalAssetPackage(pluginRunId, { safeUserNote = "" } = {}) {
  return submitScriptForgingCheckpoint(pluginRunId, "digital-asset-package", "defer", { safeUserNote });
}

export function getScriptCharacterAssetList(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/asset-lists/characters`);
}

export function getScriptLocationAssetList(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/asset-lists/locations`);
}

export function getScriptPropAssetList(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/asset-lists/props`);
}

export function getScriptMotifAssetList(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/asset-lists/motifs`);
}

export function getScriptCostumeContinuityList(pluginRunId) {
  return request(`/api/plugin-runs/${encodeURIComponent(pluginRunId)}/script-forging/asset-lists/costume-continuity`);
}
