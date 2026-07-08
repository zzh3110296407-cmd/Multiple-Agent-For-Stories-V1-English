#!/usr/bin/env python3
import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path


MACRO_META = {
    "macro_opening": ("开端", 1, "建立世界、主角、基调和初始缺口。"),
    "macro_inciting_incident": ("触发事件", 2, "让故事真正进入运动，并迫使角色回应核心问题。"),
    "macro_development_escalation": ("发展/升级", 3, "推进目标、扩大冲突、引入更复杂的压力。"),
    "macro_crisis_local_climax": ("危机/局部高潮", 4, "让角色面对关键选择，并形成局部强度峰值。"),
    "macro_resolution_aftermath": ("结尾/余波", 5, "呈现选择后果，形成阶段性落点和新状态。"),
}

MODULE_META = {
    "chapter_function": ("篇章功能模块", "chapter", "chapter_local", "chapter_framework", "no_memory_write", 1),
    "reader_emotion": ("读者情绪模块", "chapter", "ephemeral", "chapter_framework", "no_memory_write", 2),
    "character_desire": ("角色欲望模块", "character", "advisory_reference", "character_state", "no_formal_write", 3),
    "character_arc": ("人物弧光模块", "chapter", "advisory_reference", "character_state", "no_formal_write", 4),
    "conflict": ("冲突模块", "chapter", "advisory_reference", "chapter_framework", "no_formal_write", 5),
    "information_release": ("信息释放模块", "chapter", "advisory_reference", "chapter_framework", "no_formal_write", 6),
    "style_pacing": ("风格与节奏模块", "chapter", "ephemeral", "chapter_framework", "no_memory_write", 7),
}


def _module_meta(module_id: str) -> dict:
    label, scope, persistence, owner, write_policy, order = MODULE_META.get(
        module_id,
        (module_id, "chapter", "chapter_local", "chapter_framework", "no_memory_write", 999),
    )
    return {
        "label": label,
        "scope": scope,
        "persistence": persistence,
        "owner": owner,
        "write_policy": write_policy,
        "order": order,
    }


def _normalize_macro_component(component: dict) -> dict:
    component_id = component.get("component_id", "")
    label, order, instruction = MACRO_META.get(
        component_id,
        (component.get("label") or component.get("component_label") or component_id, component.get("order", 999), ""),
    )
    return {
        "component_id": component_id,
        "label": label,
        "order": component.get("order", order),
        "instruction": component.get("instruction", instruction),
        "source": component.get("source", "analyze_stories"),
        "scope": component.get("scope", "macro"),
    }


def _component_from_content(module_id: str, content: object, order: int) -> dict:
    meta = _module_meta(module_id)
    content_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    label = content_text.strip()
    if not label:
        label = meta["label"]
    if len(label) > 40 or label.startswith(("{", "[")):
        label = meta["label"]
    digest = hashlib.sha1((module_id + "|" + content_text).encode("utf-8")).hexdigest()[:10]
    return {
        "component_id": f"{module_id}_{digest}",
        "label": label,
        "source": "analyze_stories",
        "scope": meta["scope"],
        "persistence": meta["persistence"],
        "owner": meta["owner"],
        "write_policy": meta["write_policy"],
        "normalized_hint": content_text,
        "order": order,
        "authority": "advisory_only",
        "can_write_formal_state": False,
    }


def _normalize_chapter_module(module: dict, built_components_by_module: dict | None = None) -> dict:
    module_id = module.get("module_id", "")
    meta = _module_meta(module_id)
    allowed = module.get("allowed_components")
    if allowed is None and built_components_by_module:
        allowed = built_components_by_module.get(module_id, [])
    if allowed is None:
        allowed = []
    return {
        "module_id": module_id,
        "label": module.get("label") or module.get("module_label") or meta["label"],
        "scope": module.get("scope", meta["scope"]),
        "persistence": module.get("persistence", meta["persistence"]),
        "owner": module.get("owner", meta["owner"]),
        "write_policy": module.get("write_policy", meta["write_policy"]),
        "order": module.get("order", meta["order"]),
        "allowed_components": allowed,
    }


def normalize_framework_package(package: dict) -> dict:
    if package.get("shape_variant") != "compact_content_only":
        return deepcopy(package)

    normalized = deepcopy(package)

    macro_components = [
        _normalize_macro_component(c)
        for c in normalized.get("macro_framework", {}).get("components", [])
    ]
    normalized["macro_framework"] = {"components": macro_components}

    built_components_by_module = {}
    for chapter_framework in normalized.get("built_chapter_frameworks", []):
        new_modules = []
        for module in chapter_framework.get("modules", []):
            module_id = module.get("module_id", "")
            content = module.get("content", "")
            components = []
            if content not in ("", None):
                components = [_component_from_content(module_id, content, 1)]
            built_components_by_module.setdefault(module_id, [])
            built_components_by_module[module_id].extend(components)
            meta = _module_meta(module_id)
            new_modules.append({
                "module_id": module_id,
                "label": module.get("label") or module.get("module_label") or meta["label"],
                "scope": meta["scope"],
                "persistence": meta["persistence"],
                "owner": meta["owner"],
                "write_policy": meta["write_policy"],
                "order": meta["order"],
                "components": components,
            })
        chapter_framework["modules"] = new_modules

    vocabulary = normalized.get("component_vocabulary", {})
    vocabulary["macro_components"] = [
        _normalize_macro_component(c)
        for c in vocabulary.get("macro_components", macro_components)
    ]
    vocabulary["chapter_modules"] = [
        _normalize_chapter_module(m, built_components_by_module)
        for m in vocabulary.get("chapter_modules", [])
    ]
    vocabulary.setdefault("module_components", [])
    normalized["component_vocabulary"] = vocabulary
    normalized["shape_variant"] = "rich_components"
    return normalized


def validate_rich_like(package: dict) -> list[str]:
    issues = []
    for component in package.get("macro_framework", {}).get("components", []):
        for key in ["component_id", "label", "instruction", "source", "scope"]:
            if key not in component:
                issues.append(f"macro component missing {key}: {component.get('component_id')}")

    for module in package.get("component_vocabulary", {}).get("chapter_modules", []):
        for key in ["module_id", "label", "scope", "persistence", "owner", "write_policy", "order", "allowed_components"]:
            if key not in module:
                issues.append(f"chapter module missing {key}: {module.get('module_id')}")

    for chapter_framework in package.get("built_chapter_frameworks", []):
        for module in chapter_framework.get("modules", []):
            if "components" not in module:
                issues.append(f"built module missing components: {module.get('module_id')}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize Analyze Stories compact framework_package files.")
    parser.add_argument("input", help="Input framework_package.json")
    parser.add_argument("--out", default="", help="Output path. Defaults to stdout.")
    args = parser.parse_args()

    input_path = Path(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    normalized = normalize_framework_package(data)
    issues = validate_rich_like(normalized)
    if issues:
        raise SystemExit("\n".join(issues))
    output = json.dumps(normalized, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
