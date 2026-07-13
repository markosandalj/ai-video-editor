# Free-Form Timeline Editor

Status: `in-progress`
Phase: 6

## Progress log

- **M1 (componentize)** — already done before this work started: `App.tsx` is
  ~340 lines and the editor is split across `components/`, `hooks/`, and
  `lib/review-model.ts`. No separate componentization pass was needed.
- **M2 backend (range core)** — done. `review.v3`, `CutRange`, `cut_ranges` in
  the payload (derived from current decisions) and save request (legacy
  `cut_words` still honored when `cut_ranges` is omitted), range-based
  `build_reviewed_edl` (keeps = complement of merged cuts). Key realization: the
  on-disk `-review.edl.json` was *already* time-range based, so loading a legacy
  sidecar yields ranges with no migration code. 15 tests pass; verified live
  against a real 25-min lecture (39 cut ranges round-trip).
- **M3 backend (peaks)** — done. `GET /api/videos/{id}/peaks` downsamples the
  cached `AudioEnvelope` (`<stem>.audio.json`) into normalized min/max buckets;
  no new ffmpeg path. Returns 2000+ peaks for a real video.
- **M3 frontend (read-only timeline)** — done. `lib/timeline-model.ts`
  (`deriveCutRanges` mirrors the backend EDL, `samplePeaks`, `clampWindow`,
  attention bands), `usePeaks` query hook, and `components/timeline/
  timeline-strip.tsx`: collapsible strip with a full-duration minimap over a
  zoomable/pannable detail track (layered canvases so the waveform isn't
  redrawn every playhead tick), theme-aware palette, cut blocks, confidence/
  attention heat, click-to-seek, ⌘/Ctrl-scroll zoom. Wired into `App.tsx` under
  the split in editor view, reading the shared cut set. Builds + lints clean;
  12 model-logic checks pass. **Not** visually screenshotted — no browser
  binary in this environment.
- **M4 (free-form editing + canonical range flip)** — implemented. Details:
  - *Canonical flip*: `useReviewSession` now holds `cutRanges: TimeRange[]` as
    the source of truth (seeded from `payload.cut_ranges`). Word/sentence status
    is a derived overlap projection (`wordStatus`, plus a compat `cutSet` of
    fully-cut words and `cutSpans` for playback). Transcript word toggles
    (`setCut`) became range add/remove snapped to the acoustic word bounds.
    Undo/redo, drafts (v3, with v2 word-set migration), and save all range-based.
  - *Range math* in `lib/cut-ranges.ts` (normalize/add/subtract/wordStatus/snap/
    hit-test) — 26 pure-logic checks pass.
  - *Gestures* in `timeline-strip.tsx`: plain drag paints a pending selection;
    click a cut selects it; click empty seeks; edge-drag trims any cut (merge on
    release via `normalize`); `X` cuts / `⏎` restores / `L` auditions / `Esc`
    clears the active selection; `i`/`o` set its edges at the playhead. Snapping
    to cut/word/sentence/playhead within 8px with low-zoom word-density culling,
    Alt disables. One completed gesture = one undo step; preview-skip suspends
    while editing.
  - *One active selection*: transcript keys gate off while a timeline selection
    exists and vice versa; the live geometry stays local to the strip and is
    applied to the session only on release.
  - *Verified*: frontend builds + lints clean; range/hit-test/snap logic
    unit-tested; live API round-trip of real cut ranges (POST → EDL → reload).

### M4 gaps (honest)

- **Not visually verified**: no browser binary in this environment, so the
  canvas gesture *feel* (drag, edge grab, snapping, cursors) is unproven — only
  the pure logic behind it is tested. Eyeball at localhost:8000 before trusting.
- **View sync is scroll-only**: selecting a range scrolls the transcript to the
  first overlapped word but does not yet highlight the overlapped span with the
  partial-word style (the plan's fuller sync). Deferred.
- **Snapping priority** is nearest-wins, not the strict cut-edge > word >
  sentence > playhead tiering in the spec — a reasonable approximation to tune.

### Staging deviation (and why)

The read-only timeline was built *before* the canonical-range flip, deriving
display ranges from the existing word `cutSet`. Free-form *editing* is what
truly requires cut ranges to become canonical (a free-form cut need not align to
words). Sequencing read-only-first keeps the working transcript editor
untouched while delivering the visible feature, and de-risks the big state
rewrite into its own focused change. The timeline already consumes a
`TimeRange[]`, so when ranges become canonical only the *producer* of that array
changes, not the timeline.
Depends on: 6.02 (FastAPI backend), 6.04 (review workflow), 6.05 (state sync & re-render)

> Supersedes 6.03, whose sentence-block timeline was replaced by the word-level
> transcript editor and no longer exists in the code.

## Objective

A timeline-based editing experience complementary to the transcript editor: a
collapsible timeline strip (minimap + zoomable detail track with waveform) on
the same screen as the transcript, where editors can make **free-form,
time-range cuts** — any part of the video, not just word-aligned blocks — with
both views editing one shared cut state.

## Locked decisions

- **Canonical edit state is a list of cut time-ranges** (`{start, end}` in
  source seconds), replacing the word-index set. Word/sentence keep status is
  *derived* by overlap. Save schema bumps to `review.v3`.
- **Cuts-only scope**: output is always the source video minus cut ranges, in
  original order. No reordering, multi-track, external media, or per-cut
  transition control.
- **Source-time axis**: the strip maps 1:1 to the raw video; cut regions render
  dimmed/hatched in place. Output duration shown as a readout.
- **Layout**: collapsible strip docked under the player, synced with the
  transcript (shared cut state, playhead, selection). Collapsed state = minimap.
- **Navigation**: full-width minimap (keep/cut + confidence heat, draggable
  viewport window) above a zoomable/pannable detail track.
- **Visual layers**: audio waveform (server-generated peaks) + confidence/
  attention heat from sentence `keep_confidence`/tags. No thumbnails in MVP.
- **Interactions at launch**: drag-select to cut, edge-drag any cut (including
  AI cuts), razor/split at playhead with i/o in-out marks, click a cut to
  select then delete/restore it.
- **Snapping**: edges snap to word boundaries, sentence boundaries, playhead,
  and other cut edges within a pixel threshold; Alt/Option disables.
- **Partial words**: a word partially covered by a cut renders in a distinct
  "partially cut" style in the transcript; clicking it toggles the whole word
  (range expands/retracts to word boundaries).
- **Structure**: full componentization pass on `frontend/src/App.tsx` (~2000
  lines) as part of this feature. Lands as **one feature branch** with the
  milestone checkpoints below.
- **Migration**: old `cut_words` saves and old word-set localStorage drafts are
  converted to ranges on load — nobody loses in-flight work.

## M4 interaction spec (grilled 2026-07-12)

### Selection model — one selection for the whole app

There is exactly **one active selection** at any time, app-wide:

- a **word selection** (existing transcript anchor/focus selection), or
- a **time selection** (a `{start, end}` range on the timeline — either a
  pending drag-painted range or an existing cut clicked to select), or
- nothing.

Starting either kind clears the other. `X`/`Backspace`/`Delete` cut the active
selection, `Enter` keeps/restores it, `L` auditions it, `Escape` clears it —
identical verbs in both views, acting on whichever selection exists. No panel
focus tracking, no duplicate keybindings.

### Pointer gestures on the detail track

- **Plain click** on a keep region: seek (unchanged). **Plain click on a cut
  block: selects that cut** as a time selection (per the original locked
  decision); it does not seek.
- **Plain drag** on the track paints a **pending time selection** with edge
  handles. Nothing is cut yet: `X` (or a floating "Cut" chip on the selection)
  commits it; `Escape` clears; `L` auditions the range first; handles are
  draggable before committing. Mirrors the transcript's select→X flow.
- **Edge-drag** on any existing cut (including AI cuts) trims/extends it
  directly — this is live editing, not a pending selection. ~6px hit zone per
  edge with `col-resize` cursor.
- **Pan** stays on scroll; **zoom** stays on ⌘/Ctrl+scroll. Drag no longer
  pans (drag = select). Minimap click/drag continues to navigate the window;
  minimap in collapsed mode continues to seek.

### Keyboard: i/o feed the same selection

`i` sets the pending time selection's start to the playhead; `o` sets its end
(creating the selection if none exists, adjusting it if one does). Then the
normal verbs apply (`X` cut, `L` audition, `Escape` clear). There is **no
separate razor tool or marker entity**: "split a cut" falls out of the model —
select a range inside a keep and cut it, or edge-drag; `i`+`o`+`X` is the
keyboard razor. `i`/`o` are currently unbound; no conflicts.

### Collision + normalization semantics

The range list holds one invariant: **sorted, non-overlapping, merged, clamped
to `[0, duration]`, minimum width 50ms** — enforced by a single `normalize()`
on every commit. During an edge-drag, edges move freely past neighbors with a
live preview of the union; **on release** the list normalizes (overlaps merge,
sub-50ms cuts delete). Nothing ever stops-at-neighbor; joining two AI cuts is
one drag.

### Snapping

- Threshold **8px** (screen px, not seconds — so precision scales with zoom).
- Target priority: **other cut edges > word boundaries > sentence starts >
  playhead**. Word boundaries use the acoustic `cut_in`/`cut_out` splits.
- **Density culling**: when word boundaries at the current zoom are closer
  together than ~2× the threshold, word snapping is culled (sentence/cut-edge/
  playhead targets remain). Low zoom snaps coarse, high zoom snaps fine.
- **Alt/Option** held disables all snapping.

### Undo, playback, and drafts during editing

- A completed gesture (drag-select commit, edge-drag release, keyboard cut) is
  **exactly one undo step**. No history entries during a drag.
- While a drag is in progress **or a time selection is pending**, the
  preview-edit skip loop stands down (same mechanism as auditioning), so the
  playhead can't teleport out of the region being edited. It resumes on
  commit/clear.
- Draft persistence keys off the normalized range list (draft format version
  bumps; old word-set drafts convert via word timestamps on load).

### View sync (timeline → transcript)

Any time selection (pending or selected cut) makes the transcript **scroll to
and highlight the overlapped words**, with the partial-word style on words only
partially covered — timeline shows *where*, transcript shows *what speech*.
One-way; transcript word selection does not paint onto the timeline.

### Prerequisite inside M4: the canonical flip

Free-form edges cannot be represented as a word set, so M4 starts by making
`cutRanges: TimeRange[]` the session's canonical state (undo/redo stacks,
drafts, save request all range-based). Word/sentence kept/partial status becomes
a derived overlap projection; the transcript's word toggles become range
mutations snapped to word boundaries (`cut_in`/`cut_out`). The timeline already
consumes `TimeRange[]`, so only the producer changes.

## Backend work

- `ai_video_editor/review/models.py`: `SCHEMA_VERSION = "review.v3"`. New
  `CutRange {start, end}`. `ReviewSaveRequest` becomes `{cut_ranges: list[CutRange]}`
  (accept legacy `cut_words` and convert server-side). `ReviewPayload` includes
  the saved `cut_ranges` so the client restores exact state.
- `ai_video_editor/review/export.py`: `build_reviewed_edl` takes merged cut
  ranges and emits keeps as their complement over `[0, video_duration]` —
  simpler than today's word-run reconstruction. Loader converts `review.v2`
  sidecars (word indices → ranges via word timestamps).
- New `GET /api/videos/{video_id}/peaks` in `ai_video_editor/web/app.py`:
  ffmpeg extracts mono audio, downsamples to ~4–8k min/max pairs, caches JSON
  next to the video keyed on source mtime/size.
- Regenerate `frontend/src/api/schema.d.ts` from the updated OpenAPI schema.
- Range invariants (sorted, non-overlapping, merged, clamped) live in one
  module with unit tests in `tests/`; migration round-trip tested (v2 save →
  ranges → identical EDL).

## Frontend work

- **Componentization (behavior-identical checkpoint)**: split `App.tsx` into
  `state/` (edit store), `components/player/`, `components/transcript/`,
  `components/inspector/`, `components/timeline/`, plus existing `ui/`.
- **Edit store** (reducer or Zustand): `cutRanges` normalized on every
  mutation; ops `addCut`, `removeCut`, `trimEdge`, `splitAt`, `toggleWord`,
  `toggleSentence`; derived `wordStatus` (kept / cut / partial by overlap),
  `cutSpans` for `PlaybackSync`, `outputDuration`; undo/redo as range-list
  snapshots; version-keyed drafts with word-set → range migration.
- **Timeline components**: `TimelineStrip` (collapsible), `Minimap` (canvas),
  `DetailTrack` (canvas waveform + DOM/SVG cut blocks, word ticks at high
  zoom, sentence boundaries, playhead; ctrl+wheel zoom, drag pan), interaction
  layer (hit-testing, drag gestures, snapping engine, keyboard razor/marks).
- **Sync**: timeline click seeks the raw video and scrolls the transcript to
  the word under the playhead; word click centers the detail track.

## Library evaluation

The timeline is architecturally an **audio-waveform annotation surface**
(source-time axis, cut regions dragged/resized, overview + zoomed detail view),
*not* a multi-clip composition NLE. That framing rules out the maintained React
"video editor" packages (Twick, React Video Editor, xzdarcy/react-timeline-editor):
they impose their own clip/track data model and export pipeline, which fights
our cuts-only, range-canonical, ffmpeg-render design. Do **not** adopt one.

Two mature libraries fit the actual shape:

- **peaks.js (BBC R&D)** — closest match. Built as overview view + zoomable
  detail view + draggable/resizable **segments** on canvas (Konva). Attaches to
  an *external* media element (our existing `@videojs/react` player stays the
  player) and loads **precomputed peaks JSON** — exactly the `GET /peaks`
  endpoint in M2 (BBC's `audiowaveform` is the standard generator). Covers most
  of M3 and a chunk of M4 out of the box.
- **wavesurfer.js v7** — more popular, modern TS; Regions + Minimap + zoom
  plugins, precomputed peaks. But renders into a Shadow DOM (styling friction
  for confidence-heat and partial-word overlays via `::part()`), its minimap is
  a scrollbar rather than a color-codable overview, and it leans toward owning
  playback. Second choice.

What **no** library provides (we build regardless): boundary snapping with Alt
override, razor + in/out-point keyboard flow, transcript↔timeline sync,
confidence heat, partial-word styling, and undo/redo.

**Plan of record:** prototype M3 with peaks.js. **Hard rule for any library:**
`cutRanges` stays the source of truth; the library's segments are a *rendered
view* — set them from our state, translate drag events back into store
mutations. Never let a library own the cut state.

**We may end up building our own.** If peaks.js can't express the confidence
heat, partial-word styling, or snapping the way we want — or the "view-only"
boundary proves leaky in practice — we fall back to a fully custom detail track
with **react-konva** (canvas) + **d3-scale** (time↔pixel) + **react-moveable**
or **interact.js** (drag/resize with snap guides) + **@tanstack/react-virtual**
(transcript). Because our state is canonical and any library is only a view,
this fallback costs little: it is an explicitly accepted possible outcome, not a
failure. Timebox the peaks.js spike in M3 and decide build-vs-adopt from it.

## Milestones (single branch, each independently verifiable)

1. **M1 — Componentize**: App.tsx split, zero behavior change (manual
   regression of toggle/undo/audition/save/render + build passes).
2. **M2 — Range core**: backend v3 + edit store on ranges; transcript behaves
   exactly as before; save → EDL → render round-trips; migrations verified.
3. **M3 — Read-only timeline**: strip with minimap, waveform via peaks
   endpoint, cut blocks, confidence heat, click-to-seek, collapse/expand.
4. **M4 — Editing**: drag-select cut, edge-drag, razor + i/o marks,
   click-select + restore, snapping with Alt override, partial-word transcript
   styling and whole-word toggle.
5. **M5 — Polish**: hotkey drawer updated, output-duration readout, perf pass
   (virtualize word ticks; target 90-min lectures smooth), draft migration
   confirmed against a real in-flight draft.

## Risks / watch items

- Many tiny free-form cuts → dense crossfades in `render/assemble.py` may
  produce audible artifacts; consider warning on cuts shorter than the
  crossfade duration.
- Snapping density in fast speech: word boundaries every ~100ms can make Alt
  the *de facto* default at low zoom — tune threshold in pixels, not seconds.
- Peaks generation for long lectures must not block the request thread; reuse
  the render path's subprocess handling and cache aggressively.
- Undo/redo semantics across views must feel like one history (a timeline
  trim then a word toggle undo in reverse order).

## Acceptance criteria

- [ ] Cut state is range-based end-to-end: timeline and transcript edit the
      same ranges; save produces `review.v3`; legacy saves and drafts load
      correctly and render an identical EDL.
- [ ] Timeline strip shows minimap + zoomable detail track with waveform,
      confidence heat, cut regions, playhead; collapsible; click seeks video.
- [ ] Free-form editing works: drag-select cut, edge-drag trim of any cut,
      razor/in-out keys, click-restore — all with boundary snapping and Alt
      free-drag.
- [ ] Partially cut words are visually distinct in the transcript and toggle
      as whole words.
- [ ] Undo/redo and localStorage drafts cover edits from both views.
- [ ] `App.tsx` reduced to composition; editor logic lives in dedicated
      modules with unit tests for range math and EDL building.
