# Local startup verification — 2026-10-08

Verified the current checkouts in `/Users/markosandalj/var/www/ai-video-editor`
and `/Users/markosandalj/var/www/gradivo2.0`. Gradivo reuses the existing local
`gradivo-main` project/database and its normal `.env`. The worker now uses the
same Dockerfile, Compose service, entry point, healthcheck, container user and
runtime dependencies as deployment. The earlier native worker was stopped.

## Current verified setup

- Standard Gradivo `just up` succeeded with the existing local project/domain
  overrides. All services reported healthy and the existing database remained.
- Worker `deployment/local/run.sh` executed the documented Docker Compose
  build/start command successfully. The `ai-video-worker-local` project contains
  only a healthy worker, published at `127.0.0.1:8000`; no tunnel was started.
- The worker runs as UID 10001 and successfully writes to each persistent local
  state, scratch and log directory using the shared deployment bind mounts.
- `just video-worker-local-check` passed inside Django: authenticated worker
  health (200), unknown-job status lookup (404), Problem Builder root redirect,
  subjects authentication redirect and nonempty login HTML.
- `deployment/local/smoke.py` passed inside the actual Docker worker. Its health
  returns 401 without a token and 200 with a token. Gradivo's callback returns
  401 without a token; a valid token reaches unknown-job lookup (404).
- Django uses the existing `http` backend and a local URL from `.env`, without a
  separate backend type or worker-specific Gradivo startup configuration.
  Local HTTP requires DEBUG and an explicit local hostname. HTTPS retains both
  Cloudflare Access credentials; all worker requests retain Bearer auth.
- Eight targeted Django backend tests passed (60 deselected, 13 subtests), and
  seven existing worker deployment tests passed.
- Targeted Ruff, Wagtail revision guard, shell syntax and diff whitespace checks
  passed.
- Configuration updates only selected Gradivo env keys, preserves unrelated
  values and retains separate local API/callback tokens. The old additional
  Gradivo env file and its optional Compose loading were removed. Deployment
  env files remain unchanged; no credentials were printed.

The local nginx root redirect addresses the reproduced empty Next base-path
response by routing `/pb/` to its intended `/pb/subjects/` destination.

## Verification boundaries

The in-app browser previously reported `net::ERR_BLOCKED_BY_CLIENT` for the
local domain. Page checks are HTTP checks; visual browser acceptance is not
claimed. No analysis/render jobs, paid AI calls or external Drive/R2 media
requests were made. External credential validity and complete real-media
analysis, render and playback still require a chosen test recording.

The database-default regression checks pass. The broader worktree runtime
script stops on pre-existing `next-typesafe-url -w` package dev scripts in
Problem Builder/business-insights, unchanged by this work. That failure is
separate from the successful standard startup and connection checks above.

Both local Docker application stacks remain running.
