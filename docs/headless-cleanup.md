# Headless worker cleanup

Base: `f779947` on `codex/ai-video-editor-integration`. Work is local on
`codex/headless-worker-cleanup`; PR #3 is the dependency, not the publication target.

The product is a headless analysis/render worker. The editor moved to Gradivo.
Implementation phases, iteration records and tools for improving the media flow
remain supported development assets. Runtime reachability alone is not a reason
to delete a development tool or historical decision.

## Inventory and final scope

Python imports (including function-local imports and package exports), actual
callers, development commands, Docker COPY/RUN/ENTRYPOINT and Compose healthcheck
were checked. Dynamic LangChain model classes and FFmpeg/ffprobe remain required.

| Area | Final decision and reference evidence |
| --- | --- |
| `frontend/` | Remove React/Vite application, assets, generated API types, npm manifest/lock and build/lint configuration. No worker or Docker dependency. |
| `ai_video_editor/web/`, `review/` | Remove local `/api/videos`, review/diff server, static hosting and editable review sidecar DTO/export/save code. Used only by the relocated editor. |
| `ai_video_editor/cli/`, `__main__.py` | Keep development `qa`, `eval-decisions`, `dump-alignments`, `eval-models`, `eval-section-editor`. Remove combined `process`/`batch` and `review-export`/`review-serve`/`review-render`. The worker does not invoke this CLI. |
| `ai_video_editor/qa/` | Keep corpus alignment, ground-truth/word scoring, continuity, splice/spectrogram checks, reports and regression measurements used by development commands and experiments. |
| `ai_video_editor/experiments/` | Keep model manifests, reconstruction/scoring, repeat audit, section pilot, safety gates and checkpoints. These support future analysis-flow iterations. |
| `ai_video_editor/logging/` | Keep run logging used by development QA. Remove per-video handlers used only by removed process/batch commands. Worker bounded logs remain separate. |
| `analysis.py` persistence adapters | Worker used no-op persistence and fresh analysis. Remove unused CLI transcript/EDL/debug/audio sidecar persistence and force switch. Keep the real analysis pipeline and injectable transcriber/decision maker. |
| `duplicate/debug.py`, `transcription/cache.py` | Remove exporters/cache used only by old processing/review. QA owns its separate ground-truth cache and does not import these modules. |
| `audio/snap.py` | Remove local-editor envelope path/write/load/ensure helpers. Keep envelope computation, peaks, acoustic split points and boundary snapping used by worker results. |
| `config/settings.py` | Keep analysis settings, standalone worker `RenderConfig`, and output/log settings used by development QA. Remove arbitrary Python config-file loader and combined CLI render settings with no callers. |
| `llm.py`, `decisions.py` | Keep model helpers and explicit experiment override used by restored runners. Default models, prompts, thresholds and active correction algorithms are unchanged. |
| `transcription/grammar_report.py` | Keep active job-scoped diagnostic writer. Remove unused local review cache reader. |
| `iterations/` | Keep all four records: workflow, current baseline, decision history and baseline JSON. Document that July UI/production references are historical; today local EDLs are evaluation data and Gradivo owns edits. |
| `tasks/`, `TASK_MANAGEMENT.md`, `.cursor/rules/`, `.cursorignore` | Keep all implementation phases and development instructions. Preserve task statuses/history; note current headless scope in the task-management entry document. |
| `PROJECT_DESCRIPTION.md`, `ONE_VIDEO_WORKFLOW*.html` | Keep project plan and historical workflow visualizations as development references. Historical UI descriptions do not imply a second current editor. |
| `MISTAKE_PATTERNS.md`, `SECTION_EDITOR_EVALUATION.md` | Keep error-pattern research and model-selection evidence for future iterations. No new corpus evaluation or quality tuning is claimed. |
| Tests | Keep worker/media/algorithm tests plus restored QA, experiment and word-scoring tests. Only removed CLI processing/review/diff behavior loses its tests. |
| `tests/fixtures/`, `tests/data/` | Never delete ignored user media/corpus/output. Commit six existing contract JSON examples and five full transcript regression inputs under `tests/data/` so fresh checkouts can run tests. Full evaluation corpus remains local. |
| `pyproject.toml`, `uv.lock` | Keep `ai-video-worker` as the installed service entrypoint; run development CLI via `python -m ai_video_editor`. Typer moves to the `dev` extra. All original package versions remain unchanged. |
| `.dockerignore`, `.gitignore` | Remove frontend-specific exclusions; preserve secrets, local corpus/output, caches and scratch protection. |
| `deployment/mac/` | Keep Dockerfile, Compose, healthcheck, env examples and status smoke. Align prose/example pins with the user-confirmed ARM64 MacBook Air/OrbStack setup. No deployment. |
| README, CONTEXT, ADR, HTTP and integration docs | Keep and align current scope; preserve public request/result/auth/idempotency semantics. Link development phases and iteration workflow. |
| `.agents/skills/`, `skills-lock.json`, `.codex/config.toml`, `.python-version` | Keep agent tooling and Python/package infrastructure. |

## Preserved product behavior

`ai-video-worker` accepts authenticated jobs, reserves configurable capacity and
persists Gradivo UUID/idempotency state, render configuration and callback outbox
in SQLite. Subprocess deadlines terminate processing before releasing capacity.

Analysis verifies/downloads Drive media, processes audio, transcribes and proposes
cuts, then writes an uncut Review Proxy and FLAC to R2. Render uses an immutable
Gradivo cut snapshot, original Drive image stream and retained R2 audio to create
a UUID-marked final Drive MP4. Worker contracts, store, callbacks, executor,
providers, Dockerfile and Compose are unchanged. Final Drive-to-Gradivo/Mux upload
stays manual, without additional bookkeeping.

## Verification and limits

The initial `f779947` checkout missed ignored test JSON inputs: 168 tests passed
and 44 failed for missing fixtures. Restoring the existing inputs yielded 212
passing baseline tests. The final scope retains all development QA/experiment
coverage; only tests of removed product entrypoints/UI are retired.

After restoration, **192 tests pass**, with no skips and the same two existing
LangGraph/Starlette dependency warnings. All five development commands pass
`--help`; all five retired processing/review commands are rejected. Locked
installation and wheel/sdist build pass. All 100 original locked package
versions are unchanged; Typer and its CLI dependencies belong to the `dev` extra.

The updated local ARM64 Docker build passes. Its installed worker entrypoint and
both operations import successfully without Typer. This check runs in a
one-shot read-only container with no network or host mounts. The active Air
worker and its pinned image are unchanged.

The earlier cleanup already verified isolated Linux FFmpeg analysis/proxy/FLAC/
render, authenticated entrypoint/healthcheck and Compose resolution using fake
env files. The restoration does not change the Dockerfile, Compose, public
contracts or provider implementations.

No live Drive/R2/STT/LLM/callback/Gradivo browser acceptance, remote MacBook Air
access, production change, hosted DEV rollout, cloud fallback or render-quality
tuning is performed. A separately approved rollout must verify real operations.

## Restore and data boundary

Only precise Git-tracked paths are removed. Root `.env.worker`, `.env.cloudflared`
and `.env.stack.local` remain ignored and were not read or changed. Original
checkout and external durable state/scratch/logs remain untouched.

Inspect historical content with `git show f779947:path/to/file`, or recover a
selected path using `git restore --source=f779947 -- path/to/file` on a separate
branch/worktree. Current phases and iteration records are already present in this
branch; no recovery is needed for them.
