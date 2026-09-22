# Gradivo Worker HTTP Interface

This is the canonical machine-to-machine interface exposed by AI Video Editor
to Gradivo. It covers expensive media execution only; users and the Problem
Builder never call it directly.

## Job identity

Gradivo generates one UUID for every Video Processing Job. The same UUID is
used as the Gradivo primary key, worker job identity, callback identity, and
log correlation value. FIFO ordering is Gradivo metadata and is not encoded in
the UUID.

## Submit a job

```http
PUT /v1/jobs/{job_id}
```

The immutable request identifies one operation:

- `analysis`
- `render`

The closed `analysis` request schema is:

```json
{
  "operation": "analysis",
  "source": {
    "type": "google_drive",
    "file_id": "1AbC...",
    "head_revision_id": "0B...",
    "size_bytes": 184223001,
    "mime_type": "video/mp4",
    "checksum": {
      "algorithm": "md5",
      "value": "46c4..."
    }
  }
}
```

`file_id`, `head_revision_id`, `size_bytes`, and `mime_type` are required.
`checksum` is required when Drive exposes it and otherwise omitted as a whole.
The request contains no filename, callback URL, output destination, or Gradivo
domain ID. Unknown fields are rejected with `400 invalid_request`.

Responses:

- `201 Created`: the worker accepted a previously unseen job UUID and payload
- `200 OK`: the worker already knows the same UUID with the same semantic payload
- `409 job_payload_mismatch`: the UUID exists with a different payload; the existing job is unchanged

The UUID itself is the idempotency key. There is no additional
`Idempotency-Key` header and no worker-generated external job ID. Payload
comparison happens after validation, so JSON object key order and formatting do
not affect idempotency.

Before returning `201 Created`, the worker durably persists the job, reserves a
capacity slot, and creates this first snapshot:

```json
{
  "job_id": "018f...",
  "operation": "analysis",
  "revision": 1,
  "status": "processing",
  "progress": {
    "percent": 0,
    "stage": "accepted"
  }
}
```

An idempotent `200 OK`, `GET /v1/jobs/{job_id}`, and callbacks use the same
snapshot representation.

If the worker's `MAX_NUMBER_OF_JOBS` safety ceiling is occupied, a previously
unseen job is not persisted or accepted:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 30
```

```json
{
  "error": {
    "code": "worker_at_capacity",
    "retryable": true
  }
}
```

Gradivo retries the same UUID without advancing its FIFO queue. A UUID already
known to the worker receives the normal idempotent `200 OK` response regardless
of current capacity; `429` applies only to a new distinct job.

## Durable worker state

The initial Mac worker stores operational state in one SQLite database on
durable local storage. `VIDEO_PROCESSING_STATE_DB_PATH` supplies its deployment
path. Before `201 Created`, one transaction persists the validated request,
semantic payload hash, operation, resolved render configuration when relevant,
current snapshot, and initial callback-outbox entry.

The database also retains terminal results and callbacks until Gradivo
acknowledges them. It contains no Gradivo editorial state and is not a second
pending-work queue. Job scratch files use job-scoped directories; durable media
stays in Drive and R2. An internal job-store interface contains the SQLite
choice, allowing a future cloud executor to use another durable adapter without
changing this HTTP contract.

On startup, the worker does not silently rerun or checkpoint-resume a job left
in `processing`. In one transaction it increments the snapshot revision, marks
the attempt `failed` with retryable code `worker_interrupted`, places that
terminal callback in the outbox, and releases the capacity slot. The failure
retains the last recorded processing stage. Gradivo creates a new UUID and
`retry_of` relationship only after an explicit Retry command. A terminal
snapshot persisted before the restart remains terminal; the worker resumes only
its unacknowledged callback delivery.

## Runtime process boundary

The worker runtime has one long-lived FastAPI control process and at most
`MAX_NUMBER_OF_JOBS` media-execution subprocesses. The setting is a positive
integer, initially `1`, parsed from the environment and enforced by both durable
acceptance and the subprocess executor. Each job has its own process group and
timeout; finishing or timing out one job releases only that job's slot. Only the
control process reads and writes operational SQLite state. It owns HTTP
authentication, idempotent acceptance, capacity, snapshot revisions, and the
callback outbox.

After the acceptance transaction commits, the control process immediately
starts a subprocess with the already accepted immutable request. There is no
worker-owned pending queue, Redis broker, or Celery worker. The subprocess runs
either `analysis` or `render` and sends progress or terminal events back to the
control process. An abnormal subprocess exit becomes a terminal retryable
`processing_failed` snapshot while the HTTP API and callback dispatcher remain
alive.

Execution is bounded independently by `VIDEO_PROCESSING_ANALYSIS_TIMEOUT_SECONDS`
and `VIDEO_PROCESSING_RENDER_TIMEOUT_SECONDS` (both initially 14400 seconds / four
hours). The monotonic deadline starts when execution is launched, not while a
job waits in Gradivo. These generous defaults require tuning with representative
recordings; they are not performance targets or video-quality settings.

On expiry, the worker terminates the job's dedicated POSIX process group,
including FFmpeg descendants, escalating to a forced kill if necessary. It
persists `processing_timeout` and delivers the terminal callback through the
existing durable outbox. Retry remains an explicit Gradivo action with a new
UUID. If the media process cannot be stopped, capacity is retained rather than
risking overlapping executions. Job start/finish and callback-failure logs use
job UUIDs and safe diagnostic fields, never callback bodies or credentials.
Subprocess failures send bounded internal diagnostics to the control process's
rotating worker log: exception cause types, stack locations (without locals or
source text), and the FFmpeg stderr tail. Configured environment credentials,
Bearer tokens and URLs are redacted; SDK exception messages and response bodies
are omitted. These diagnostics never enter persisted snapshots or callbacks.

Graceful shutdown rejects new execution starts and signals every active job's
monitor. Each monitor first reads pending events for up to the termination grace
period (5 seconds by default), stopping as soon as it receives a terminal result.
It then stops and joins its process group, removes that job's scratch directory,
and persists one terminal event before shutdown returns. Jobs without a terminal
result after this wait fail with `worker_interrupted`; queued success or failure
results received during the wait are preserved. The callback dispatcher stops
after these transactions, leaving unacknowledged outbox entries available after restart.
The Docker service allows 60 seconds for this shutdown sequence.

Scratch storage is dedicated to one worker instance. After success, failure,
crash, timeout or graceful shutdown, the control process removes the completed
job's UUID directory only after stopping its process group. On startup, after
the previous instance has stopped, it removes UUID-named remnants before
accepting jobs. Other directory names and symlink targets are preserved. Cleanup
failure retains capacity and blocks further execution until recovery, preventing
continued accumulation of media when removal is unavailable. Operational logs,
SQLite state and remote artifacts are retained separately.

## Domain isolation

The job UUID is the only Gradivo identity visible to the worker. A request
contains an operation-specific media manifest, but never contains Problem,
Problem Source, Profile, Notion, Mux, or Raw Recording IDs. Gradivo alone maps
worker state and results back to those domain records.

## Drive source acquisition

A Drive-backed media manifest supplies only the stable Drive file ID and its
confirmed content fingerprint: head revision, checksum when available, byte
size, and MIME type. Gradivo never places a Google OAuth access token or refresh
token in a job request.

The worker owns its Google Drive credential configuration and downloads source
media directly through the Drive API. Before processing it compares the live
Drive metadata with the supplied fingerprint. A mismatch is a terminal,
machine-readable `source_changed` failure for that job attempt.

The initial deployment authenticates as the same automation Google user used by
Gradivo, using a separately issued offline OAuth refresh token. The worker reads
`GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, and
`GOOGLE_DRIVE_REFRESH_TOKEN` from deployment secrets. These values are distinct
from the Gradivo deployment's refresh token and never enter SQLite, logs, HTTP
payloads, or callbacks. The Drive authorization must cover reading confirmed
existing raw files plus creating, finding, and annotating final output files in
the supplied folder.

## Authentication

Every request uses HTTPS. Gradivo authenticates to the worker with a static
random Bearer token stored as `AI_VIDEO_EDITOR_API_TOKEN` in both deployments:

```http
Authorization: Bearer <AI_VIDEO_EDITOR_API_TOKEN>
```

The worker authenticates callbacks to Gradivo with a separate static random
Bearer token stored as `GRADIVO_VIDEO_CALLBACK_TOKEN` in both deployments.
Neither token has a refresh, expiry, JWT, or request-signing protocol in v1.
They are server-only environment variables and must never be exposed to the
Problem Builder browser or written to logs.

The Cloudflare-published Mac worker origin is also protected by a Cloudflare
Access application with a `Service Auth` policy restricted to Gradmin's
dedicated service token and no public bypass. Before sending the application
Bearer token, Gradmin adds:

```http
CF-Access-Client-Id: <VIDEO_PROCESSING_CF_ACCESS_CLIENT_ID>
CF-Access-Client-Secret: <VIDEO_PROCESSING_CF_ACCESS_CLIENT_SECRET>
```

Cloudflare Access rejects a request before it reaches the tunnel unless those
credentials match the policy. A request that passes Access must still pass the
worker's independent `AI_VIDEO_EDITOR_API_TOKEN` check. The Access credentials
belong only to the concrete Mac route and are not part of this provider-neutral
job API; local or future cloud executors may use another network-access layer
while retaining application Bearer authentication. Worker callbacks to Gradivo
do not send these Cloudflare Access headers.

## Status and progress

The public worker status vocabulary is exactly `processing`, `completed`, and
`failed`. There is no public `queued`, `accepted`, `retrying`, or `cancelled`
status because the worker owns no queue. `accepted` is only the first progress
stage inside `processing`. If execution cannot start after acceptance, the job
becomes `failed`; it is never silently returned to a worker queue.

The worker keeps a current status snapshot for every accepted job. Gradivo can
retrieve it for manual diagnostics or recovery:

```http
GET /v1/jobs/{job_id}
Authorization: Bearer <AI_VIDEO_EDITOR_API_TOKEN>
```

This endpoint is not polled during normal processing.

The worker pushes current snapshots to Gradivo:

```http
PUT /wt/internal/api/video-processing/jobs/{job_id}/status
Authorization: Bearer <GRADIVO_VIDEO_CALLBACK_TOKEN>
```

The callback base URL is not accepted in a job request. Each worker deployment
reads one fixed `GRADIVO_VIDEO_CALLBACK_BASE_URL` environment variable and
appends `/wt/internal/api/video-processing/jobs/{job_id}/status`. Gradivo likewise
reads the worker origin from `VIDEO_PROCESSING_HTTP_BASE_URL`. Neither
application hard-codes the peer hostname or puts it in a job payload; local,
development, staging, and production routing differs only by environment
configuration. The worker currently runs on a separate ARM64 MacBook Air;
Gradivo/callback remains local on the first computer pending a separate DEV rollout.
This worker never sends job callbacks to caller-supplied URLs.

The initial Mac worker HTTPS origin is published with Cloudflare Tunnel, which
forwards control-plane HTTP traffic to the local worker service through an
outbound `cloudflared` connection. The office router exposes no inbound worker
port. Drive video and R2 artifacts bypass this tunnel entirely. Ngrok is not
used for the initial deployment, and a later tunnel replacement changes only
`VIDEO_PROCESSING_HTTP_BASE_URL`.

The first Mac deployment is containerized immediately. Docker Compose runs one
worker container and one separately configured `cloudflared` container; neither
is installed as a native host process. The worker image contains this API entry
point and both operations and is the same execution package a future cloud
fallback must reuse. Persistent SQLite, scratch, and log locations are explicit
deployment-configured mounts outside the source checkout, and each container
receives only its own secrets and mounts. Compose restarts the containers after
the Docker engine is available. One dedicated non-admin macOS service account
owns the Docker engine supplied by OrbStack on the MacBook Air. After a cold Mac
restart, an operator signs in and starts OrbStack; Compose restores both
containers through `unless-stopped`.
This host-login policy is not part of the HTTP contract.

Image distribution and rollout automation are outside the first E2E milestone.
The operator manually ensures that the intended worker image is present and the
correct Compose containers are running on the Mac. This contract does not yet
choose local builds versus a registry, CI, immutable image references, or
automatic deployment; that decision is a later infrastructure task after real
`analysis` and `render` both work end to end.

The Mac stack injects secrets with two distinct mode-`0600` host env files in
the repository root. Both are excluded by `.gitignore` and `.dockerignore`, so
they remain discoverable without entering Git history or the Docker build
context. `.env.worker` is attached only to the worker container and contains its Drive OAuth, R2,
application-authentication, callback, and provider credentials.
`.env.cloudflared` is attached only to the tunnel container and contains its
tunnel token. They are never copied into an image, printed by deployment
scripts, or shared between services. Docker administrators can inspect a
container's environment, so the dedicated Docker owner is an explicitly trusted
operator boundary. A future cloud secret store may replace these host files
without changing this API or its semantic environment configuration.

A processing snapshot has this common shape:

```json
{
  "revision": 4,
  "status": "processing",
  "progress": {
    "percent": 35,
    "stage": "transcribing"
  }
}
```

`revision` is a monotonically increasing integer scoped to the job. Gradivo
stores only a newer revision and acknowledges duplicate or delayed older
snapshots with `200 OK`. Progress snapshots are best effort because newer ones
supersede them. A terminal `completed` or `failed` snapshot is persisted by the
worker and retried until Gradivo returns a successful response. The terminal
snapshot body is immutable across those retries.

`progress.percent` is a non-decreasing integer from 0 through 99 while the job
is `processing`; only `completed` reports 100. The contract provides no ETA.
`progress.stage` is an extensible lowercase `snake_case` code rather than a
closed enum. Gradivo maps known stages to user-facing labels and treats unknown
ones as generic in-progress work instead of rejecting the snapshot.

Initial analysis stages follow the current pipeline:

- `accepted`
- `downloading_source`
- `extracting_audio`
- `reducing_noise`
- `transcribing`
- `deciding_edits`
- `building_review_artifacts`
- `rendering_review_proxy`
- `uploading_artifacts`

## Terminal failures

A terminal failure uses the common snapshot shape and contains exactly one
`error` member and no `result` member:

```json
{
  "job_id": "018f...",
  "operation": "analysis",
  "revision": 7,
  "status": "failed",
  "progress": {
    "percent": 35,
    "stage": "downloading_source"
  },
  "error": {
    "code": "source_download_failed",
    "stage": "downloading_source",
    "message": "Could not download source media"
  }
}
```

A completed snapshot contains exactly one `result` member and no `error`
member. `error.code` is a stable, extensible lowercase `snake_case` machine
code. Gradivo maps known codes to localized Problem Builder messages and falls
back to a generic failure message for unknown codes instead of rejecting the
snapshot.

The worker sends no terminal `retryable` flag. Gradivo derives retryability from
its stable error-code registry and treats unknown codes as non-retryable.
Retrying is always a Gradivo decision and creates a new job UUID; the worker
never reopens a terminal attempt.

`error.stage` identifies where the failure occurred. `error.message` is a
short, sanitized, operator-safe description. It contains no stack trace,
stderr dump, third-party response body, credential, or secret. Detailed logs
remain worker-owned. The shared job UUID is the log-correlation identity, so
the contract introduces no separate diagnostic ID.

The initial terminal failure registry is deliberately small. Retryability is
fixed for each code rather than chosen independently by each failure site:

| Code | Retryable | Meaning |
| --- | --- | --- |
| `source_changed` | no | Live Drive content no longer matches the confirmed source fingerprint |
| `source_not_found` | no | The source Drive file does not exist |
| `source_access_denied` | no | The worker lacks permission to read the source |
| `invalid_media` | no | The source is not a valid supported video |
| `processed_audio_missing` | no | The durable FLAC required by render does not exist |
| `duplicate_output_artifacts` | no | Drive contains multiple outputs for the render job UUID |
| `source_download_failed` | yes | A transient source download failed |
| `processed_audio_download_failed` | yes | A transient processed-audio download failed |
| `worker_interrupted` | yes | The worker process or host stopped while the accepted job was processing |
| `processing_failed` | yes | Analysis or rendering failed unexpectedly; `stage` identifies the step |
| `processing_timeout` | yes | Execution exceeded the configured analysis/render time limit; processing is stopped before capacity is released |
| `artifact_upload_failed` | yes | Uploading an S3 analysis artifact failed transiently |
| `output_upload_failed` | yes | Uploading the final Drive output failed transiently |
| `internal_error` | yes | The worker encountered an unexpected internal failure |

Request failures that occur before a job is accepted are not terminal job
snapshots: `400 invalid_request`, `409 job_payload_mismatch`, and
`429 worker_at_capacity`. The first two require caller correction. Capacity is
a retryable dispatch condition for the same queued Gradivo job and UUID.

## Review Proxy artifact

The worker uploads the private Review Proxy to the environment's configured
private Cloudflare R2 Standard `VIDEO_PROCESSING_S3_BUCKET` through R2's
S3-compatible API, using this deterministic key:

```text
jobs/{job_id}/review-proxy.mp4
```

The proxy preserves the Raw Recording's complete, uncut source timeline and
uses the processed audio produced by analysis. Automatic and human cut ranges
are not rendered into it. Gradivo previews cuts by skipping source-time ranges,
which keeps transcript words, waveform points, and edits aligned and allows a
human to restore any proposed cut. Exact proxy encoding and quality remain
worker configuration outside the current integration acceptance criteria.

The completed result identifies it without returning a public or presigned
URL:

```json
{
  "review_proxy": {
    "type": "s3_object",
    "key": "jobs/018f.../review-proxy.mp4",
    "size_bytes": 48221031,
    "mime_type": "video/mp4",
    "etag": "..."
  }
}
```

Gradivo stores this stable reference and generates a short-lived signed GET URL
only when an authorized user opens the editor. Signed URLs are never persisted,
and the Problem Builder receives neither S3 credentials nor a worker URL. Both
services know the environment's private bucket through deployment
configuration, so bucket identity is not carried in a job request or result.

The first real end-to-end deployment uses a dedicated private DEV R2 bucket,
not a production bucket separated only by object-key prefixes. The worker is
configured with its own bucket-scoped `Object Read & Write` credentials.
Gradivo uses a separate bucket-scoped `Object Read only` credential pair to
sign authorized GET requests. Neither service receives an account-admin token,
and they do not share one read/write key. The bucket and both credential sets
are deployment configuration and never enter a job payload, result, callback,
SQLite record, browser response, or log.

## Processed audio artifact

Analysis also uploads the lossless processed audio used by later rendering:

```text
jobs/{job_id}/processed-audio.flac
```

Its `s3_object` reference contains the key, byte size, `audio/flac` MIME type,
and ETag. FLAC preserves the exact processed PCM samples while using less
storage than WAV. The artifact survives the interval between analysis and
human review. Rendering uses the original Drive video for the image stream and
this S3 object for the processed audio stream, rather than repeating audio
preprocessing or depending on worker-local analysis scratch files.

The worker stores a `source-fingerprint` SHA-256 value in the FLAC object's R2
metadata and verifies it after upload and before render download. It hashes the
canonical source manifest (sorted, compact JSON), excluding the optional
checksum: Drive file ID, immutable head revision, byte size, MIME type and source
type identify the recording. Download integrity checks still verify any supplied
checksum. This binds audio to the confirmed source without adding fields to the
HTTP request. Missing or mismatched provenance fails with `invalid_media` at
`downloading_processed_audio`; legacy FLAC objects without this metadata require
a new analysis. There is no unverified legacy fallback.

## Analysis result boundary

Analysis completion uses a dedicated transport DTO with
`schema: "analysis_result.v1"`. Filesystem paths remain worker-internal and
human review state belongs exclusively to Gradivo. The former local review
schema and migration UI are removed.

`analysis_result.v1` contains only portable processing output:

- source duration
- transcript words and source-time positions
- automatic cut ranges, machine reasons, and confidence
- data needed by the waveform editor
- the Review Proxy object reference
- the processed-audio object reference needed by render
- a machine-readable diagnostic summary

It contains no local filesystem or cache path, source filename, human review
state, or Gradivo domain ID. An adapter maps worker-internal Pydantic models to
this versioned boundary model, allowing internal pipeline models to evolve
without silently changing the Gradivo contract.

The complete structured DTO is included inline in the terminal snapshot:

```json
{
  "job_id": "018f...",
  "operation": "analysis",
  "revision": 10,
  "status": "completed",
  "progress": {
    "percent": 100,
    "stage": "completed"
  },
  "result": {
    "schema": "analysis_result.v1",
    "duration_ms": 912340,
    "transcript": [],
    "automatic_cut_ranges": [],
    "waveform": {
      "sample_interval_ms": 100,
      "peaks": [0.0]
    },
    "review_proxy": {
      "type": "s3_object",
      "key": "jobs/018f.../review-proxy.mp4",
      "size_bytes": 48221031,
      "mime_type": "video/mp4",
      "etag": "..."
    },
    "processed_audio": {
      "type": "s3_object",
      "key": "jobs/018f.../processed-audio.flac",
      "size_bytes": 48123122,
      "mime_type": "audio/flac",
      "etag": "..."
    },
    "diagnostics": {
      "pipeline_version": "analysis.v1",
      "warnings": []
    }
  }
}
```

The worker persists this immutable terminal JSON and retries the identical
callback until Gradivo acknowledges it. Gradivo validates and stores the editor
data atomically with its transition to `completed`. Transcript data, edits,
downsampled waveform data, the Review Proxy and processed-audio references, and
a small diagnostic summary remain inline; large binary media goes to S3.
Verbose logs and traces remain worker-owned operational data.

## Media time representation

Every time value in the HTTP contract is an integer number of milliseconds;
floating-point seconds never cross the service boundary. A range uses
half-open `[start_ms, end_ms)` semantics and must satisfy:

- `start_ms >= 0`
- `end_ms > start_ms`
- `end_ms <= duration_ms`

Cut-range collections are sorted and non-overlapping. Gradivo stores and sends
these canonical millisecond values back in render requests. Worker-internal
models may continue using floating-point seconds; boundary adapters perform the
conversion.

Gradivo continually overwrites one validated
`EditingTranscript.cut_ranges` PostgreSQL JSON field and creates no edit
revision model or EDL sidecar in v1. When a human requests rendering, Gradivo
copies the current ranges into the render job's immutable request payload. A
render operation may convert that snapshot into a full keep/cut EDL in
job-scoped scratch storage. That derived file is an ephemeral renderer input
and can be removed after the job; it never becomes shared production state.

## Render input

The closed render request schema is:

```json
{
  "operation": "render",
  "render_profile": "student_video.v1",
  "source": {
    "type": "google_drive",
    "file_id": "1AbC...",
    "head_revision_id": "0B...",
    "size_bytes": 184223001,
    "mime_type": "video/mp4",
    "checksum": {
      "algorithm": "md5",
      "value": "46c4..."
    }
  },
  "processed_audio": {
    "type": "s3_object",
    "key": "jobs/analysis-job-uuid/processed-audio.flac",
    "size_bytes": 48123122,
    "mime_type": "audio/flac",
    "etag": "..."
  },
  "output": {
    "type": "google_drive",
    "folder_id": "1FinalVideosFolder...",
    "display_name": "problem-123-final.mp4"
  },
  "edit": {
    "schema": "cut_ranges.v1",
    "duration_ms": 912340,
    "cut_ranges": [
      {"start_ms": 12540, "end_ms": 18920}
    ]
  }
}
```

`student_video.v1` selects the compatible worker render pipeline and
configuration schema; it is not a frozen quality preset and does not put
caller-supplied FFmpeg options into the cross-application contract. Exact codec,
resolution, frame rate, color, quality, audio, and splice settings are outside
the current integration acceptance criteria and may be tuned later. On job
acceptance, the worker resolves and durably stores the concrete configuration
with that immutable job. Restarting or replaying the same UUID therefore cannot
silently change its output, while later job UUIDs may use updated settings
without changing this request schema. The request contains no transcript,
separate analysis-job field, or Gradivo domain ID.

Before encoding, the worker probes the video and processed-audio durations and
compares each against `edit.duration_ms` and against each other. Durations must
be positive and finite, with at most 100 ms difference for sample/container
padding and millisecond rounding. Missing duration or a larger mismatch fails
with `invalid_media` before rendering or uploading an output.

## Render output

The worker uploads the completed MP4 directly to the supplied Google Drive
folder, which represents the Problem Source's `05 Final videos` workspace. It
returns a stable reference in the terminal result:

```json
{
  "final_video": {
    "type": "google_drive",
    "file_id": "1RenderedFile...",
    "head_revision_id": "0B...",
    "size_bytes": 954221031,
    "mime_type": "video/mp4",
    "checksum": {
      "algorithm": "md5",
      "value": "..."
    }
  }
}
```

The display name is not identity; Gradivo maps the artifact through the render
job. The worker does not duplicate this durable final MP4 in S3. A human later
downloads the Drive file and uploads it through Gradivo's Mux UI; this contract
does not implement Drive-to-Mux transfer.

Drive names are not unique and do not provide output idempotency. The render
job UUID is written into the output file as the private custom property
`appProperties.video_processing_job_id`. Before upload, the worker searches
inside the requested folder for that property. If no file exists, it creates
an empty metadata file with the property and then writes the MP4 to its Drive
file ID with a resumable update. Re-execution after a crash finds and reuses
the same file ID. More than one matching file produces terminal error
`duplicate_output_artifacts`; the worker never chooses an artifact by display
name or arbitrarily.

Fields not yet specified by the operation-specific schemas remain open until
their decisions are resolved.
