# Multiple Agent For Stories V1

Chinese README: https://github.com/zzh3110296407-cmd/Multiple-Agent-For-Stories-V1

Multiple Agent For Stories, is a multi-agent story creation workbench for long-form narrative design, interactive script development, and agent-assisted story production. It is built around one core idea: the system should not only continue text, but also maintain a structured story world, verify narrative state, and let different agent services cooperate around explicit story objects.

The open-source package contains the current runnable product surface:

- FastAPI backend with JSON-first storage and optional PostgreSQL primary storage.
- Vite/React product workbench with ordinary/expert operating modes.
- Model gateway and model runtime observability for Qwen/DeepSeek-compatible LLM calls.
- Story setup, world canvas, character spine, chapter planning, scene writing, quality/continuity gates, final output, and plugin-output entry points.
- Story Analyzer module for long-form story analysis and framework extraction.
- PostgreSQL schema prototypes, storage contracts, and database migration foundations.

This directory is generated from the development workspace. For long-term fixes, update the source project and regenerate this package instead of manually patching generated files.

## What The System Does

The project turns story creation into an auditable multi-agent workflow:

1. The user creates or opens a story project.
2. The system builds a story setup, world canvas, main cast, and global framework.
3. Chapter planning creates a light route and current chapter brief.
4. The scene-writing workflow generates structured scene drafts before final prose.
5. Memory, event, state-change, decision, quality, and continuity layers record what changed and what still requires user confirmation.
6. Final story package and plugin-output modules prepare export-oriented results only after user-visible confirmation.

The product is designed for writers, script creators, interactive narrative designers, and AI-agent researchers who need reproducible story state rather than one-shot prompt output.

## Included Source Areas

- `app/backend` - FastAPI backend, services, models, storage adapters, and API routers.
- `app/frontend` - React/Vite product UI and workbench pages.
- `app/Story Analyzer` - external story analysis module used for long-form analysis and framework extraction.
- `database/sql-prototype` - PostgreSQL schema and migration prototype material.
- `database/contracts` - storage/API contract documentation.
- `database/storage_foundation` - database foundation notes and migration support files.

## Excluded By Design

Historical phase folders, Harness caches, debug screenshots, generated runtime data, virtual environments, `node_modules`, build output, and private environment files are excluded.

The large `app/frontend/public/confirmed-ui` visual draft asset set is excluded by default to keep the repository practical for GitHub and Docker build contexts. If exact ordinary-mode iframe previews are required, regenerate the package from the source workspace with `--include-design-assets`.

## Requirements

Recommended:

- Docker Desktop with Docker Compose.
- A model API key, usually `QWEN_API_KEY` or `DEEPSEEK_API_KEY`.

Optional local development:

- Python 3.11+
- Node.js 22+
- PostgreSQL 16+ if you want PostgreSQL primary storage.

## Docker Deployment

From the repository root:

```powershell
cd "<your clone path>"
Copy-Item .env.example .env
docker compose up --build
```

Or from `cmd.exe`:

```bat
cd /d "<your clone path>"
copy .env.example .env
docker compose up --build
```

Then open:

- Frontend: <http://localhost:3000>
- Backend health through frontend proxy: <http://localhost:3000/health>
- Backend health directly: <http://localhost:8000/health>

## Configure The Model

Edit `.env` before starting Docker:

```text
QWEN_API_KEY=your_key_here
QWEN_BASE_URL=https://your-openai-compatible-endpoint/v1
QWEN_MODEL_NAME=your-model-name

DEEPSEEK_API_KEY=
```

The release template disables LangSmith tracing by default. If external tracing is enabled during development, do not publish private prompts, raw model responses, or API keys.

## Docker Hub Image Names

The Docker image names do not include the language directory name. The published Docker Hub repository uses separate backend/frontend tags:

```text
zihangzhong/multiple-agent-for-stories-v1:backend-latest
zihangzhong/multiple-agent-for-stories-v1:frontend-latest
zihangzhong/multiple-agent-for-stories-v1:backend-1.0.0
zihangzhong/multiple-agent-for-stories-v1:frontend-1.0.0
```

For local builds, `docker compose` uses:

```text
multiple-agent-for-stories-backend:latest
multiple-agent-for-stories-frontend:latest
```

To build with Docker Hub image names:

```powershell
$env:MAS_BACKEND_IMAGE = "zihangzhong/multiple-agent-for-stories-v1:backend-latest"
$env:MAS_FRONTEND_IMAGE = "zihangzhong/multiple-agent-for-stories-v1:frontend-latest"
docker compose build
```

## Storage Modes

The default Docker configuration uses JSON primary storage:

```text
MULTIPLE_AGENT_STORIES_STORAGE_MODE=json_primary
MULTIPLE_AGENT_STORIES_DATA_DIR=/workspace/app/data/local_project
```

PostgreSQL is included as an optional service. To switch to PostgreSQL primary mode, set:

```text
MULTIPLE_AGENT_STORIES_STORAGE_MODE=postgres_primary
MULTIPLE_AGENT_STORIES_DATABASE_URL=postgresql://mas:mas_dev_password@postgres:5432/mas
```

Runtime data is stored in Docker volumes:

- `app_data` for project data.
- `postgres_data` for PostgreSQL data.

## How To Enter The Product

1. Open <http://localhost:3000>.
2. Check the top status area. `backend connected` and a healthy model status indicate the product can call the backend and model gateway.
3. Open `模型设置 / Model Settings` if the model is not configured.
4. Use the left navigation to move through the product workflow.

The UI has two operating modes:

- `普通 / Ordinary` - product-oriented flow for normal use.
- `专家 / Expert` - more technical diagnostics and lower-level workbench state.

## Basic Workflow

1. `创建项目 / Create Project` - create or select a story project.
2. `故事设定 / Story Setup` - confirm the initial story premise and handoff state.
3. `世界画布 / World Canvas` - generate, revise, validate, and confirm the world-level fact base.
4. `角色 / Character Spine` - create A-tier main cast and B/C/D supporting roles, then build role context where needed.
5. `框架 / Framework` - build the global framework package and chapter-level skeleton.
6. `章节计划 / Chapter Planning` - generate or revise the light route, current chapter brief, and scene count.
7. `场景写作 / Scene Writing` - generate scene drafts, review quality/continuity results, revise, and confirm.
8. `记忆与连续性 / Memory & Continuity` - inspect memory synchronization, old-story completion, and continuity issue resolution.
9. `最终输出 / Final Output` - assemble a confirmed final story package.
10. `插件输出 / Plugin Output` - run plugin-style output flows after the final package is ready.

Important rule: the system separates draft/candidate state from confirmed story facts. User confirmation, decision records, quality gates, memory sync, and continuity checks are part of the product design.

## Local Development Without Docker

Backend:

```powershell
cd "<your clone path>"
python -m pip install -r app\backend\requirements.txt
python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd "<your clone path>\app\frontend"
npm ci
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

Open <http://127.0.0.1:5173>.

## Troubleshooting

- Backend not connected: check `docker compose ps`, `.env`, and <http://localhost:8000/health>.
- Model calls fail: verify the model key, base URL, model name, and network access.
- Port conflict: stop the process using ports `3000` or `8000`, or edit `docker-compose.yml`.
- Ordinary-mode iframe pages are missing: regenerate the package with design assets if those visual draft pages are needed.
- Reset local Docker data: remove the Docker volumes only if you intentionally want to delete local story projects.
