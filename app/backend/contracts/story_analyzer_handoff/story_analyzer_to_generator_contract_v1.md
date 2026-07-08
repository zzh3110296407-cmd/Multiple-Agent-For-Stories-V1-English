# Story Analyzer to Story Generator Integration Contract v1

## Status
Accepted for integration scaffold.

## Date
2026-06-30

## Decision
故事生成器接入故事分析器时，只接入一份混合统一交接包：

`generator_handoff/unified_generator_handoff.validated.json`

分析器不再按三类用户分别输出三份包。分析器统一输出完整材料，生成器在内部根据用户选择做筛选、组合和降级。

## Integration Boundary
分析器负责：

- 从原文和分析结果编译统一 handoff。
- 为每个可供生成器使用的材料提供 `module_type`、`abstraction_level`、`source_dependence`、`selection_tags`、`source_refs`。
- 生成 `source_reference_index.json`，让生成器或检测系统能回查接近原文的证据。
- 运行 validator 和 repair loop。
- 只有通过验证后才写出 `unified_generator_handoff.validated.json`。

生成器负责：

- 只读取 `unified_generator_handoff.validated.json`。
- 按用户选择读取其中不同模块，而不是要求分析器重新生成不同包。
- 对导入材料做二次生成前校验。
- 如果 validated handoff 不存在或状态不通过，停止导入并显示结构化失败原因。

## Canonical File Contract
生成器必须按以下顺序读取：

1. `output/generator_handoff/unified_generator_handoff.validated.json`
2. `output/generator_handoff/source_reference_index.json`
3. 可选读取 `output/generator_handoff/validation_report.json`
4. 可选读取 `output/generator_handoff/repair_history.json`

生成器禁止直接读取：

- `chapters/*.json`
- `arcs/*.json`
- `book_framework.json`
- `generation_profiles.json`
- `full_book_bundle.json`
- `unified_generator_handoff.json`
- `unified_generator_handoff.repaired.json`
- 任意 partial run 输出

这些文件属于分析器内部或中间产物，不能成为对接契约。

## Required Import Gate
生成器导入前必须检查：

```text
handoff.handoff_version == "generator_handoff.v1"
handoff.handoff_status == "passed"
quality_gate.run_status == "completed"
quality_gate.failed_chapter_count == 0
quality_gate.llm_unrecovered_failed_target_count == 0
quality_gate.missing_required_outputs is empty
quality_gate.source_leak_status == "passed"
quality_gate.abstraction_quality_status == "passed"
quality_gate.arc_count == quality_gate.expected_arc_count
validator_summary.validation_status in ["passed", "passed_with_warnings"]
generator_materials is not empty
every generator_material has source_refs
source_reference_index_ref resolves to an existing file
```

如果任何条件不满足，生成器不得使用本次分析内容。

## Unified Payload Shape
`unified_generator_handoff.validated.json` 必须包含：

```json
{
  "handoff_version": "generator_handoff.v1",
  "handoff_status": "passed",
  "compiled_at": "ISO-8601 string",
  "work_identity": {},
  "quality_gate": {},
  "source_map": {},
  "book_framework": {},
  "arc_hierarchy": {},
  "chapter_blueprints": [],
  "foreshadowing_registry": {},
  "generator_materials": [],
  "selection_metadata": {},
  "validator_summary": {},
  "repair_history": {},
  "source_reference_index_ref": "source_reference_index.json"
}
```

字段只允许加法扩展。不得删除上述字段，不得改变已有枚举语义。

## Material Contract
`generator_materials[]` 是生成器最主要的消费入口。每个 material 必须包含：

```json
{
  "material_id": "GM001",
  "module_type": "pacing_structure",
  "abstraction_level": "abstract",
  "source_dependence": "source_free",
  "granularity": "book",
  "content": {},
  "selection_tags": ["original_writing"],
  "source_refs": ["REF_CH_001"],
  "evidence_strength": "medium"
}
```

### module_type
允许值：

- `pacing_structure`
- `arc_structure`
- `chapter_progression`
- `character_growth`
- `relationship_dynamics`
- `worldbuilding`
- `core_conflict`
- `foreshadowing_system`
- `emotion_curve`
- `information_release`
- `scene_function`
- `narrative_mechanism`
- `adaptable_setting`
- `source_fidelity`

### abstraction_level
允许值：

- `abstract`: 去剧情专名化结构，适合原创用户。
- `semi_abstract`: 可迁移但保留部分设定功能，适合混合借用。
- `source_specific`: 贴近原作事实，适合续写、改写、补完。

### source_dependence
允许值：

- `source_free`: 不应携带原作专名或具体剧情事实。
- `adaptable`: 可迁移模块，允许有来源说明，但生成器使用时应改写。
- `source_bound`: 必须严格依赖原文证据，适合续写和改写。

### selection_tags
推荐标签：

- `original_writing`
- `continuation`
- `rewrite`
- `hybrid_adaptation`
- `structure_only`
- `source_story`

生成器可以组合使用标签，但不得把 `source_bound` 材料当作纯原创结构直接喂给原创生成流程。

## User Type Mapping
用户类型在生成器中选择，分析器不参与选择。

### 原创写作用户
生成器优先读取：

```text
source_dependence in ["source_free", "adaptable"]
abstraction_level in ["abstract", "semi_abstract"]
selection_tags contains "original_writing" or "structure_only"
module_type in ["pacing_structure", "arc_structure", "chapter_progression", "emotion_curve", "narrative_mechanism"]
```

生成器必须避免直接读取：

```text
source_dependence == "source_bound"
abstraction_level == "source_specific"
module_type == "source_fidelity"
```

### 续写 / 改写用户
生成器优先读取：

```text
source_dependence == "source_bound"
abstraction_level == "source_specific"
selection_tags contains "continuation" or "rewrite" or "source_story"
module_type in ["source_fidelity", "foreshadowing_system", "worldbuilding", "relationship_dynamics", "core_conflict", "information_release"]
```

生成器必须保留 `source_refs`，后续检测和修正系统需要它回查原文证据。

### 混合借用用户
生成器优先读取：

```text
source_dependence in ["adaptable", "source_free"]
abstraction_level in ["semi_abstract", "abstract"]
selection_tags contains "hybrid_adaptation"
module_type in ["worldbuilding", "relationship_dynamics", "core_conflict", "adaptable_setting", "emotion_curve", "arc_structure"]
```

如果读取 `source_specific` 材料，生成器必须先做改写，不得直接复制为新故事设定。

## Source Reference Contract
`source_reference_index.json` 是证据索引，不是生成素材主体。

生成器至少需要支持：

```json
{
  "schema_version": "generator_handoff.source_reference_index.v2",
  "references": {
    "REF_CH_001": {
      "source_type": "chapter_analysis",
      "near_source_summary": "...",
      "evidence_spans": [],
      "raw_source_scope": {}
    }
  }
}
```

生成器可以把 `source_refs` 传给检测系统。检测系统根据 `source_reference_index` 和 raw source evidence 决定生成结果是否忠实。

## Foreshadowing Contract
生成器读取 `foreshadowing_registry.items[]` 时，主内容字段优先级为：

1. `canonical_content`
2. `summary`
3. `text`

每条伏笔必须有稳定 `id` 和 `status`。

允许状态：

- `planted`
- `partially_resolved`
- `resolved`

生成器不得把 `partially_resolved` 当作完全回收。只要存在 `open_questions`、`partial_resolution_chapters` 或 `resolution_scope=series`，生成器应按未完全关闭处理。

## Failure Contract
如果没有 `unified_generator_handoff.validated.json`，生成器可以读取：

- `generator_handoff/handoff_failed_report.json`
- `generator_handoff/validation_report.json`
- `generator_handoff/compiler_report.json`

并向用户显示：

```json
{
  "import_status": "blocked",
  "reason": "ANALYZER_HANDOFF_NOT_DELIVERABLE",
  "blocking_issue_count": 0,
  "warning_count": 0,
  "user_message": "本次分析结果未通过交接检测，请重试分析或等待失败章节续跑。"
}
```

生成器不能自行拼接中间文件绕过失败。

## Compatibility Rules
后续分析器升级必须遵守：

- 可以新增字段。
- 可以新增 `generator_materials`。
- 可以新增 `module_type`，但新增前需要更新 schema 和生成器映射。
- 不能删除必需字段。
- 不能把 `source_free` 的语义改成允许专名泄漏。
- 不能把 `passed_with_warnings` 等同于无条件可导入，必须通过 deliverable 判定。
- 不能让生成器依赖 `material_id` 的排序，只能依赖字段含义。

## Generator Import Pseudocode
```python
def import_analyzer_handoff(output_dir):
    handoff_path = output_dir / "generator_handoff" / "unified_generator_handoff.validated.json"
    if not handoff_path.exists():
        return blocked("ANALYZER_HANDOFF_NOT_DELIVERABLE")

    handoff = read_json(handoff_path)
    assert handoff["handoff_version"] == "generator_handoff.v1"
    assert handoff["handoff_status"] == "passed"
    assert handoff["quality_gate"]["run_status"] == "completed"
    assert handoff["quality_gate"]["failed_chapter_count"] == 0

    source_index = read_json(output_dir / "generator_handoff" / handoff["source_reference_index_ref"])
    materials = handoff["generator_materials"]
    return {
        "work_identity": handoff["work_identity"],
        "source_map": handoff["source_map"],
        "materials": materials,
        "source_reference_index": source_index,
    }
```

## Immediate Integration Scope
当前建议只做 P0 对接：

- 生成器实现 handoff importer。
- 生成器实现三类用户筛选器。
- 生成器实现 source_refs 透传。
- 生成器实现失败报告显示。
- 暂不要求分析器本体达到百万字稳定生产质量。

这个范围能先固定接口结构，后续分析器增强只要继续输出本契约，就不会影响生成器对接。
