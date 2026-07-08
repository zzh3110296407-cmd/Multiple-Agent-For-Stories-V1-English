from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.backend.api.health import router as health_router
from app.backend.api.abcd_runtime import router as abcd_runtime_router
from app.backend.api.abcd_runtime_gate import router as abcd_runtime_gate_router
from app.backend.api.abcd_story_information import router as abcd_story_information_router
from app.backend.api.app_progress import router as app_progress_router
from app.backend.api.analyze_stories import router as analyze_stories_router
from app.backend.api.analyzer_handoffs import router as analyzer_handoffs_router
from app.backend.api.background_thinking import router as background_thinking_router
from app.backend.api.background_budget import router as background_budget_router
from app.backend.api.chapter_archive import router as chapter_archive_router
from app.backend.api.chapter_plan import router as chapter_plan_router
from app.backend.api.character_intents import router as character_intents_router
from app.backend.api.characters import router as characters_router
from app.backend.api.continuity import router as continuity_router
from app.backend.api.composite_runtime import router as composite_runtime_router
from app.backend.api.debug import router as debug_router
from app.backend.api.debug_visibility import router as debug_visibility_router
from app.backend.api.framework_package import router as framework_package_router
from app.backend.api.framework_library import router as framework_library_router
from app.backend.api.framework_compositions import router as framework_compositions_router
from app.backend.api.future_review import router as future_review_router
from app.backend.api.final_story_package import router as final_story_package_router
from app.backend.api.memory import router as memory_router
from app.backend.api.memory_packs import router as memory_packs_router
from app.backend.api.memory_retrieval_promotion import router as memory_retrieval_promotion_router
from app.backend.api.memory_sync import router as memory_sync_router
from app.backend.api.modification_impact import router as modification_impact_router
from app.backend.api.model_gateway import router as model_gateway_router
from app.backend.api.model_runtime import router as model_runtime_router
from app.backend.api.narrative_layer import router as narrative_layer_router
from app.backend.api.plugin_artifacts import router as plugin_artifacts_router
from app.backend.api.plugin_runs import router as plugin_runs_router
from app.backend.api.plugins import router as plugins_router
from app.backend.api.pre_modify import router as pre_modify_router
from app.backend.api.project import router as project_router
from app.backend.api.project_creation import (
    project_creation_router,
    projects_router,
)
from app.backend.api.project_story_premise import router as project_story_premise_router
from app.backend.api.product_navigation import router as product_navigation_router
from app.backend.api.product_artifacts import router as product_artifacts_router
from app.backend.api.product_mode import router as product_mode_router
from app.backend.api.product_progress import router as product_progress_router
from app.backend.api.quality import router as quality_router
from app.backend.api.formal_apply_dry_run import router as formal_apply_dry_run_router
from app.backend.api.formal_apply_decision_gate import router as formal_apply_decision_gate_router
from app.backend.api.formal_apply_execution import router as formal_apply_execution_router
from app.backend.api.formal_apply_eligibility import router as formal_apply_eligibility_router
from app.backend.api.formal_apply_proposals import router as formal_apply_proposals_router
from app.backend.api.phase6_release_gate import router as phase6_release_gate_router
from app.backend.api.phase6_replay_gate import router as phase6_replay_gate_router
from app.backend.api.phase7_release_gate import router as phase7_release_gate_router
from app.backend.api.phase8_release_gate import router as phase8_release_gate_router
from app.backend.api.propagation_governance import router as propagation_governance_router
from app.backend.api.recommendation_governance import router as recommendation_governance_router
from app.backend.api.roles import router as roles_router
from app.backend.api.role_memory import router as role_memory_router
from app.backend.api.scenes import router as scenes_router
from app.backend.api.scene_gate_repair import router as scene_gate_repair_router
from app.backend.api.scene_dependency_graph import router as scene_dependency_graph_router
from app.backend.api.script_forging import router as script_forging_router
from app.backend.api.scene_candidate_cache import router as scene_candidate_cache_router
from app.backend.api.scene_snapshots import router as scene_snapshots_router
from app.backend.api.scene_participation import router as scene_participation_router
from app.backend.api.scene_participants import router as scene_participants_router
from app.backend.api.settings_model import router as settings_model_router
from app.backend.api.story_setup import router as story_setup_router
from app.backend.api.library_retrieval import router as library_retrieval_router
from app.backend.api.temporal_resolver import router as temporal_resolver_router
from app.backend.api.template_demo_seed import (
    demo_seeds_router,
    project_origin_badges_router,
    project_templates_router,
    template_instantiation_router,
)
from app.backend.api.story_progress import router as story_progress_router
from app.backend.api.story_data import router as story_data_router
from app.backend.api.tracing import router as tracing_router
from app.backend.api.world_canvas import router as world_canvas_router
from app.backend.core.config import settings


def create_app() -> FastAPI:
    settings.validate_storage_runtime()
    app = FastAPI(
        title="Multiple Agent For Stories Backend",
        description="Productized story workbench backend with model, setup, and story workspace services.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(health_router)
    app.include_router(app_progress_router, prefix="/api/app")
    app.include_router(analyze_stories_router, prefix="/api/analyze-stories")
    app.include_router(analyzer_handoffs_router, prefix="/api/analyzer-handoffs")
    app.include_router(project_router, prefix="/api/project")
    app.include_router(project_creation_router, prefix="/api/project-creation")
    app.include_router(projects_router, prefix="/api/projects")
    app.include_router(project_story_premise_router, prefix="/api/project-story-premise")
    app.include_router(product_navigation_router, prefix="/api/product-navigation")
    app.include_router(product_mode_router, prefix="/api/product-mode")
    app.include_router(product_progress_router, prefix="/api/product-progress")
    app.include_router(product_artifacts_router, prefix="/api/product-artifacts")
    app.include_router(story_setup_router, prefix="/api/story-setup")
    app.include_router(project_templates_router, prefix="/api/project-templates")
    app.include_router(
        template_instantiation_router,
        prefix="/api/template-instantiation",
    )
    app.include_router(demo_seeds_router, prefix="/api/demo-seeds")
    app.include_router(project_origin_badges_router, prefix="/api/project-origin-badges")
    app.include_router(framework_package_router, prefix="/api/framework-package")
    app.include_router(framework_library_router, prefix="/api/framework-library")
    app.include_router(framework_compositions_router, prefix="/api/framework-compositions")
    app.include_router(memory_router, prefix="/api/memory")
    app.include_router(memory_packs_router, prefix="/api/memory-packs")
    app.include_router(memory_retrieval_promotion_router, prefix="/api/memory-retrieval")
    app.include_router(memory_sync_router, prefix="/api/memory-sync")
    app.include_router(modification_impact_router, prefix="/api/modification-impact")
    app.include_router(model_gateway_router, prefix="/api/model-gateway")
    app.include_router(model_runtime_router, prefix="/api/model-runtime")
    app.include_router(settings_model_router, prefix="/api/settings/model")
    app.include_router(background_budget_router, prefix="/api/background-budget")
    app.include_router(background_thinking_router, prefix="/api/background-thinking")
    app.include_router(pre_modify_router, prefix="/api/pre-modify")
    app.include_router(phase6_replay_gate_router, prefix="/api/phase6/replay-gate")
    app.include_router(
        formal_apply_eligibility_router,
        prefix="/api/phase6/formal-apply/eligibility",
    )
    app.include_router(
        formal_apply_dry_run_router,
        prefix="/api/phase6/formal-apply/dry-run",
    )
    app.include_router(
        formal_apply_decision_gate_router,
        prefix="/api/phase6/formal-apply/decisions",
    )
    app.include_router(
        formal_apply_execution_router,
        prefix="/api/phase6/formal-apply/executions",
    )
    app.include_router(
        formal_apply_proposals_router,
        prefix="/api/phase6/formal-apply/proposals",
    )
    app.include_router(
        propagation_governance_router,
        prefix="/api/phase6/propagation",
    )
    app.include_router(
        recommendation_governance_router,
        prefix="/api/phase6/recommendation-governance",
    )
    app.include_router(
        phase6_release_gate_router,
        prefix="/api/phase6/release-gate",
    )
    app.include_router(
        phase7_release_gate_router,
        prefix="/api/phase7/release-gate",
    )
    app.include_router(
        phase8_release_gate_router,
        prefix="/api/phase8/release-gate",
    )
    app.include_router(narrative_layer_router, prefix="/api/narrative-layer")
    app.include_router(tracing_router, prefix="/api/tracing")
    app.include_router(world_canvas_router, prefix="/api/world-canvas")
    app.include_router(characters_router, prefix="/api/characters")
    app.include_router(roles_router, prefix="/api/roles")
    app.include_router(role_memory_router, prefix="/api/role-memory")
    app.include_router(chapter_plan_router, prefix="/api/chapter-plan")
    app.include_router(chapter_archive_router, prefix="/api/chapter-archive")
    app.include_router(story_progress_router, prefix="/api/story-progress")
    app.include_router(scenes_router, prefix="/api/scenes")
    app.include_router(scene_gate_repair_router, prefix="/api/scene-gate-repair")
    app.include_router(scene_candidate_cache_router, prefix="/api/scene-candidate-cache")
    app.include_router(scene_participants_router, prefix="/api/scene-participants")
    app.include_router(scene_participation_router, prefix="/api/scene-participation")
    app.include_router(character_intents_router, prefix="/api/character-intents")
    app.include_router(abcd_story_information_router, prefix="/api/abcd-story-information")
    app.include_router(abcd_runtime_router, prefix="/api/abcd-runtime")
    app.include_router(abcd_runtime_gate_router, prefix="/api/abcd-runtime-gate")
    app.include_router(library_retrieval_router, prefix="/api/library-retrieval")
    app.include_router(temporal_resolver_router, prefix="/api/temporal-resolver")
    app.include_router(composite_runtime_router, prefix="/api/composite-runtime")
    app.include_router(future_review_router, prefix="/api/future-review")
    app.include_router(final_story_package_router, prefix="/api/final-story-package")
    app.include_router(plugins_router, prefix="/api/plugins")
    app.include_router(plugin_runs_router, prefix="/api/plugin-runs")
    app.include_router(script_forging_router, prefix="/api/plugin-runs")
    app.include_router(plugin_artifacts_router, prefix="/api/plugin-artifacts")
    app.include_router(scene_snapshots_router, prefix="/api/scene-snapshots")
    app.include_router(
        scene_dependency_graph_router,
        prefix="/api/scene-dependency-graph",
    )
    app.include_router(continuity_router, prefix="/api/continuity")
    app.include_router(debug_router, prefix="/api/debug")
    app.include_router(debug_visibility_router, prefix="/api/debug-visibility")
    app.include_router(quality_router, prefix="/api")
    app.include_router(story_data_router, prefix="/api")
    return app


app = create_app()
