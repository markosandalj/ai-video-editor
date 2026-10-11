# Local Gradivo + video worker

Keep the same application and Docker runtime across local, dev and production.
Use environment values for URLs, tokens, credentials, concurrency and data paths.
Gradivo uses its existing `.env` and standard `just up`. The worker uses the
existing deployment Dockerfile and Compose service, with a small local overlay
for building this checkout, publishing a local port and resolving the local
Gradivo hostname. No Cloudflare tunnel starts locally.

The worker has no separate UI; the editor lives in Gradivo Problem Builder.
Requirements: Docker/OrbStack and `just`; `uv` is needed only for the optional
configuration helper and host-side tests. Python, FFmpeg and native libraries
for the worker are installed by the same Dockerfile used for deployment.
Gradivo needs its normal `.env` and database; follow the sibling repository's
`docs/local-worktree-dev.md`.

## Configure once

Choose the Gradivo URL with `just worktree-url`. If a local project already runs
from the same physical checkout, reuse its project and domain instead of
starting duplicate development servers. In this checkout they are
`gradivo-main` and `main.gradivo.localhost`.

From the worker repository:

```bash
uv run --locked python deployment/local/configure.py \
  --gradivo-dir ../gradivo2.0 \
  --callback-url http://main.gradivo.localhost
```

The helper creates ignored `.env.worker.local` and updates only worker-related
values in Gradivo's existing `.env`. It generates separate API/callback tokens,
retains them on later runs and copies existing worker media credentials without
printing them. Both files are private (0600). Existing deployment env files are
read only. You can maintain these env values directly after initial setup.

`.env.worker.local` selects the shared and local Compose files through
`COMPOSE_FILE`, a separate `COMPOSE_PROJECT_NAME`, the image, published port and
local data directories. State, scratch and logs persist under
`.ai_video_editor_tmp/local-worker/`; deployment data is separate. The worker
uses the container paths defined in the shared deployment service.

Gradivo keeps its own R2 key and uses the worker's endpoint/bucket for playback.
The helper verifies credential presence, not external validity or permissions.

## Start and stop

From the worker repository:

```bash
docker compose --env-file .env.worker.local up --build --detach --wait worker
```

`bash deployment/local/run.sh` is a shorthand for exactly this command.
It runs the shared Docker worker service; the local overlay leaves cloudflared
behind an inactive profile. The tunnel env example supplies only unused Compose
interpolation values, and no real tunnel token is loaded locally.

From Gradivo:

```bash
COMPOSE_PROJECT_NAME=gradivo-main LOCAL_DOMAIN=main.gradivo.localhost \
  just up
```

For a fresh worktree use plain `just up` and its corresponding callback URL.
The project/domain overrides above reuse this checkout's existing database and
are unrelated to video processing. There is no worker-specific Gradivo startup
command, extra env file or startup overlay.

Open `http://main.gradivo.localhost/pb/`. Gradivo calls the worker through
`http://host.docker.internal:8000`. The Docker worker resolves the local Gradivo
hostname to the Docker host and calls its existing Traefik entry point. The
usual `http` backend permits local HTTP only with Django DEBUG and a hostname
of localhost, 127.0.0.1 or host.docker.internal. HTTPS origins keep both
Cloudflare Access credentials. Bearer authentication is always required.

After changing env values, rerun the respective startup command to recreate
containers with the new values. Code changes in the worker require rebuilding;
Gradivo keeps its existing development reload behavior.

```bash
# Worker repository; preserves state/scratch/log directories.
docker compose --env-file .env.worker.local down
# Gradivo; use the same project/domain selection as startup.
COMPOSE_PROJECT_NAME=gradivo-main LOCAL_DOMAIN=main.gradivo.localhost just down
```

## Verify both directions

From Gradivo:

```bash
COMPOSE_PROJECT_NAME=gradivo-main LOCAL_DOMAIN=main.gradivo.localhost \
  just video-worker-local-check
```

From the worker repository, run the callback check inside the actual container:

```bash
docker compose --env-file .env.worker.local exec -T worker python - \
  < deployment/local/smoke.py
```

These checks prove authenticated health/status access from Django, Problem
Builder routing to nonempty login HTML, and callback routing/authentication
from the Docker worker. They use unknown job UUIDs, create no jobs and make no
paid AI or external media requests. Real analysis/render/playback needs a chosen
local recording and the acceptance checks from `deployment/mac/README.md`.

## Production consumption

Consumption tracking uses `PRODUCTION_CONSUMPTION_ENABLED=true` in the existing
Gradivo `.env` and this worker's env. Its default is false. Gradivo forwards
authenticated work intervals and provider receipts to the existing PostHog
project, using its existing `NEXT_PUBLIC_POSTHOG_KEY` and `POSTHOG_HOST` settings.
Local/dev events carry their environment and `is_test=true`.

The worker temporarily stores receipts in its existing SQLite until Gradivo
acknowledges them. Gradivo temporarily queues the events until PostHog accepts
them. Both queues delete delivered payloads; PostHog owns the lasting evidence.
Existing Celery/beat handles delivery without another service or startup command.
Production consumption scopes disable duplicate LangSmith tracing; evaluations
outside those scopes retain their existing LangSmith behavior.

PostHog is the destination for the overview and CSV, and its native Notion
connector imports reported hours hourly. No app-maintained AI price list is
used by this delivery flow. Receipts provide charged amounts; unverified
automatic estimates stay excluded from the business summary. The dashboard,
CSV and removal of the old prototype UI are complete. The real local media
acceptance test passed on 2026-10-11: analysis, browser playback, a saved manual
cut, final Drive render, measured editor work and provider usage in PostHog.

See the sibling repository's [feature documentation](../../../gradivo2.0/docs/production-consumption.md)
and [PostHog integration verification](../../../gradivo2.0/docs/production-consumption-posthog-integration.md).
The [real media validation](../../../gradivo2.0/docs/production-consumption-media-validation.md)
records the fixture, artifacts, usage and remaining limits. This was a local
test, not a deployment.
