# Headless worker cleanup

Base: `f779947` on `codex/ai-video-editor-integration`. The cleanup branch is
`codex/headless-worker-cleanup`; PR #3 is its dependency, not its publication target.

## Inventory and reference checks

Before removal, all Git-tracked paths were inventoried. Python imports, including
imports inside functions and package `__init__` exports, were traced from
`worker.app`, `worker.healthcheck`, `AnalysisUseCase` and `RenderUseCase`.
CLI command bodies, dynamic model imports, package scripts, Docker COPY/RUN/
ENTRYPOINT and Compose healthcheck were checked separately. No worker operation
shells out to the old CLI. The only dynamic provider imports are the retained
LangChain model classes; FFmpeg/ffprobe remain required external programs.

| Candidate | References and decision |
| --- | --- |
| `frontend/` (React/Vite, npm manifest/lock, generated API types, assets, config) | Used only by the local review server and old UI documentation; remove all tracked files. No Docker COPY, worker call or runtime asset dependency. |
| `ai_video_editor/web/` | Old `/api/videos`, review/diff routes and static hosting, constructed only by `review-serve`; remove. |
| `ai_video_editor/review/` | `review.v4`, editable sidecar export/save and reviewed EDL, called only by CLI/web; remove. Gradivo owns edits. |
| `ai_video_editor/cli/`, `ai_video_editor/__main__.py` | `process`, `batch`, `qa`, `eval-decisions`, `dump-alignments`, `eval-models`, `eval-section-editor`, `review-export`, `review-serve`, `review-render`; remove. `process`/`batch` compose analysis and render but are not called by either operation or Docker. |
| `ai_video_editor/experiments/` | Model manifests, cutting reconstruction/scoring, repeat audit, section pilot/checkpoints; invoked by old evaluation CLI only; remove. |
| `ai_video_editor/qa/` | Corpus alignment, ground truth, continuity, splice/spectrogram comparison, HTML reports and regression score storage; used only by CLI/experiments/web diff and their tests; remove. Active media tests do not use it. |
| `ai_video_editor/logging/` | CLI run/video log sinks only; remove. Worker bounded file logging in `worker.app` and UUID event logging remain. |
| `analysis.py` persistence adapters | Worker always used no-op persistence and forced fresh analysis. Remove CLI transcript/EDL/debug/audio-envelope sidecars and the now-unused persistence/force seam; keep the actual analysis pipeline and injected transcriber/decision maker. |
| `duplicate/debug.py`, `transcription/cache.py` | Only CLI persistence and retired QA/review use them; remove after removing package exports. |
| `audio/snap.py` sidecar helpers | `audio_envelope_path_for`, write/load/ensure helpers serve the local UI only; remove. Keep envelope computation, peaks, acoustic split points and boundary snapping used by analysis/Gradivo results. |
| `config/settings.py` CLI settings and Python config loader | `output_dir`, `log_level`, combined pipeline render config and arbitrary Python config-file loading were CLI-only; remove. Keep analysis settings and standalone `RenderConfig` used by worker snapshots. |
| `llm.py` experiment helpers | `with_id`, `public_dict`, `direct_gemini_model_config` have only experiment callers; remove. Keep dynamic provider construction, model defaults, fallback and observability. |
| `transcription/grammar_report.py` | **Keep** the report writer: the active transcription pipeline writes job-scoped diagnostics. Remove the unused review cache reader; retain grammar algorithm/report tests. |
| `iterations/` | Old corpus baseline/promotion instructions and history reference local sidecars/retired scorers; remove tracked records. Algorithm implementations remain unchanged. Historical evidence is recoverable from the base commit. |
| `tasks/`, `TASK_MANAGEMENT.md`, `.cursor/rules/`, `.cursorignore` | Old phase roadmap and automatic iteration/UI workflow instructions, no runtime callers; remove. This cleanup explicitly replaces their previous workflow. |
| `PROJECT_DESCRIPTION.md`, `ONE_VIDEO_WORKFLOW*.html` | Superseded end-user editor/CLI/product plans and visualizations; remove. Current scope is in README, CONTEXT and worker docs. |
| `MISTAKE_PATTERNS.md`, `SECTION_EDITOR_EVALUATION.md` | Historical local corpus/model evaluation instructions and scores; remove with retired evaluation workflow. Do not change selected models, prompts, thresholds or correction algorithms. |
| `tests/test_cli_analysis_composition.py`, `test_diff.py`, `test_review.py`, `test_qa.py` | Tests of removed entrypoints, UI DTOs and retired scoring tools; remove with their implementation. |
| `tests/test_model_experiments.py` | Move its dynamic LLM adapter regression to `test_llm.py`; remove tests of deleted manifests/runners/scorers. |
| `tests/test_section_editor.py::TestWordLevelScoring` | Four tests exercise deleted QA scorer/pilot, not the section editor; remove only this class. Keep all section segmentation, deletion guard, retry/fallback and correction tests. |
| `tests/fixtures/` | No tracked fixtures exist at the base commit. Never delete this ignored media/corpus directory. Required existing JSON fixtures are copied read-only from the original checkout to tracked `tests/data/`; no audio/video or output is copied. |
| `pyproject.toml`, `uv.lock` | Remove Typer and the `ai-video-editor` script; retain `ai-video-worker` and all active media/provider dependencies. Regenerate lock without upgrading retained packages. |
| `.dockerignore`, `.gitignore` | Remove frontend-specific entries; keep protection for secrets, ignored legacy media/output, caches and scratch. Docker remains a Python-only package build. |
| `deployment/mac/` | Keep Dockerfile, Compose, healthcheck, env examples and status smoke script. Update stale host/runtime prose to the user-confirmed ARM64 MacBook Air/OrbStack setup. No deployment action. |
| `CONTEXT.md`, `docs/adr/0001-keep-ai-video-editor-headless.md`, `docs/http-api.md`, `docs/integration-completion.md`, `README.md` | Keep and align scope/host descriptions; preserve all public request/result/auth/idempotency semantics. |
| `.agents/skills/`, `skills-lock.json`, `.codex/config.toml` | General agent tooling, not the application frontend or worker runtime; leave untouched. |
| `.python-version`, package initializers, `tests/__init__.py`, `tests/conftest.py` | Keep Python/package infrastructure and any fixtures with active consumers. |

## Retained execution paths

- `ai-video-worker` → `worker.app` → service/store/outbox/executor →
  `run_configured_media_job`. Authenticated submission, UUID idempotency,
  configurable capacity, durable SQLite snapshots and callback retries remain.
- Analysis: Drive identity/fingerprint/download → audio extraction/denoise/silence
  → ElevenLabs + grammar → section editor, deterministic local corrections,
  audio false starts/asides → acoustic snapping → uncut MP4 Review Proxy + FLAC
  → R2 and `analysis_result.v1`.
- Render: immutable persisted config and Gradivo cut snapshot → Drive source + R2
  audio → existing FFmpeg assembly → UUID-marked Drive MP4 and `render_result.v1`.
- Process-group deadlines, healthcheck, Docker/Compose isolation and Cloudflare
  tunnel remain. Final Drive-to-Gradivo/Mux upload stays manual, with no new log
  or bookkeeping workflow.

## Restore and data boundary

Only exact paths from `git ls-files` are removed. No recursive directory deletion,
media/output cleanup, secret-file read, SQLite mutation, remote-worker connection
or container/tunnel action is part of this task. Existing runtime data remains
outside the checkout. The three root env files stay ignored.

Inspect any removed file with `git show f779947:path/to/file`. Recover selected
paths in a separate branch/worktree with
`git restore --source=f779947 -- path/to/file`; revert the cleanup commit to
restore the whole tracked tree if desired. Ignored media was never in Git and is
not affected by these restoration commands.

## Verification

- Initial clean-worktree run: 168 passed / 44 failed. Every failure was a
  missing ignored JSON fixture, not an implementation regression. Restoring the
  six existing worker contract examples and five full transcript inputs made
  the unchanged baseline pass **212 tests**. Their original copies were not
  modified. `tests/data/README.md` records provenance and source hashes.
- After cleanup and locked environment sync: **137 passed**, no skips. The 75
  removed tests covered retired CLI/review/diff/QA/experiment behavior. The
  dynamic LLM adapter test was moved, not dropped; all active media/worker and
  correction regressions remain. The two pre-existing dependency warnings are
  LangGraph's future deserialization default and Starlette's httpx deprecation.
- Added checks to existing tests: stale local-editor sidecars cannot feed or
  overwrite analysis; the worker does not expose `/`, `/api/videos`, `/docs` or
  `/openapi.json`.
- `uv lock`, `uv sync --locked --extra dev`, `uv build` passed. Only Typer,
  shellingham, rich, markdown-it-py and mdurl left the lock; all 95 retained
  package versions are unchanged. Wheel inspection found only the worker
  console script and no retired modules or bytecode caches.
- Local `linux/arm64` build of `deployment/mac/Dockerfile` passed under the local
  OrbStack socket with a distinct tag `ai-video-worker:headless-cleanup-local`.
  This is a verification image, not a deployed replacement for `f779947`.
- That image ran as its configured non-root user in a disposable read-only
  container with no network, no host mounts, fake tokens and tmpfs state. The
  actual entrypoint, authenticated HTTP health, unauthorized rejection, absence
  of retired routes, installed runtime/provider imports and
  `python -m ai_video_editor.worker.healthcheck` all passed. Real Linux FFmpeg
  extraction, denoise, FLAC/proxy generation and cut-snapshot render passed on
  generated tiny media; STT/decision providers were injected test adapters.
  The disposable container was stopped and automatically removed.
- Compose configuration resolved with disposable fake env files: only service
  network exposure, separate secrets, three external durable mounts,
  healthcheck and both `unless-stopped` policies were preserved. No actual
  root env file was opened. Git still ignores all three root env paths.
- Final internal-import/reference scan and `git diff --check` passed. Worker
  contracts, SQLite/store, callback delivery, executor/deadlines, provider
  implementations, Dockerfile and Compose were not changed.

Live Drive, R2, transcription/LLM providers, callback delivery to Gradivo and
cross-app browser acceptance were not exercised by this cleanup. No production
or remote MacBook Air access, hosted DEV rollout, cloud fallback work or
render-quality tuning occurred. A separately approved rollout must still verify
both real operations end to end.
