# 15 Settings / 01 设置总览

## 页面定位

设置模块入口页。它不是表单堆叠页，而是“创作环境校准室”的总览：用户进入后应快速判断当前主题、模型、密钥策略和创作偏好是否处于可继续创作的状态。

## 视觉方向

- 背景使用 `15 Settings/assets/settings-background-v1.png`。
- 主色延续羊皮卷莫兰迪：`#ECE7DC`、`#E9DDBF`、`#B48A78`、`#737D69`、`#80684E`。
- 页面结构为左侧分类导航、中间总览卡片、右侧状态预览。
- 总览页避免展示 debug trace、runtime raw logs、专家诊断内容。

## 主要交互

- `返回总览`：回到当前项目总览页。
- 左侧分类导航：进入后续设置子页。
- 总览卡片点击：进入对应设置子页。
- `刷新状态`：重新读取设置总览数据。
- `应用当前主题`：应用当前主题配置，后续应进入外观与主题页做完整管理。
- `运行健康检查`：触发模型 Provider Profile 健康检查。

## Phase 8.5 对接接口

当前设置总览应主要聚合以下前端 helper：

```ts
getModelSettingsProviders(): Promise<ModelSettingsProviders>
getModelSettingsWorkbench(): Promise<ModelSettingsWorkbench>
getModelProviderProfiles(): Promise<ModelProviderProfiles>
getActiveModelSelection(): Promise<ActiveModelSelection>
getModelSecretPolicy(): Promise<ModelSecretPolicy>
getModelRuntimeStatus(): Promise<ModelRuntimeStatus>
runModelProviderHealthCheck(profileId: string): Promise<ModelProviderHealthCheckResult>
```

设置动作来自当前前端：

```ts
onModelSettingsAction("health-check", { profileId })
```

后续子页会继续使用：

```ts
createModelProviderProfile(payload)
patchModelProviderProfile(profileId, payload)
setActiveModelSelection(payload)
```

## 建议数据类型

```ts
type SettingsOverviewViewModel = {
  backendReady: boolean;
  currentTheme: {
    themeId: string;
    displayName: string;
    palette: string[];
    aiAdaptiveThemeEnabled?: boolean;
  };
  activeModel: {
    providerType: string;
    providerLabel: string;
    modelName: string;
    activeProfileId: string;
    activeSelectionId?: string;
    latestHealthStatus?: "healthy" | "passed" | "failed" | "missing" | "unknown" | "checking";
    deterministicFallbackAllowed?: boolean;
    usedDeterministicFallback?: boolean;
  };
  secretPolicy: {
    frontendMayShowRawKey: boolean;
    frontendMayShowKeyLastFour: boolean;
    resolvableKeyRefPrefixes: string[];
    safeDisplayKeyRefPrefixes: string[];
    safeSummary?: string;
  };
  writingPreferences: {
    requestedLanguage: "zh" | "en" | string;
    defaultChapterCount?: number;
    defaultSceneCount?: number;
    showBeginnerHints?: boolean;
  };
  warnings: string[];
  blockers: string[];
};
```

## UI 状态

- `ready`：无阻塞，允许继续创作。
- `checking`：运行健康检查时显示按钮 loading 和临时状态。
- `warning`：模型 profile 缺失、密钥引用不可解析、后端未 ready 时显示。
- `blocked`：没有可用模型且不能使用 fallback 时，右侧阻塞项计数需要大于 0，并提示进入模型配置。

## 后续接口预留

当前 Phase 8.5 已有模型设置接口，但主题偏好、创作偏好、导出偏好尚未形成完整设置 API。Codes 接入时建议先以本地 UI state 或前端偏好存储承载，再在后续版本新增统一设置接口，例如：

```ts
getUserSettingsPreferences()
patchUserSettingsPreferences(payload)
```

这些预留接口不得阻塞当前模型设置能力落地。
