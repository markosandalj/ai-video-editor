# AI Video Editor worker

A headless media worker for Gradivo with two operations:

- **Analysis** verifies and downloads a Drive recording, processes audio,
  transcribes speech and proposes cuts. It returns source-time transcript,
  waveform and cut ranges, plus a private uncut Review Proxy and lossless
  processed audio in R2.
- **Render** applies Gradivo's confirmed immutable cut snapshot to the original
  Drive video and retained processed audio, then uploads the final MP4 to Drive.

Gradivo owns the queue, editor, permissions and editorial state. The worker owns
execution, SQLite job snapshots, callback retries and job-scoped scratch. Final
upload from Drive into Gradivo/Mux is manual.

## Development

Python 3.13+, [uv](https://docs.astral.sh/uv/), FFmpeg/ffprobe and libsndfile are
required. There is no Node build, frontend, local review server or combined
analysis/render CLI.

```bash
uv sync --locked --extra dev
uv run --extra dev pytest -q
uv build
```

Tests use committed JSON contract/transcript data and generated tiny media in
pytest temporary directories. External providers are replaced by test adapters;
no live credentials, Drive/R2 access or local video corpus is required.

## Runtime

The only installed application command is `ai-video-worker`. Configure it using
[worker env examples](deployment/mac/env/worker.env.example) and the
[Mac deployment runbook](deployment/mac/README.md). Compose loads `.env.worker`
and `.env.cloudflared` separately; `.env.stack.local` supplies image references
and external durable-data paths. All three root files remain ignored.

Docker installs the locked Python package and starts `ai-video-worker`. The
worker exposes authenticated job submission/status and healthcheck endpoints.
Each job runs in a subprocess with a configurable deadline and process-tree
termination. Render configuration and callback outbox survive worker restarts.

The current host is a separate ARM64 MacBook Air under OrbStack. The currently
running image is `ai-video-worker:f779947` and the tunnel is pinned to
`cloudflared:2026.7.3`; this cleanup does not deploy a replacement.

## Contracts and maintenance

- [Domain language](CONTEXT.md)
- [HTTP contract](docs/http-api.md)
- [Headless architecture decision](docs/adr/0001-keep-ai-video-editor-headless.md)
- [Integration completion scope](docs/integration-completion.md)
- [Cleanup inventory, restoration and verification](docs/headless-cleanup.md)

The active analysis implementation remains in `analysis.py`, `audio/`,
`transcription/`, `decisions.py` and `duplicate/`. Rendering remains in `render/`;
HTTP execution, providers and persistence remain in `worker/`. Historical UI,
CLI and evaluation tools can be recovered from Git at `f779947`.
