# 15 Settings / 03 模型配置

## 页面定位

模型配置页用于管理 Phase 8.5 当前真实前端已有的模型连接能力：Provider Profile、当前模型选择、健康检查和安全密钥引用。

该页面向用户，不展示 runtime calls、错误 trace 或调试中心内容。调试细节应保留在内部 Debug Workspace。

## 视觉方向

- 背景沿用 `15 Settings/assets/settings-background-v1.png`。
- 版式为左侧设置分类、中间 Profile 列表与编辑区、右侧当前模型和安全策略状态。
- 所有输入区域使用完整边框，不使用下划线输入。

## 主要交互

- 选择 Profile：载入表单。
- 选择 Provider：切换 `qwen`、`deepseek`、`local` 默认字段。
- 新建 Profile：清空 `profileId` 并保留当前 provider 默认值。
- 更新 Profile：提交 `patch-profile`。
- 新增 Profile：当 `profileId` 为空时提交 `create-profile`。
- 设为当前：提交 `set-active`。
- 健康检查：提交 `health-check`。
- 启用 Profile：改变 `enabled`；关闭后不能设为当前模型。

## Phase 8.5 已有接口

来自 `frontend/src/api/projectApi.js`：

```ts
getModelSettingsProviders(): Promise<ModelSettingsProviders>
getModelSettingsWorkbench(): Promise<ModelSettingsWorkbench>
createModelProviderProfile(payload): Promise<ModelProviderProfile>
getModelProviderProfiles(): Promise<ModelProviderProfiles>
getModelProviderProfile(profileId: string): Promise<ModelProviderProfile>
patchModelProviderProfile(profileId: string, payload): Promise<ModelProviderProfile>
runModelProviderHealthCheck(profileId: string): Promise<ModelProviderHealthCheckResult>
setActiveModelSelection(payload): Promise<ActiveModelSelection>
getActiveModelSelection(): Promise<ActiveModelSelection>
getModelSecretPolicy(): Promise<ModelSecretPolicy>
```

当前 `App.jsx` 动作分发：

```ts
onModelSettingsAction("create-profile", payload)
onModelSettingsAction("patch-profile", { profileId, ...payload })
onModelSettingsAction("set-active", {
  providerProfileId,
  selectedBy: "user",
  deterministicFallbackAllowed: true,
  realModelRequired: false
})
onModelSettingsAction("health-check", { profileId })
```

## payload 契约

```ts
type ModelProviderProfileInput = {
  providerType: "qwen" | "deepseek" | "local" | string;
  displayName: string;
  baseUrl: string;
  modelName: string;
  apiKeyRef: string;
  enabled: boolean;
};

type PatchModelProviderProfileInput = Partial<{
  displayName: string;
  baseUrl: string;
  modelName: string;
  apiKeyRef: string;
  enabled: boolean;
}>;

type SetActiveModelSelectionInput = {
  providerProfileId: string;
  selectedBy: "user";
  deterministicFallbackAllowed: boolean;
  realModelRequired: boolean;
};
```

## 数据展示规则

- `provider_type === "local"` 时密钥显示 `not required`。
- `api_key_configured === true` 时显示 `configured`。
- `apiKeyRef` 以 `env:` 开头时可显示引用名，但不得显示真实 key。
- `secret:` 或 `runtime:` 引用当前前端可显示为不支持引用或需配置。
- 生产环境建议隐藏 `local` provider；开发环境可显示。

## 状态规则

- `ready`：有可用 active profile 且无 blockers。
- `checking`：健康检查进行中。
- `blocked`：无可用模型、后端未 ready、profile disabled 或 key missing。
- `warning`：fallback、mock provider 或密钥引用不可解析。

## Codes 接入注意

- 表单字段要和现有 `ModelSettingsWorkspace.jsx` 保持一致，避免二次字段转换。
- 真实密钥不得进入 React state 作为明文展示；前端只保存和显示 `apiKeyRef`。
- 设为当前前必须检查 `enabled`。
- 健康检查失败时应保留用户输入，不要清空表单。
- 创建/更新/设为当前/健康检查后需要刷新：
  - `getModelSettingsProviders`
  - `getModelSettingsWorkbench`
  - `getModelProviderProfiles`
  - `getActiveModelSelection`
  - `getModelSecretPolicy`
  - `getModelRuntimeStatus`
