# 15 Settings / 05 密钥与安全

## 页面定位

密钥与安全页用于向用户解释和检查模型密钥的安全边界：哪些引用可以显示、哪些引用可以解析、真实密钥不能出现在哪里，以及配置缺失时应如何处理。

该页不是密钥输入页。用户不应在这里粘贴真实 API key；修改 `apiKeyRef` 应返回 `03 模型配置`。

## 视觉方向

- 背景沿用 `15 Settings/assets/settings-background-v1.png`。
- 主结构为左侧设置分类、中间密钥策略和引用列表、右侧策略摘要与审查结果。
- 文案保持明确、克制，不恐吓用户。

## 主要交互

- `刷新策略`：重新读取 `getModelSecretPolicy()` 和当前 provider profiles。
- `检查引用`：检查当前 `apiKeyRef` 是否符合安全引用规则。
- `前往模型配置`：进入 03 模型配置修改 `apiKeyRef`。
- `运行安全检查`：聚合检查原始密钥泄露、不安全引用、缺失环境变量和阻塞项。
- 点击策略卡片：展示对应策略说明。
- 点击模型密钥引用行：展示引用检查反馈，不读取、不展示真实 key。

## Phase 8.5 已有接口

来自 `frontend/src/api/projectApi.js`：

```ts
getModelSecretPolicy(): Promise<ModelSecretPolicy>
getModelProviderProfiles(): Promise<ModelProviderProfiles>
getModelSettingsWorkbench(): Promise<ModelSettingsWorkbench>
runModelProviderHealthCheck(profileId: string): Promise<ModelProviderHealthCheckResult>
```

可结合：

```ts
getModelRuntimeStatus(): Promise<ModelRuntimeStatus>
getModelRuntimeErrors(limit?: number): Promise<ModelRuntimeErrorList>
```

但普通用户界面不得直接展示 raw runtime errors。

## 当前后端契约

来自 `backend/models/model_settings.py`：

```ts
type ModelSecretPolicy = {
  resolvable_key_ref_prefixes: string[]; // 默认 ["env:"]
  safe_display_key_ref_prefixes: string[]; // 默认 ["env:", "secret:", "runtime:"]
  unsupported_safe_reference_prefixes: string[]; // 默认 ["secret:", "runtime:"]
  raw_key_storage_disabled: boolean; // true
  forbidden_storage_targets: string[];
  frontend_may_show_key_presence: boolean; // true
  frontend_may_show_raw_key: boolean; // false
  frontend_may_show_key_last_four: boolean; // false
  safe_summary: string;
};
```

当前服务端 summary：

```text
当前 Phase 8.5 只解析 `env:` 密钥引用。
前端可以显示 configured / missing 状态，但永远不能显示真实密钥。
```

## 展示规则

- 可展示：`configured`、`missing`、`not required`、`unsupported reference`。
- 可展示：`env:QWEN_API_KEY` 这类安全引用。
- 不可展示：真实 API key。
- 不可展示：真实 key 末四位。
- 不可展示：Authorization header。
- 不可展示：包含密钥、prompt、raw response 的原始 runtime 错误。

## 禁止写入边界

UI 需要显式表达这些目标不得存储真实密钥：

- story data
- memory
- prompt snapshot
- runtime log
- debug export
- Final Story Package
- Plugin Output Artifact
- frontend localStorage
- frontend source/build artifact

## 建议 ViewModel

```ts
type SecretSecurityViewModel = {
  policy: ModelSecretPolicy;
  providerKeyRefs: Array<{
    profileId: string;
    providerType: string;
    displayName: string;
    apiKeyRef: string;
    keyPresence: "configured" | "missing" | "not_required" | "unsupported_reference";
    resolvable: boolean;
    safeToDisplay: boolean;
  }>;
  audit: {
    rawKeyLeakCount: number;
    unsafeRefCount: number;
    missingEnvCount: number;
    blockerCount: number;
  };
};
```

## Codes 接入注意

- 前端永远不要把真实 key 写入 localStorage、URL、console、artifact、export。
- 输入框若允许编辑，只允许填写引用值，例如 `env:QWEN_API_KEY`。
- 对 `secret:`、`runtime:` 这类安全显示前缀，当前 Phase 8.5 应显示为“安全显示但暂不可解析”。
- 检查失败时优先引导到 `03 模型配置` 修改引用，而不是让用户粘贴真实 key。
- 若后续引入真正 secret manager，应新增后端解析能力，UI 仍然只显示引用名。
