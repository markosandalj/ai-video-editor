# Keep AI Video Editor as a headless media-compute worker

`ai-video-editor` remains a separate repository and deployment because video
analysis and rendering must not consume Gradivo's production resources. It
accepts authenticated machine jobs, keeps operational processing state and
temporary artifacts, and returns analysis or render results to Gradivo. The
production editor, human review, permissions, and canonical editorial state
live in Gradivo's Problem Builder; the current local review UI may remain only
as a development and migration reference. Media moves directly between Google
Drive, the worker, and a private Cloudflare R2 Standard bucket rather than
through the Gradivo application server. The worker uses its own configured Drive
credentials; Gradivo sends file identity and an integrity fingerprint, never a
Google OAuth token. Gradivo owns the only pending-work queue. This
worker merely enforces `MAX_NUMBER_OF_JOBS`, initially `1`, as a CPU and memory
protection ceiling; Gradivo's separate in-flight setting is authoritative for
normal dispatch concurrency. The worker rejects new distinct jobs when its
safety ceiling is reached and never introduces a second scheduler. Terminal job
results and undelivered Gradivo callbacks are persisted outside process memory
and survive worker restarts; callback delivery is retried until Gradivo
acknowledges it.

The initial Mac worker uses one SQLite database on durable local storage for
accepted job payloads and hashes, current and terminal snapshots, resolved
render configuration, and a callback outbox. Its path comes from
`VIDEO_PROCESSING_STATE_DB_PATH`. Job acceptance and its initial outbox entry
commit atomically before `201 Created`. SQLite is hidden behind an internal
job-store interface so a future cloud executor may use another durable adapter
without changing the application contract. It is operational state, not a
second Gradivo queue or editorial store; media remains in Drive/R2 and scratch
files remain job-scoped.

A worker or host restart never silently reruns an accepted job. At startup, any
attempt still stored as `processing` becomes terminally `failed` with retryable
code `worker_interrupted`, a newer snapshot revision, and a callback-outbox
entry. Gradivo's explicit Retry action creates the replacement job UUID and
records `retry_of`. Already-terminal jobs remain unchanged and resume only any
unacknowledged callback delivery.

The Mac runtime uses one long-lived FastAPI control process and at most one
media-execution subprocess. The control process alone owns SQLite, HTTP
acceptance, capacity, snapshot revisions, and callback-outbox delivery. It
starts a subprocess immediately after durably accepting a job; no internal
pending queue, Redis, or Celery worker is introduced. The subprocess runs either
operation and reports events to the control process, keeping the HTTP boundary
responsive and isolating media-pipeline failures.

The initial primary worker deployment is a dedicated, always-on office Mac
mini. The same processing implementation must also support an on-demand cloud
fallback with no idle compute charge. Both execution targets consume the same
immutable job payload, use the same job UUID and artifact keys, and deliver the
same revisioned callbacks; the fallback is not a second editorial workflow or
pending-work queue.

The cloud fallback is a manually activated cold standby in v1. It may execute
only a Gradivo job that remains `queued` and whose primary-worker acceptance is
known not to have occurred. Transport timeouts never trigger automatic
failover, because the Mac worker may have persisted the job before its response
was lost. Ambiguous attempts must be reconciled before another executor runs
them.

Deployment routing is environment-only configuration. Gradivo reads the worker
origin from `VIDEO_PROCESSING_HTTP_BASE_URL`; the worker reads Gradivo's callback
origin from `GRADIVO_VIDEO_CALLBACK_BASE_URL`. Neither hostname is hard-coded or
included in a job payload. The first real end-to-end topology is hosted
development Gradivo at `https://gradmin.com.hr` connected to the office Mac mini
worker, but the same contract applies to another environment or executor.

Cloudflare Tunnel supplies the Mac worker's initial public HTTPS origin through
an outbound `cloudflared` connection, without an inbound office-router port.
Only job and callback control traffic uses the tunnel; media still moves
directly through Drive and R2. Cloudflare Tunnel replaces the earlier ngrok idea
for this deployment, but remains a replaceable routing component rather than an
application-contract dependency.

The initial worker uses the same automation Google user identity as Gradivo but
receives a separately issued offline OAuth refresh token. Its
`GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, and
`GOOGLE_DRIVE_REFRESH_TOKEN` values are worker-only environment secrets and
never enter SQLite or an integration payload. Replacing that identity later
does not change the job contract.

The first Mac deployment is containerized immediately. Docker Compose runs one
worker container and one separately configured `cloudflared` container; neither
is installed as a native host process. The worker image contains the same entry
point and both operations that a future cloud executor will run. Persistent
SQLite, scratch, and log paths are explicit mounts outside the checkout, and
each container receives only its own secrets and mounts. Containerization is
part of the first real-video tracer bullet rather than deferred until fallback.
Secrets enter the Mac stack through two separate mode-`0600` host files in the
repository root: `.env.worker` is attached only to the worker, and
`.env.cloudflared` only to the tunnel container. Both are excluded by
`.gitignore` and `.dockerignore`; they are never committed, copied into an
image, or shared across services. The dedicated Docker owner is trusted
because Docker administration can inspect container environment values. A
future cloud secret store may replace these files without changing the worker
contract.
One dedicated non-admin macOS service account owns Docker Desktop and is not
used for normal office work. After a cold Mac restart, an operator signs in to
that account once; Docker Desktop starts at login and the Compose restart policy
restores both containers. Automatic macOS login and a separately managed
headless Linux VM are not part of the first E2E deployment.

Image distribution and rollout automation are deferred until both real worker
operations work end to end. For the initial tracer bullet, the operator manually
ensures the intended image and Compose containers are running on the Mac. No
decision is made yet about local builds, a registry, CI, immutable image
references, or automatic deployment; that is a later infrastructure task.

The concrete fallback platform remains undecided. It is a separate research
task after the first real end-to-end video proves both worker operations and
provides measured runtime and resource evidence. No cloud provider is selected
by this decision.

HTTPS requests in each direction use separate static Bearer tokens supplied as
environment variables; v1 has no token refresh or signing protocol. Progress
and terminal state are pushed as revisioned snapshots. Progress delivery is
best effort, while terminal snapshots are retried until acknowledged; Gradivo
does not normally poll the worker. Each deployment reads its single Gradivo
callback base URL from the environment rather than accepting arbitrary
per-request callback destinations.

The Cloudflare-published Mac worker origin additionally has a Cloudflare Access
`Service Auth` policy restricted to Gradmin's dedicated service token and no
public bypass. Gradmin supplies that token from
`VIDEO_PROCESSING_CF_ACCESS_CLIENT_ID` and
`VIDEO_PROCESSING_CF_ACCESS_CLIENT_SECRET`; after Access accepts the request,
the worker independently validates `AI_VIDEO_EDITOR_API_TOKEN`. Cloudflare
credentials protect the initial Mac route but are not part of the worker's
provider-independent HTTP contract. Callbacks to Gradivo do not use them.

Terminal failures expose a stable machine code, the failure stage, and a short
sanitized message. They never expose stack traces, stderr, third-party response
bodies, credentials, or secrets. Detailed logs remain worker-owned and use the
shared job UUID for correlation. Gradivo derives retryability from its stable
error-code registry; the worker sends no terminal retryability flag and unknown
codes fail closed as non-retryable.

Private Review Proxies live at deterministic job-scoped keys in the configured
Cloudflare R2 Standard bucket through its S3-compatible API. The worker returns
stable object metadata, while Gradivo creates short-lived signed GET URLs for
authorized Problem Builder users. No public or presigned artifact URL is
persisted.

A Review Proxy preserves the complete uncut Raw Recording timeline but uses the
processed analysis audio. Proposed and human cuts remain Gradivo editor state
and are previewed by playback skipping rather than burned into the proxy. This
keeps transcript, waveform, and cut coordinates aligned to source time and lets
the human restore any proposal. Proxy codec and quality remain worker
configuration outside the current milestone.

The first real end-to-end deployment uses a dedicated private DEV R2 bucket,
separate from production rather than isolated only by object-key prefixes. The
worker has its own bucket-scoped `Object Read & Write` credentials; Gradivo has
separate bucket-scoped `Object Read only` credentials for signing authorized
GET requests. Neither service receives an account-admin token or shares a
common read/write key. Bucket and credentials remain environment configuration,
not job-contract data.

Analysis also persists a lossless processed-audio FLAC at a deterministic
job-scoped key. A later render combines the original Drive video stream with
that audio instead of repeating preprocessing or relying on local scratch files
surviving human review.

The service boundary uses its own versioned `analysis_result.v1` DTO rather
than exposing the local editor's `review.v4` model. Filesystem paths and human
review state stay internal; a dedicated adapter emits only portable processing
results for Gradivo.

The implementation exposes two reusable headless application use cases:
`AnalysisUseCase.execute(...)` and `RenderUseCase.execute(...)`. One worker
media subprocess calls one use case for each accepted job, while the existing
CLI may retain its one-command workflow by composing both sequentially. The
worker neither shells out to the CLI and parses sidecars nor duplicates the
processing pipeline.

Current human cut ranges live in one mutable Gradivo database field. A render
job carries its own immutable snapshot of those ranges, and the worker derives
any full render EDL only in job-scoped scratch space. Existing review sidecar
files remain a local-development implementation detail and are not part of the
production integration.

Render requests use a named compatible pipeline selector rather than
caller-supplied FFmpeg flags. `student_video.v1` versions the render pipeline and
its configuration schema; it is not a frozen quality preset. Exact codec,
resolution, frame rate, color, quality, audio, and splice settings are
worker-owned configuration and are deliberately outside the current integration
acceptance criteria. When accepting an immutable render job, the worker resolves
the selector to a concrete configuration and durably stores that snapshot with
the job. Restarting or replaying the same UUID therefore cannot change its
render, while later job UUIDs may use tuned settings without changing the
Gradivo request schema.

The current integration milestone is complete only when one real Drive video
runs through both operations: real analysis artifacts return to Gradivo for
human editing, and the accepted cut snapshot then produces a real final Drive
MP4 through a `render` job. Neither terminal result may be mocked. Render-quality
tuning and fallback-provider selection remain later work.

Final rendered MP4 files are uploaded directly to the Drive output folder
supplied by Gradivo and are not duplicated in S3. Gradivo retains the
job-to-Problem association, and a human performs the later Mux upload.
The worker marks each output with the render job UUID in private Drive
`appProperties` and reuses that file ID after retries, so a crash cannot create
a second final artifact merely because Drive allows duplicate filenames.
