const ROOT = "/confirmed-ui/";

const SETTINGS_NAV_ACTIONS = [
  { match: ["设置总览"], to: "settings-overview", actionId: "settings.workbench" },
  { match: ["外观与主题"], to: "settings-appearance", actionId: "settings.workbench" },
  { match: ["模型配置"], to: "settings-model", actionId: "settings.workbench" },
  { match: ["当前模型"], to: "settings-health", actionId: "settings.activeModel" },
  { match: ["密钥与安全"], to: "settings-secrets", actionId: "settings.secretPolicy" },
  { match: ["创作偏好"], to: "settings-preferences", actionId: "settings.workbench" },
];

function page(id, title, file, actions = []) {
  return { id, title, src: `${ROOT}${encodeURI(file)}`, actions };
}

export const CONFIRMED_PAGES = [
  page("opening", "开场动画", "00 Opening Animation/opening-animation-live-final-v1.html", [
    { match: ["进入", "跳过"], to: "home" },
  ]),
  page("home", "主页", "_runtime/home-confirmed.html", [
    { selector: ".start", match: ["开始创作"], to: "start-popout" },
    { selector: ".works", match: ["作品集"], to: "projects", actionId: "projects.refresh" },
    { selector: ".import", match: ["导入故事"], to: "framework", actionId: "navigation.framework" },
    { selector: ".ideas", match: ["灵感库"], to: "template-demo" },
    { selector: ".materials", match: ["创作资料库"], to: "template-demo" },
    { selector: ".guide", match: ["新手引导"], to: "current-project" },
    { selector: ".settings", match: ["设置"], to: "settings-overview", actionId: "settings.workbench" },
  ]),
  page("start-popout", "开始创作弹出层", "01 Main Page/01 Start Creation Popout/start-creation-popout-animation-final-v1.html", [
    { selector: ".left", match: ["新创作"], to: "project-create", actionId: "navigation.createProject" },
    { selector: ".center", match: ["继续创作"], to: "projects", actionId: "projects.refresh" },
    { selector: ".right", match: ["历史创作"], to: "projects", actionId: "projects.refresh" },
  ]),
  page("project-create", "项目创建", "02 Project Creation/visual-drafts/project-creation-final-v1.html", [
    { selector: ".back", match: ["返回主页"], to: "home" },
    { selector: "#create-button", match: ["创建空白档案", "生成草稿", "确认项目"], to: "story-setup-entry", actionId: "project.createRequest" },
  ]),
  page("projects", "项目列表", "03 Projects And Works/visual-drafts/projects-and-works-final-v1.html", [
    { match: ["返回", "返回主页"], to: "home" },
    { match: ["新故事", "新建", "从模板开始"], to: "project-create" },
    { match: ["继续", "详细", "进入"], to: "current-project", actionId: "projects.openSelected" },
  ]),
  page("current-project", "当前项目总览", "04 Current Project/visual-drafts/current-project-overview-final-v1.html", [
    { match: ["模板与演示"], to: "template-demo", actionId: "navigation.templateDemo" },
    { match: ["Framework", "编排"], to: "framework", actionId: "navigation.framework" },
    { match: ["故事设定"], to: "story-setup-entry", actionId: "navigation.storySetup" },
    { match: ["世界画布"], to: "world-entry", actionId: "navigation.worldCanvas" },
    { match: ["角色主轴"], to: "character-entry", actionId: "navigation.characters" },
    { match: ["章节计划"], to: "chapter-source", actionId: "navigation.chapterPlan" },
    { match: ["场景写作"], to: "scene-entry", actionId: "navigation.scene" },
    { match: ["最终输出"], to: "final-entry", actionId: "navigation.finalOutputs" },
    { match: ["插件输出"], to: "plugin-entry", actionId: "navigation.pluginOutputs" },
    { match: ["设置"], to: "settings-overview", actionId: "settings.workbench" },
  ]),
  page("template-demo", "模板与演示", "05 Template Demo/visual-drafts/template-demo-final-v1.html", [
    { match: ["返回总览"], to: "current-project" },
    { match: ["实例化", "使用模板"], to: "framework", actionId: "template.validateAndInstantiate" },
    { match: ["运行演示"], to: "current-project", actionId: "template.runDemo" },
  ]),
  page("framework", "Framework 编排", "06 Framework Composition/visual-drafts/framework-composition-final-v1.html", [
    { match: ["返回总览"], to: "current-project" },
    { match: ["模板库", "Library"], to: "framework-library", actionId: "framework.library" },
    { match: ["分析器", "导入故事"], to: "import-source", actionId: "navigation.analyzeStories" },
    { match: ["导入编辑"], to: "imported-session", actionId: "framework.openImportedSession" },
    { match: ["确认", "下一步", "进入章节计划"], to: "chapter-source", actionId: "framework.validateAndConfirm" },
  ]),
  page("framework-library", "Framework Library", "06 Framework Composition/02 Framework Library/visual-drafts/framework-library-final-v1.html", [
    { match: ["返回", "编排"], to: "framework" },
    { match: ["加入", "创建", "使用"], to: "framework", actionId: "framework.libraryFromCandidates" },
  ]),
  page("imported-session", "导入编辑会话", "06 Framework Composition/03 Imported Edit Session/visual-drafts/imported-edit-session-final-v1.html", [
    { match: ["返回", "回到编排"], to: "framework" },
    { match: ["确认", "激活"], to: "framework", actionId: "framework.confirmActivationPlan" },
  ]),
  page("import-source", "导入源", "07 Import Story Analyzer/01 Import Source/visual-drafts/import-source-v1.html", [
    { match: ["返回 Framework", "返回"], to: "framework" },
    { match: ["提交", "开始分析", "导入"], to: "analyzing", actionId: "analyze.import" },
  ]),
  page("analyzing", "分析中", "07 Import Story Analyzer/02 Analyzing/visual-drafts/analyzing-v1.html", [
    { match: ["返回导入源"], to: "import-source" },
    { match: ["查看结果", "完成", "继续"], to: "analysis-result", actionId: "analyze.refresh" },
  ]),
  page("analysis-result", "分析结果总览", "07 Import Story Analyzer/03 Analysis Result Overview/visual-drafts/analysis-result-overview-v1.html", [
    { match: ["返回分析中"], to: "analyzing" },
    { match: ["候选", "生成 Framework"], to: "framework-candidate", actionId: "analyze.createCandidate" },
  ]),
  page("framework-candidate", "Framework 候选选择", "07 Import Story Analyzer/04 Framework Candidate Selection/visual-drafts/framework-candidate-selection-v1.html", [
    { match: ["返回结果"], to: "analysis-result" },
    { selector: "#primaryButton", match: ["开始导入编辑会话", "选择此候选", "编辑会话"], to: "imported-session", actionId: "analyze.startEditSession" },
    { match: ["确认", "使用候选"], to: "framework", actionId: "analyze.markCandidateReviewed" },
  ]),
  page("story-setup-entry", "故事设定入口", "08 Story Setup/01 Setup Entry/visual-drafts/story-setup-entry-v1.html", [
    { match: ["返回总览"], to: "current-project" },
    { selector: "#loadPrompt", match: ["载入项目提示词"], actionId: "storySetup.loadProjectPrompt" },
    { selector: "#generateButton", match: ["生成", "开始"], to: "story-setup-generating", actionId: "storySetup.createPrompt" },
  ]),
  page("story-setup-generating", "故事设定生成中", "08 Story Setup/02 Generating/visual-drafts/story-setup-generating-v1.html", [
    { selector: "#reviewButton", match: ["查看", "完成", "继续"], to: "story-setup-review", actionId: "storySetup.current" },
  ]),
  page("story-setup-review", "故事设定草案审阅", "08 Story Setup/03 Draft Review/visual-drafts/story-setup-draft-review-v1.html", [
    { match: ["缺失", "补充"], to: "story-setup-missing" },
    { match: ["审查", "决策", "确认"], to: "story-setup-decision" },
  ]),
  page("story-setup-missing", "故事设定缺失信息处理", "08 Story Setup/04 Missing Information Handling/visual-drafts/story-setup-missing-info-v1.html", [
    { selector: ".mini-save, #saveButton", match: ["保存回答", "更新回答"], to: "story-setup-missing", actionId: "storySetup.answerQuestion" },
    { match: ["返回草案", "回到草案"], to: "story-setup-review" },
  ]),
  page("story-setup-decision", "故事设定审查与决策", "08 Story Setup/05 Review And Decision/visual-drafts/story-setup-review-decision-v1.html", [
    { match: ["修订"], to: "story-setup-generating", actionId: "storySetup.reviseDecision" },
    { selector: "#recordButton", match: ["记录", "确认"], to: "story-setup-handoff", actionId: "storySetup.confirmDecision" },
  ]),
  page("story-setup-handoff", "故事设定交接与初始化", "08 Story Setup/06 Handoff Initialization/visual-drafts/story-setup-handoff-initialization-v1.html", [
    { selector: "#createButton", match: ["创建交接包"], actionId: "storySetup.createHandoff" },
    { selector: "#bootstrapButton", match: ["初始化工作台"], actionId: "storySetup.bootstrapHandoff" },
    { selector: "#enterButton", match: ["进入目标工作台", "进入世界画布工作台"], to: "world-entry" },
  ]),
  page("world-entry", "世界画布入口", "09 World Canvas/01 Source Premise And Generation Entry/visual-drafts/world-canvas-source-premise-entry-v1.html", [
    { selector: "#backButton", match: ["返回总览"], to: "current-project" },
    { selector: "#generateButton", match: ["生成世界画布草案", "进入生成中"], to: "world-generating", actionId: "world.generate" },
  ]),
  page("world-generating", "世界画布生成中", "09 World Canvas/02 Generating/visual-drafts/world-canvas-generating-v1.html", [
    { match: ["查看", "完成", "审阅"], to: "world-review", actionId: "world.current" },
  ]),
  page("world-review", "世界画布草案审阅", "09 World Canvas/03 Draft Review/visual-drafts/world-canvas-draft-review-v1.html", [
    { selector: "#problemButton", match: ["处理问题", "缺口", "冲突"], to: "world-gap", actionId: "world.current" },
    { selector: "#reviseButton", match: ["修订草案", "修订"], to: "world-revision" },
    { selector: "#confirmButton", match: ["确认草案", "确认"], to: "world-confirm", actionId: "world.confirm" },
  ]),
  page("world-gap", "世界画布缺口与冲突处理", "09 World Canvas/04 Gap And Conflict Handling/visual-drafts/world-canvas-gap-conflict-handling-v1.html", [
    { selector: "#reviewButton", match: ["返回草案审阅"], to: "world-review" },
    { selector: "#saveButton", match: ["提交处理并返回审阅", "保存处理"], to: "world-review", actionId: "world.revise" },
    { selector: "#continueButton", match: ["返回草案审阅", "继续确认"], to: "world-review" },
  ]),
  page("world-revision", "修订世界草案", "09 World Canvas/05 Draft Revision/visual-drafts/world-canvas-draft-revision-v1.html", [
    { match: ["提交修订", "重新生成"], to: "world-generating", actionId: "world.revise" },
  ]),
  page("world-confirm", "确认世界事实", "09 World Canvas/06 Confirm World Facts/visual-drafts/world-canvas-confirm-world-facts-v1.html", [
    { selector: "#confirmButton", match: ["进入角色", "角色主轴"], to: "character-entry", actionId: "navigation.characters" },
  ]),
  page("character-entry", "角色主轴入口", "10 Character Spine/01 Character Spine Entry/visual-drafts/character-spine-entry-v1.html", [
    { match: ["返回总览"], to: "current-project" },
    { selector: "#generateButton", match: ["生成角色", "生成草案", "生成"], to: "character-generating", actionId: "characters.generate" },
    { match: ["档案库"], to: "role-library", actionId: "roles.refresh" },
  ]),
  page("character-generating", "角色生成中", "10 Character Spine/02 Generating/visual-drafts/character-spine-generating-v1.html", [
    { selector: "#reviewButton", match: ["进入草案审阅", "查看", "完成", "草案"], to: "character-review", actionId: "characters.current" },
  ]),
  page("character-review", "角色草案审阅", "10 Character Spine/03 Draft Review/visual-drafts/character-spine-draft-review-v1.html", [
    { selector: "#missingButton", match: ["处理缺口", "缺失"], to: "character-missing" },
    { selector: "#reviseToggle", match: ["修订草案", "修订"], to: "character-revision" },
    { selector: "#confirmButton, #sideConfirm", match: ["确认草案", "确认"], to: "character-confirm", actionId: "characters.confirm" },
  ]),
  page("character-conflict", "关系与冲突处理", "10 Character Spine/04 Relationship Conflict Handling/visual-drafts/character-spine-conflict-handling-v1.html", [
    { match: ["状态变更"], to: "a-tier-state-change", actionId: "roles.proposeStateChange" },
    { match: ["回到", "审阅"], to: "character-review" },
  ]),
  page("character-missing", "角色缺失信息处理", "10 Character Spine/05 Missing Information Handling/visual-drafts/character-spine-missing-info-v1.html", [
    { match: ["提交", "完成"], to: "character-review", actionId: "characters.revise" },
  ]),
  page("character-revision", "修订角色草案", "10 Character Spine/06 Character Draft Revision/visual-drafts/character-spine-draft-revision-v1.html", [
    { match: ["提交修订", "重新生成"], to: "character-generating", actionId: "characters.revise" },
  ]),
  page("character-confirm", "确认角色主轴", "10 Character Spine/07 Confirm Character Spine/visual-drafts/character-spine-confirmation-v1.html", [
    { match: ["进入章节", "章节计划", "完成"], to: "chapter-source", actionId: "characters.finishMainCast" },
  ]),
  page("role-library", "角色档案库与分级管理", "10 Character Spine/08 Role Library And Tier Management/visual-drafts/role-library-tier-management-v1.html", [
    { match: ["上下文"], to: "role-context", actionId: "roles.contextPreview" },
    { match: ["返回", "角色主轴"], to: "character-entry" },
  ]),
  page("role-context", "角色上下文预览", "10 Character Spine/09 Role Context Preview/visual-drafts/role-context-preview-v1.html", [
    { match: ["返回"], to: "role-library" },
  ]),
  page("a-tier-state-change", "A-tier 状态变更审阅", "10 Character Spine/10 A-tier State Change Review/visual-drafts/a-tier-state-change-review-v1.html", [
    { match: ["确认"], to: "role-library", actionId: "roles.confirmStateChange" },
    { match: ["拒绝"], to: "role-library", actionId: "roles.rejectStateChange" },
  ]),
  page("chapter-source", "章节计划入口", "11 Chapter Planning/01 Source Preconditions And Current Framework Entry/visual-drafts/chapter-planning-source-preconditions-entry-v1.html", [
    { match: ["构建"], to: "chapter-building", actionId: "chapter.buildCurrent" },
  ]),
  page("chapter-building", "当前章 Framework 构建中", "11 Chapter Planning/02 Building Current Chapter Framework/visual-drafts/chapter-planning-building-current-framework-v1.html", [
    { match: ["查看", "完成"], to: "chapter-framework-review", actionId: "chapter.currentFramework" },
  ]),
  page("chapter-framework-review", "当前章 Framework 审阅", "11 Chapter Planning/03 Current Chapter Framework Review/visual-drafts/chapter-planning-current-framework-review-v1.html", [
    { match: ["章节路线", "进入"], to: "chapter-route-entry", actionId: "chapter.currentPlan" },
  ]),
  page("chapter-route-entry", "章节路线生成入口", "11 Chapter Planning/04 Chapter Route Generation Entry/visual-drafts/chapter-planning-route-generation-entry-v1.html", [
    { match: ["生成章节路线", "生成"], to: "chapter-route-generating", actionId: "chapter.generatePlan" },
  ]),
  page("chapter-route-generating", "章节路线生成中", "11 Chapter Planning/05 Generating Chapter Route/visual-drafts/chapter-planning-generating-route-v1.html", [
    { match: ["查看", "完成"], to: "chapter-route-review", actionId: "chapter.currentPlan" },
  ]),
  page("chapter-route-review", "章节路线审阅", "11 Chapter Planning/06 Chapter Route Review/visual-drafts/chapter-planning-route-review-v1.html", [
    { match: ["场景数"], to: "chapter-scene-count" },
    { match: ["问题"], to: "chapter-issue", actionId: "chapter.repairRoles" },
    { match: ["修订"], to: "chapter-revision", actionId: "chapter.revise" },
    { match: ["确认"], to: "chapter-confirm" },
  ]),
  page("chapter-scene-count", "场景数设置 / 修复", "11 Chapter Planning/07 Scene Count Setting And Repair/visual-drafts/chapter-planning-scene-count-repair-v1.html", [
    { match: ["应用", "返回"], to: "chapter-route-review", actionId: "chapter.setSceneCount" },
  ]),
  page("chapter-issue", "章节问题处理", "11 Chapter Planning/08 Issue Handling/visual-drafts/chapter-planning-issue-handling-v1.html", [
    { match: ["修复", "返回"], to: "chapter-route-review", actionId: "chapter.repairRoles" },
  ]),
  page("chapter-revision", "修订章节计划", "11 Chapter Planning/09 Revise Chapter Plan/visual-drafts/chapter-planning-revision-v1.html", [
    { match: ["提交修订", "重新生成"], to: "chapter-route-generating", actionId: "chapter.revise" },
  ]),
  page("chapter-confirm", "确认章节计划", "11 Chapter Planning/10 Confirm Chapter Plan/visual-drafts/chapter-planning-confirm-v1.html", [
    { match: ["进入场景", "场景写作"], to: "scene-entry", actionId: "chapter.confirm" },
  ]),
  page("scene-entry", "场景入口", "12 Scene Writing/01 Source Preconditions And Scene Entry/visual-drafts/scene-writing-source-preconditions-entry-v1.html", [
    { match: ["生成首场景", "生成"], to: "scene-generating", actionId: "scene.generateFirst" },
    { match: ["Brief", "简述"], to: "scene-brief" },
  ]),
  page("scene-brief", "场景 Brief 审阅", "12 Scene Writing/02 Scene Brief Review/visual-drafts/scene-writing-brief-review-v1.html", [
    { match: ["生成正文"], to: "scene-generating", actionId: "scene.generateNext" },
  ]),
  page("scene-generating", "正文生成中", "12 Scene Writing/03 Generating Scene Prose/visual-drafts/scene-writing-generating-prose-v1.html", [
    { match: ["查看", "完成"], to: "scene-review", actionId: "scene.current" },
  ]),
  page("scene-review", "场景正文草案审阅", "12 Scene Writing/04 Scene Prose Draft Review/visual-drafts/scene-writing-prose-draft-review-v1.html", [
    { match: ["修订"], to: "scene-revision", actionId: "scene.modificationPreview" },
    { match: ["连续性", "记忆"], to: "scene-continuity", actionId: "scene.continuityCheck" },
    { selector: "#confirmButton", match: ["确认场景", "确认", "进入确认流程"], to: "scene-confirm", actionId: "scene.commit" },
  ]),
  page("scene-revision", "修订场景正文", "12 Scene Writing/05 Revising Scene Prose/visual-drafts/scene-writing-revising-prose-v1.html", [
    { match: ["未来问题"], to: "scene-impact", actionId: "scene.futureQuestion" },
    { match: ["应用", "返回"], to: "scene-review", actionId: "scene.chooseModification" },
  ]),
  page("scene-continuity", "连续性与记忆写入", "12 Scene Writing/06 Continuity And Memory Write/visual-drafts/scene-writing-continuity-memory-write-v1.html", [
    { match: ["接受", "解决", "确认"], to: "scene-confirm", actionId: "scene.resolveContinuity" },
  ]),
  page("scene-confirm", "确认场景 / 进入下一场景", "12 Scene Writing/07 Confirm Scene And Enter Next Scene/visual-drafts/scene-writing-confirm-enter-next-v1.html", [
    { match: ["下一场景"], to: "scene-entry", actionId: "scene.generateNext" },
    { match: ["章节收尾", "章节末尾", "准备下一章"], to: "chapter-closeout", actionId: "scene.archivePreview" },
  ]),
  page("scene-gate", "后台检查修复与参与角色候选", "12 Scene Writing/08 Scene Gate Repair And Participant Candidates/visual-drafts/scene-gate-repair-participant-candidates-v1.html", [
    { selector: "[data-candidate]", match: ["确认候选", "确认"], to: "scene-entry", actionId: "scene.confirmParticipant" },
    { match: ["拒绝候选"], to: "scene-entry", actionId: "scene.rejectParticipant" },
    { match: ["刷新候选"], to: "scene-gate", actionId: "scene.participantRefresh" },
  ]),
  page("scene-impact", "修改影响与未来问题", "12 Scene Writing/09 Modification Impact And Future Issues/visual-drafts/modification-impact-future-issues-v1.html", [
    { match: ["接受", "返回"], to: "scene-review", actionId: "scene.acceptPreModify" },
  ]),
  page("chapter-closeout", "章节收尾与下一章准备", "12 Scene Writing/10 Chapter Closeout And Next Chapter Prep/visual-drafts/chapter-closeout-next-chapter-prep-v1.html", [
    { match: ["下一章"], to: "chapter-source", actionId: "scene.confirmNextChapter" },
    { match: ["故事草稿完成", "最终输出"], to: "final-entry", actionId: "scene.confirmStoryComplete" },
  ]),
  page("final-entry", "输出入口 / 完成度检查", "13 Final Output/01 Output Entry And Completion Check/visual-drafts/final-output-entry-completion-check-v1.html", [
    { match: ["进入成稿组装", "开始"], to: "final-assembly", actionId: "final.assemble" },
    { selector: "#refreshButton", match: ["评估完成度", "重新检查"], to: "final-entry", actionId: "final.evaluate" },
  ]),
  page("final-assembly", "成稿组装中", "13 Final Output/02 Manuscript Assembly In Progress/visual-drafts/final-output-manuscript-assembly-v1.html", [
    { selector: "#nextButton", match: ["进入成稿审阅", "查看", "完成"], to: "final-review", actionId: "final.refreshExports" },
    { selector: "#returnButton", match: ["返回检查"], to: "final-entry", actionId: "final.evaluate" },
  ]),
  page("final-review", "成稿审阅", "13 Final Output/03 Manuscript Review/visual-drafts/final-output-manuscript-review-v1.html", [
    { selector: "#confirmButton", match: ["确认成稿", "进入导出交付"], to: "final-settings", actionId: "final.viewerState" },
    { match: ["问题"], to: "final-issue", actionId: "final.readiness" },
  ]),
  page("final-settings", "输出设置", "13 Final Output/04 Output Settings/visual-drafts/final-output-output-settings-v1.html", [
    { match: ["开始导出", "下载所选格式", "准备交付文件", "导出"], to: "final-exporting", actionId: "final.refreshExports" },
    { match: ["回到成稿审阅", "返回成稿审阅"], to: "final-review", actionId: "final.refreshExports" },
  ]),
  page("final-exporting", "导出生成中", "13 Final Output/05 Export Generation In Progress/visual-drafts/final-output-export-generation-v1.html", [
    { selector: "#completeButton", match: ["进入交付结果", "完成"], to: "final-result", actionId: "final.refreshExports" },
    { match: ["返回输出设置", "返回设置"], to: "final-settings", actionId: "final.refreshExports" },
  ]),
  page("final-result", "导出结果 / 下载与归档", "13 Final Output/06 Export Result Download And Archive/visual-drafts/final-output-export-result-v1.html", [
    { selector: ".download-button[data-format]", to: "final-result", actionId: "final.download" },
    { selector: "[data-action='back-output']", to: "final-exporting", actionId: "final.refreshExports" },
    { selector: "[data-action='open-collection']", to: "projects" },
    { selector: "[data-action='back-settings']", to: "final-settings", actionId: "final.refreshExports" },
  ]),
  page("final-issue", "输出问题处理", "13 Final Output/07 Output Issue Handling/visual-drafts/final-output-issue-handling-v1.html", [
    { match: ["返回", "成稿"], to: "final-review", actionId: "final.readiness" },
  ]),
  page("plugin-entry", "插件成果入口", "14 Plugin Outputs/01 Plugin Outputs Entry/visual-drafts/plugin-outputs-entry-v1.html", [
    { match: ["选择插件", "开始"], to: "plugin-select", actionId: "plugins.refresh" },
  ]),
  page("plugin-select", "插件选择 / 输入确认", "14 Plugin Outputs/02 Plugin Selection And Input Confirmation/visual-drafts/plugin-selection-input-confirmation-v1.html", [
    { match: ["开始运行", "运行"], to: "plugin-running", actionId: "plugins.createRun" },
    { match: ["校验"], to: "plugin-select", actionId: "plugins.validateInput" },
  ]),
  page("plugin-running", "插件运行中", "14 Plugin Outputs/03 Plugin Run In Progress/visual-drafts/plugin-run-in-progress-v1.html", [
    { selector: "#refreshButton", match: ["刷新状态", "检查点"], to: "plugin-checkpoint", actionId: "plugins.run" },
    { match: ["查看成果", "完成"], to: "plugin-review", actionId: "plugins.artifacts" },
  ]),
  page("plugin-checkpoint", "检查点处理", "14 Plugin Outputs/04 Checkpoint Handling/visual-drafts/plugin-checkpoint-handling-v1.html", [
    { match: ["确认"], to: "plugin-review", actionId: "plugins.confirmCheckpoint" },
    { match: ["修订"], to: "plugin-select", actionId: "plugins.reviseCheckpoint" },
    { match: ["拒绝"], to: "plugin-issue", actionId: "plugins.rejectCheckpoint" },
  ]),
  page("plugin-review", "插件成果审阅", "14 Plugin Outputs/05 Plugin Artifact Review/visual-drafts/plugin-artifact-review-v1.html", [
    { selector: "#refreshButton", match: ["刷新成果"], to: "plugin-review", actionId: "plugins.artifacts" },
    { match: ["问题"], to: "plugin-issue", actionId: "plugins.safetyReport" },
  ]),
  page("plugin-issue", "插件输出问题处理", "14 Plugin Outputs/06 Plugin Output Issue Handling/visual-drafts/plugin-output-issue-handling-v1.html", [
    { match: ["返回", "选择"], to: "plugin-select" },
  ]),
  page("settings-overview", "设置总览", "15 Settings/01 Settings Overview/visual-drafts/settings-overview-v1.html", [
    ...SETTINGS_NAV_ACTIONS,
  ]),
  page("settings-appearance", "外观与主题", "15 Settings/02 Appearance And Theme/visual-drafts/settings-appearance-theme-v1.html", [
    ...SETTINGS_NAV_ACTIONS,
    { match: ["返回"], to: "settings-overview", actionId: "settings.workbench" },
  ]),
  page("settings-model", "模型配置", "15 Settings/03 Model Configuration/visual-drafts/settings-model-configuration-v1.html", [
    ...SETTINGS_NAV_ACTIONS,
    { selector: "#newProfileButton", match: ["新建 Profile"], actionId: "settings.createProfile" },
    { selector: "#saveButton", match: ["更新 Profile", "保存"], actionId: "settings.patchProfile" },
    { selector: "#activeButton", match: ["设为当前"], actionId: "settings.setActive" },
    { selector: "#healthButton", match: ["健康检查"], to: "settings-health", actionId: "settings.healthCheck" },
    { match: ["返回总览"], to: "settings-overview" },
  ]),
  page("settings-health", "当前模型与健康检查", "15 Settings/04 Current Model And Health Check/visual-drafts/settings-current-model-health-v1.html", [
    ...SETTINGS_NAV_ACTIONS,
    { selector: "#fullButton", match: ["运行完整检查", "运行健康检查"], to: "settings-health", actionId: "settings.healthCheck" },
    { match: ["返回"], to: "settings-overview" },
  ]),
  page("settings-secrets", "密钥与安全", "15 Settings/05 Secrets And Security/visual-drafts/settings-secrets-security-v1.html", [
    ...SETTINGS_NAV_ACTIONS,
    { match: ["返回"], to: "settings-overview" },
  ]),
  page("settings-preferences", "创作偏好", "15 Settings/06 Creative Preferences/visual-drafts/settings-creative-preferences-v1.html", [
    ...SETTINGS_NAV_ACTIONS,
    { match: ["返回"], to: "settings-overview", actionId: "settings.workbench" },
  ]),
];

export const PAGE_BY_ID = Object.fromEntries(CONFIRMED_PAGES.map((item) => [item.id, item]));

export function getPage(id) {
  return PAGE_BY_ID[id] || PAGE_BY_ID.home;
}

export function getPageIndex(id) {
  return CONFIRMED_PAGES.findIndex((item) => item.id === id);
}

export function getPreviousPage(id) {
  const index = getPageIndex(id);
  return CONFIRMED_PAGES[Math.max(index - 1, 0)] || PAGE_BY_ID.home;
}
