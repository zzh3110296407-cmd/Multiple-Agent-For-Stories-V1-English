# 15 Settings / 04 当前模型与健康检查

## 页面定位

当前模型与健康检查页用于确认“现在创作会调用哪个模型”以及“当前模型是否可用”。它不负责编辑 Provider Profile，编辑入口应回到 `03 模型配置`。

## 视觉方向

- 背景沿用 `15 Settings/assets/settings-background-v1.png`。
- 主结构为左侧设置分类、中间健康检查工作台、右侧检查报告与修复入口。
- 页面强调可读结论，不展示 raw runtime calls、trace、真实密钥或内部错误堆栈。

## 主要交互

- `刷新状态`：重新读取当前激活模型、网关、运行时、密钥策略。
- `检查 Provider`：触发当前 Profile 健康检查。
- `检查 Runtime`：触发模型运行时健康检查。
- `运行完整检查`：依次覆盖服务商档案、模型运行时、密钥策略、回退保护。
- 检查范围切换：完整检查 / Provider / Runtime。
- 健康卡片点击：查看对应检查项的简要说明或后续修复入口。
- `前往模型配置`：进入 03 模型配置修改 Provider Profile。

## Phase 8.5 已有接口

来自 `frontend/src/api/projectApi.js`：

```ts
getModelGatewayStatus(): Promise<ModelGatewayStatus>
getModelRuntimeStatus(): Promise<ModelRuntimeStatus>
getModelRuntimeCalls(limit?: number): Promise<ModelRuntimeCallList>
getModelRuntimeErrors(limit?: number): Promise<ModelRuntimeErrorList>
runModelRuntimeHealthCheck(): Promise<ModelRuntimeHealthCheckResult>
getModelSettingsProviders(): Promise<ModelSettingsProviders>
getModelSettingsWorkbench(): Promise<ModelSettingsWorkbench>
getModelProviderProfiles(): Promise<ModelProviderProfiles>
runModelProviderHealthCheck(profileId: string): Promise<ModelProviderHealthCheckResult>
getActiveModelSelection(): Promise<ActiveModelSelection>
getModelSecretPolicy(): Promise<ModelSecretPolicy>
```

当前页需要调用的动作：

```ts
onModelSettingsAction("health-check", { profileId })
runModelRuntimeHealthCheck()
```

## 建议 ViewModel

```ts
type ModelHealthViewModel = {
  activeModel: {
    providerType: string;
    providerLabel: string;
    modelName: string;
    activeProfileId: string;
    activeSelectionId?: string;
  };
  providerHealth: {
    status: "healthy" | "passed" | "failed" | "missing" | "unknown" | "checking";
    latestCheckedAt?: string;
    keyPresence: "configured" | "missing" | "not_required" | "unsupported_reference";
  };
  runtimeHealth: {
    status: "healthy" | "failed" | "missing" | "unknown" | "checking";
    gatewayConfigured: boolean;
    recentCallAvailable: boolean;
    recentErrorCount?: number;
  };
  secretPolicy: {
    frontendMayShowRawKey: boolean;
    frontendMayShowKeyLastFour: boolean;
    resolvableKeyRefPrefixes: string[];
    safeDisplayKeyRefPrefixes: string[];
  };
  fallback: {
    deterministicFallbackAvailable: boolean;
    deterministicFallbackAllowed: boolean;
    usedDeterministicFallback: boolean;
    realModelRequired: boolean;
  };
  warnings: string[];
  blockers: string[];
};
```

## 状态规则

- `healthy`：Provider 与 Runtime 均可用，无 blockers。
- `warning`：允许 fallback、runtime 有近期错误、或者 secret 引用需用户确认。
- `blocked`：active profile 缺失、profile disabled、key missing、gateway 未配置、runtime health failed。
- `checking`：检查中，按钮进入 loading，避免重复提交。

## 用户可见文案规则

- 用户只需要看到结论、影响和修复入口。
- 不展示真实 API key。
- 不展示 raw stack trace。
- 不把 `getModelRuntimeCalls` / `getModelRuntimeErrors` 的原始请求正文直接展示给普通用户。
- 检查失败时优先提示进入 `03 模型配置` 或 `05 密钥与安全`。

## Codes 接入注意

- Provider 检查和 Runtime 检查是不同接口，不能混成一个状态。
- 检查完成后需要刷新：
  - `getModelSettingsWorkbench`
  - `getActiveModelSelection`
  - `getModelProviderProfiles`
  - `getModelGatewayStatus`
  - `getModelRuntimeStatus`
  - `getModelSecretPolicy`
- 如果 `deterministicFallbackAllowed === true`，UI 可显示 warning，但不应阻止用户继续。
- 如果 `realModelRequired === true` 且真实模型不可用，UI 必须显示 blocked。
