# 15 Settings / 02 外观与主题

## 页面定位

外观与主题页用于管理网站式 UI 的色卡、面板质感、动效柔和度和后期故事氛围自动换肤预览。它只影响用户界面外观，不写入故事事实，不改变项目工作流状态。

## 视觉方向

- 背景沿用 `15 Settings/assets/settings-background-v1.png`。
- 默认色卡为羊皮卷莫兰迪：
  - `#ECE7DC`
  - `#E9DDBF`
  - `#B48A78`
  - `#737D69`
  - `#80684E`
- 页面采用左侧设置分类、中间主题编辑、右侧实时预览。
- 主题卡片和色卡可交互。

## 主要交互

- 选择主题卡片：切换预览主题。
- 快速色调：从右侧 Presets 选择预设。
- 自定义色卡：使用颜色选择器编辑背景、纸张、强调、辅助、主按钮色。
- 面板通透度：调整预览面板透明度。
- 转场柔和度：在克制、柔和、丝滑三档间切换。
- 故事氛围自动主题：当前为预览/预留，不代表智能体能力已正式接入。
- 恢复默认：重置为默认羊皮卷莫兰迪。
- 更新预览：刷新右侧实时预览。
- 应用主题：后续接入时写入用户外观偏好。

## 当前接口状态

Phase 8.5 当前真实前端已具备模型设置相关接口，但外观与主题尚未看到完整后端设置 API。该页建议先由前端偏好状态承载，后续补统一用户设置接口。

建议新增或映射的接口：

```ts
getUserSettingsPreferences(): Promise<UserSettingsPreferences>
patchUserSettingsPreferences(payload: Partial<UserSettingsPreferences>): Promise<UserSettingsPreferences>
```

## 建议数据类型

```ts
type MorandiPalette = {
  background: string;
  paper: string;
  accentSoft: string;
  support: string;
  accent: string;
};

type ThemeMotionLevel = "restrained" | "soft" | "silky";

type UserAppearanceSettings = {
  themeId: "parchment_morandi" | "warm_chapter" | "cold_chapter" | "custom";
  palette: MorandiPalette;
  panelOpacity: number; // 0.48 - 0.86
  motionLevel: ThemeMotionLevel;
  storyAdaptiveThemePreviewEnabled: boolean;
  storyAdaptiveThemeEnabled?: boolean; // 后期正式接入智能体时再启用
};

type UserSettingsPreferences = {
  appearance: UserAppearanceSettings;
};
```

## 状态规则

- 默认主题必须始终可恢复。
- 用户自定义色卡只影响 UI token，不影响后端故事内容。
- AI/故事氛围主题当前只显示为预留或预览，正式接入前不得在交接中承诺智能体已能自动生成背景和色调。
- 色卡需要保持低饱和，避免影响长时间阅读。
- 应用主题后应刷新全局 CSS variables 或主题上下文。

## Codes 接入建议

- 前端可先使用 `ThemeProvider` 或全局 CSS variables 管理主题。
- `themeId` 和 `palette` 建议存入用户偏好，不存入故事事实库。
- `storyAdaptiveThemeEnabled` 后期需要依赖章节氛围分析结果，建议由独立事件驱动，不和手动主题互相覆盖。
- 当用户开启后期自动主题时，仍需保留“锁定当前主题”的开关，避免写作时界面频繁变化。
