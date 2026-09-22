# Mac worker deployment

This directory packages the manually operated ARM64 MacBook Air worker as two
Docker Compose services. `worker` exposes port 8000 only to the Compose network;
`cloudflared` reaches it as `http://worker:8000` and creates the only public
route through an outbound tunnel. Neither service mounts the Docker socket and
the office router needs no inbound port.

The first rollout is deliberately manual. It does not create Cloudflare,
Google, R2, or media-provider credentials, choose a registry, or automate image
delivery.

## Current setup and rollout boundary

The user-confirmed running image is `ai-video-worker:f779947`, with
`cloudflare/cloudflared:2026.7.3`, on the separate MacBook Air under OrbStack.
Both services use `restart: unless-stopped`. Gradivo and its callback endpoint
remain local on the first computer. A hosted DEV rollout is future work.

The cleanup does not rebuild or replace that running image, change its three
root env files, or touch its external durable data. The commands below are an
operator runbook for a separately approved rollout, not steps executed by this
cleanup. Verify host login/start-at-login settings on the Air when doing that
rollout; this task does not inspect or change them.

## Security boundary and host account

Create one dedicated **Standard** (non-admin) macOS account, for example
`ai-video-worker`. It is the only everyday account that opens OrbStack or
operates this stack. A Mac administrator may perform OrbStack's initial installation, but the
worker stack should run under its dedicated account. Treat the dedicated Docker owner as trusted:
Docker control can inspect container environment values.

Disable automatic macOS login. Add OrbStack to this account's Login Items
and enable its start-at-login setting. After a cold Mac restart an operator must
sign in to this account once. OrbStack then starts and Compose's
`unless-stopped` policies restore both containers. Containers cannot start
before that login because OrbStack is a user session application.

## Durable host layout

While signed in as the dedicated account, keep the three discoverable Compose
environment files in the repository root and the durable worker data outside
the Git checkout. The example contract uses:

```text
/absolute/path/to/ai-video-editor/
  .env.stack.local
  .env.worker
  .env.cloudflared
/Users/ai-video-worker/ai-video-worker-data/
  state/
  scratch/
  logs/
```

Copy `env/stack.env.example`, `env/worker.env.example`, and
`env/cloudflared.env.example` to `.env.stack.local`, `.env.worker`, and
`.env.cloudflared` in the repository root. Update the absolute paths, create the
three external data directories, and set both secret files to mode `0600`:

```bash
chmod 0600 /absolute/path/to/ai-video-editor/.env.worker
chmod 0600 /absolute/path/to/ai-video-editor/.env.cloudflared
```

`.env.stack.local` contains only image references and host paths. `.env.worker`
is attached only to `worker`; `.env.cloudflared` is attached only to
`cloudflared`. All three local files are excluded by `.gitignore` and
`.dockerignore`, so they stay discoverable without entering Git history or the
image build context. Do not source either secret file into a broad interactive
shell.

SQLite is stored in `state/jobs.sqlite3`. Scratch remains job-scoped but uses a
durable host mount so an operator can inspect interrupted work. Worker-owned
file logs use the dedicated logs mount; normal container stdout remains
available through `docker compose logs`.

## Manual Cloudflare setup

Provision this outside the repository:

1. Create a named Cloudflare Tunnel and map one public DEV hostname to the HTTP
   service `http://worker:8000`. Store only its tunnel token in
   `.env.cloudflared`.
2. Put a Cloudflare Access application on the entire hostname. Add a `Service
   Auth` allow policy restricted to Gradmin's dedicated service token. Do not
   add a Bypass policy, public Allow policy, or path excluded from Access.
3. Store the Access client ID/secret only in Gradmin's development deployment
   and in a short-lived operator smoke environment. They do not belong in the
   worker or cloudflared env files.
4. Configure Gradmin to send both Access headers and its application
   `Authorization: Bearer` token. The worker independently validates the latter.

Drive OAuth, the dedicated private DEV R2 bucket/key, and provider keys are
also manually provisioned. Issue a worker-specific offline Google refresh token
and bucket-scoped R2 Object Read & Write key. Do not reuse Gradivo's refresh
token or its separate R2 read-only key.

## Build and first rollout

Choose and record an intentional cloudflared version or digest in `.env.stack.local`;
do not deploy the example placeholder or a floating `latest` tag. Build the
worker image manually from the repository root using the same tag recorded in
`AI_VIDEO_WORKER_IMAGE`:

```bash
docker build --file deployment/mac/Dockerfile --tag ai-video-worker:headless-cleanup .
```

Set these operator-only paths for the commands below:

```bash
export AI_VIDEO_STACK_ENV=/absolute/path/to/ai-video-editor/.env.stack.local
export AI_VIDEO_COMPOSE_FILE=/absolute/path/to/ai-video-editor/deployment/mac/compose.yaml
```

Render and inspect the configuration before starting it. The rendered output
must show no host `ports`, no `/var/run/docker.sock`, and three durable-data bind
mounts outside the checkout:

```bash
docker compose --env-file "$AI_VIDEO_STACK_ENV" --file "$AI_VIDEO_COMPOSE_FILE" config
docker compose --env-file "$AI_VIDEO_STACK_ENV" --file "$AI_VIDEO_COMPOSE_FILE" up --detach --no-build
docker compose --env-file "$AI_VIDEO_STACK_ENV" --file "$AI_VIDEO_COMPOSE_FILE" ps
```

Wait for `worker` to become `healthy` and `cloudflared` to remain running. If a
container fails, inspect its stdout without printing the host env files:

```bash
docker compose --env-file "$AI_VIDEO_STACK_ENV" --file "$AI_VIDEO_COMPOSE_FILE" logs --tail 200 worker cloudflared
```

The container healthcheck calls the local `/healthz` endpoint with the worker's
application Bearer token. It is not a public bypass; Cloudflare Access still
protects the entire external hostname.

## Authenticated HTTPS status smoke

Use an already accepted job UUID. This sends no media bytes: it performs four
`GET /v1/jobs/{job_id}` checks and proves that missing Access credentials,
invalid Access credentials, and a wrong application Bearer token are rejected
before confirming the real durable status.

Export the values from an approved secret source without echoing them:

```bash
export VIDEO_PROCESSING_HTTP_BASE_URL=https://worker-dev.example.com
export VIDEO_PROCESSING_SMOKE_JOB_ID=replace-with-an-existing-job-uuid
export VIDEO_PROCESSING_CF_ACCESS_CLIENT_ID=replace-me
export VIDEO_PROCESSING_CF_ACCESS_CLIENT_SECRET=replace-me
export AI_VIDEO_EDITOR_API_TOKEN=replace-me
python deployment/mac/smoke_worker_status.py
```

The script succeeds only for HTTPS, exact Cloudflare Service Auth headers, the
worker Bearer token, and a matching job snapshot.

To verify persistence, choose a terminal job, record its reported revision,
force-recreate only the worker container, wait for it to become healthy, and
run the smoke again. The job and revision must still be present because the
SQLite bind mount did not change:

```bash
docker compose --env-file "$AI_VIDEO_STACK_ENV" --file "$AI_VIDEO_COMPOSE_FILE" up --detach --no-deps --force-recreate worker
```

Do not perform this check on an active processing job: by contract, recreation
turns interrupted processing into a terminal `worker_interrupted` failure and
never silently reruns it.

## Real analysis acceptance

The status smoke above proves only routing, authentication, and durable worker
state. It does not prove Drive download, media providers, R2 upload, callback
projection, or browser playback.

After the worker env file contains a worker-specific Drive OAuth refresh token,
bucket-scoped R2 Object Read & Write credentials, and the active STT/LLM provider
keys, trigger an Analysis Job from the Gradmin Problem Builder for one confirmed
small Drive recording. A real DEV-787 acceptance run must show all of these:

1. The terminal worker result is `analysis_result.v1`, not a Gradivo mock.
2. R2 contains `jobs/{job_id}/review-proxy.mp4` and
   `jobs/{job_id}/processed-audio.flac` in the dedicated private DEV bucket.
3. The Review Proxy duration matches the complete source timeline and its audio
   stream is the processed audio; proposed cuts remain editable source-time data.
4. The authorized Gradivo editor receives a short-lived signed Review Proxy GET
   URL and plays it without receiving an R2 credential, worker URL, or object key.

Record the job UUID and operator-visible outcome. Do not report this external
acceptance as run unless the real Drive, R2, provider, callback, and browser
boundaries were all exercised with provisioned credentials.

## Real render acceptance

Run this only after a real analysis has projected its durable Processed Audio
reference into Gradivo. In Problem Builder, change and save at least one cut,
then request a render for that exact Editing Transcript.

Verify all of the following without printing either service's credentials:

1. The accepted worker job has a non-null `resolved_render_config_json` in its
   durable SQLite row before source or audio download begins. Re-submitting the
   same UUID does not change it after the env render values change.
2. The worker downloads and verifies the original Drive fingerprint and the
   referenced R2 FLAC. It does not create new analysis artifacts or call the
   transcription, denoise, or decision providers.
3. The output folder contains exactly one private file with
   `appProperties.video_processing_job_id` equal to the render job UUID. Its
   file ID remains stable across a replay. The MP4 duration reflects the saved
   half-open millisecond cut snapshot.
4. The terminal result is `render_result.v1` with Drive file ID, head revision,
   byte size, `video/mp4`, and MD5 checksum. It contains no local path, worker
   URL, provider response, or credential.
5. Gradivo atomically marks that exact attempt completed and projects a real
   Final Render Artifact. Problem Builder labels it as a Drive artifact, opens
   the stable Drive web page, and retains prior render artifacts in history.

Record the analysis UUID, render UUID, source fingerprint, output Drive file
ID, and operator-visible result. Do not report this external acceptance as run
unless the actual Drive, R2, FFmpeg, callback, Gradivo, and browser boundaries
were exercised with provisioned credentials.

If the worker reports `duplicate_output_artifacts`, do not delete or choose a
file automatically. Inspect all UUID-marked Drive files and reconcile them
manually before creating a new Gradivo retry attempt.

## Cold restart runbook

1. Power on the Mac and sign in once as the dedicated non-admin Docker owner.
2. Wait for OrbStack to report that its engine is running.
3. Run the `docker compose ... ps` command above. Both services should have
   returned through `unless-stopped`; do not run `up` unless they are absent.
4. Run the authenticated HTTPS smoke against an existing terminal job.
5. If OrbStack did not start, start it in this account, then inspect
   container status and logs. Do not enable automatic macOS login as a fix.

Stopping or recreating containers does not remove the external state, scratch,
or log directories. Never use a cleanup command that deletes those host paths
during routine rollout or recovery.
