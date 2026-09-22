# Gradivo integration completion

Scope: finish the editor user flow and make worker execution resilient to stuck
processing. Keep the existing local setup. Deployment, cloud fallback selection,
render-quality settings, and Mux provenance are outside this work.

This document records the focused grill-with-docs decisions. Recorded decisions
are requirements, not claims that implementation is complete. Gradivo owns the
editor UI; this repository owns the headless worker.

## Accepted: finish editing (2026-09-21)

After **Approve & finish**, Gradivo saves the current edits and submits the render
request. Only after saving succeeds and Gradivo accepts the render into its queue
does the editor navigate back to **Raw Recordings**, bringing the corresponding
recording into view. Worker execution does not need to have started yet.

The existing recording row shows progress and the finished video's link. A save
or submission failure keeps the user in the editor with edits retained, a clear
error, and a way to retry.

## Accepted: bounded worker execution (2026-09-21)

Worker execution has a configurable maximum duration, set separately for analysis
and render. This bounds execution after it starts, not time spent waiting in
Gradivo's queue. Initial limits should be generous enough for normal processing;
exact defaults remain an implementation choice to validate against real jobs.

When the limit is exceeded, stop the job's processing, report a clear timeout
failure to Gradivo, and release worker capacity only after processing has stopped
so the queue can continue. Retry remains an explicit user action, not an automatic
rerun. A genuinely healthy but exceptionally slow job may also hit this limit;
this trade-off was accepted.

## Accepted: recover unsaved edits (2026-09-21)

If the connection drops or authentication expires, preserve edits in the same
browser and distinguish locally retained edits from edits saved in Gradivo.
After connection or login is restored, the user explicitly retries saving.
Rendering is blocked until saving succeeds. Warn before leaving the editor while
edits have not been saved to Gradivo. Local browser retention is not a substitute
for a successful server save.

## Implementation and verification

The focused decision session is complete. Editor navigation/recovery and worker
deadlines are implemented locally in the two repositories, with automated tests
for unsaved drafts, save-before-render, single-flight submission, media URL
recovery, subprocess-tree termination, durable timeout callbacks and replay.
Worker deadlines initially default to four hours for each operation and are
independently configurable through the documented environment variables.

A new cross-app browser acceptance run and Gradivo backend tests remain pending:
the local Gradivo Django service was not running during verification. No worker
image was rebuilt or deployed, and no render-quality settings were changed.

## Worker-only repository (2026-09-22)

The local review UI/API and combined processing CLI are removed. Corpus
evaluation runners, iteration records and implementation phases remain as
development tools. Analysis algorithms and immutable-snapshot rendering remain
behind the worker API. See [cleanup inventory](headless-cleanup.md)
for scope and verification. Editor behavior described above belongs to Gradivo.

The active worker is the separate ARM64 MacBook Air with OrbStack, image
`ai-video-worker:f779947`, pinned `cloudflared:2026.7.3` and `unless-stopped`.
Gradivo/callback is still local on the first computer. This cleanup performs no
deployment, real-provider acceptance or hosted DEV rollout. Final upload from
Drive to Gradivo/Mux remains manual without additional render/Mux bookkeeping.
