# Global Product Shell - Workspace Unavailable v1

Date: 2026-07-05

Status: accepted on 2026-07-05 and copied into `99 Complete/16 Global Product Shell`.

## Files

```text
visual-drafts/global-shell-workspace-unavailable-v1.html
visual-drafts/global-shell-workspace-unavailable-v1.png
visual-drafts/global-shell-workspace-unavailable-v1-mobile.png
visual-drafts/global-shell-workspace-unavailable-v1-service-unavailable.png
```

## Design Direction

The product shell stays visible, but the workspace body changes into a calm guard state. The user can still see the project context, module navigation, unavailable reason, safe redirect, and health summary.

This draft covers three states in one interactive prototype:

- `no_project`: no active project has been selected.
- `workspace_blocked`: the selected workspace is not accessible because a prerequisite is missing.
- `service_unavailable`: backend or model service is not ready.

The HTML supports direct review links:

```text
?mode=no_project
?mode=workspace_blocked
?mode=service_unavailable
```

## Frontend Alignment

Current Phase 8.5 source components:

- `ProductAppShell.jsx` owns global navigation, status bar, selected workspace, and current project summary.
- `WorkspaceUnavailablePanel.jsx` renders when `currentAccess && !currentAccess.can_access`.
- `App.jsx` routes unavailable workspaces through `WorkspaceUnavailablePanel`.

Current API wrappers that should feed this UI:

```ts
getHealth(): Promise<{ status: string }>
getProjectStatus(): Promise<ProjectStatus>
getProjectData(): Promise<ProjectData>
getProjects(): Promise<ProjectSummary[]>
getActiveProjectSelection(): Promise<ActiveProjectSelection>
getProductNavigationState(params): Promise<ProductNavigationState>
getProductWorkspaceAccess(workspaceId, params): Promise<ProductWorkspaceAccess>
openProject(projectId): Promise<unknown>
```

Recommended UI contract:

```ts
type WorkspaceAvailabilityStatus =
  | "available"
  | "needs_setup"
  | "blocked"
  | "hidden"
  | "unavailable";

type ProductWorkspaceAccess = {
  workspace_id: string;
  can_access: boolean;
  availability_status: WorkspaceAvailabilityStatus;
  blocked_reason?: string;
  required_next_step?: string;
  safe_redirect_workspace_id?: string;
};

type WorkspaceUnavailableViewModel = {
  access: ProductWorkspaceAccess;
  workspace?: {
    workspace_id: string;
    display_name: string;
    route_key?: string;
  };
  project?: {
    project_id?: string;
    title?: string;
    origin_badge_label?: string;
  } | null;
  backendReady: boolean;
  modelGatewayStatus?: string | null;
  modelRuntimeStatus?: string | null;
  lastLoadedAt?: string;
};
```

## Interaction Notes

- Primary action follows `safe_redirect_workspace_id`; default fallback is `home`.
- Secondary action should return to project list or current project overview depending on the failure type.
- “重新检测” should refresh health, product navigation state, and workspace access.
- Locked navigation items remain visible but muted, so users understand that the system is gated by prerequisites rather than missing features.
