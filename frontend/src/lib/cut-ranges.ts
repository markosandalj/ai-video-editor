import type { TimeRange } from '@/lib/timeline-model'

// Free-form cuts are stored as source-time ranges. This module is the single
// home for the range invariant and the derivations the transcript reads off it.

export const MIN_CUT_SECONDS = 0.05
const EPS = 1e-4

// A few ms of grace at each edge of the audible word: a cut has to intrude past
// this before it counts as touching the word, so a cut that just grazes the
// acoustic boundary (or lands a hair inside it) leaves the word un-crossed.
const AUDIBLE_EDGE_BUFFER_SECONDS = 0.05

/**
 * The one invariant the canonical cut list must always satisfy: clamped to
 * `[0, duration]`, sorted, overlapping/adjacent ranges merged, and (for user
 * edits) anything narrower than `minWidth` dropped. Pass `minWidth: 0` when
 * loading server/AI state so a legitimately tiny AI cut is not silently removed.
 */
export function normalizeRanges(
  ranges: TimeRange[],
  duration: number,
  minWidth = MIN_CUT_SECONDS,
): TimeRange[] {
  const clamped = ranges
    .map((r) => ({
      start: Math.max(0, Math.min(r.start, duration)),
      end: Math.max(0, Math.min(r.end, duration)),
    }))
    .filter((r) => r.end - r.start > EPS)
    .sort((a, b) => a.start - b.start)

  const merged: TimeRange[] = []
  for (const r of clamped) {
    const last = merged.at(-1)
    if (last && r.start <= last.end + EPS) last.end = Math.max(last.end, r.end)
    else merged.push({ ...r })
  }
  return merged.filter((r) => r.end - r.start >= minWidth - EPS)
}

/** Add one cut range and re-normalize (merges into any it overlaps). */
export function addCut(ranges: TimeRange[], range: TimeRange, duration: number): TimeRange[] {
  return normalizeRanges([...ranges, range], duration)
}

/** Punch `hole` out of every existing range — the restore/keep operation. */
export function subtractRange(ranges: TimeRange[], hole: TimeRange): TimeRange[] {
  const out: TimeRange[] = []
  for (const r of ranges) {
    if (hole.end <= r.start + EPS || hole.start >= r.end - EPS) {
      out.push(r)
      continue
    }
    if (hole.start > r.start + EPS) out.push({ start: r.start, end: hole.start })
    if (hole.end < r.end - EPS) out.push({ start: hole.end, end: r.end })
  }
  return out
}

/** Remove (restore) a span from the cut list. */
export function removeCut(ranges: TimeRange[], hole: TimeRange, duration: number): TimeRange[] {
  return normalizeRanges(subtractRange(ranges, hole), duration, 0)
}

export type WordStatus = 'kept' | 'cut' | 'partial'

type Span = {
  start: number
  end: number
  cut_in?: number | null
  cut_out?: number | null
}

/**
 * The interval that actually damages the word when cut. Transcript timestamps
 * are not reliable edit points — ElevenLabs word ends often run past the
 * audible word into the following silence — so we clip the transcript interval
 * to the acoustic split points (`cut_in`/`cut_out`, the quiet frames around the
 * audible word). A cut that lives entirely in that trailing silence then has
 * zero overlap and the word stays kept.
 */
function audibleSpan(word: Span): { start: number; end: number } {
  const start = word.cut_in != null ? Math.max(word.start, word.cut_in) : word.start
  const end = word.cut_out != null ? Math.min(word.end, word.cut_out) : word.end
  const audible = end > start ? { start, end } : { start: word.start, end: word.end }
  // Pull each edge in by the grace buffer, but never past the middle.
  const buffered = {
    start: audible.start + AUDIBLE_EDGE_BUFFER_SECONDS,
    end: audible.end - AUDIBLE_EDGE_BUFFER_SECONDS,
  }
  return buffered.end > buffered.start ? buffered : audible
}

/**
 * A word's status by how much of its audible extent the cuts cover: fully cut,
 * fully kept, or partially cut (a free-form edge landed mid-word). A 2% slack
 * absorbs float noise at snapped boundaries.
 */
export function wordStatus(word: Span, ranges: TimeRange[]): WordStatus {
  const audible = audibleSpan(word)
  const span = Math.max(EPS, audible.end - audible.start)
  let covered = 0
  for (const r of ranges) {
    const lo = Math.max(audible.start, r.start)
    const hi = Math.min(audible.end, r.end)
    if (hi > lo) covered += hi - lo
  }
  const fraction = covered / span
  if (fraction >= 0.98) return 'cut'
  if (fraction <= 0.02) return 'kept'
  return 'partial'
}

export function buildWordStatus(
  words: Array<{ idx: number } & Span>,
  ranges: TimeRange[],
): Map<number, WordStatus> {
  const map = new Map<number, WordStatus>()
  for (const word of words) map.set(word.idx, wordStatus(word, ranges))
  return map
}

export function sameRanges(a: TimeRange[], b: TimeRange[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (Math.abs(a[i].start - b[i].start) > EPS || Math.abs(a[i].end - b[i].end) > EPS) return false
  }
  return true
}

/** Index of the cut range containing `time`, or -1. */
export function findCutAt(ranges: TimeRange[], time: number): number {
  return ranges.findIndex((r) => time >= r.start && time <= r.end)
}

export type CutEdge = { index: number; edge: 'start' | 'end' }

/**
 * The nearest cut edge within `thresholdPx` screen pixels of `time`, or null.
 * Edge hits take priority over interior hits so a cut can always be trimmed.
 */
export function findCutEdge(
  ranges: TimeRange[],
  time: number,
  pxPerSecond: number,
  thresholdPx = 6,
): CutEdge | null {
  let best: CutEdge | null = null
  let bestPx = thresholdPx
  ranges.forEach((range, index) => {
    for (const edge of ['start', 'end'] as const) {
      const distPx = Math.abs(range[edge] - time) * pxPerSecond
      if (distPx < bestPx) {
        bestPx = distPx
        best = { index, edge }
      }
    }
  })
  return best
}

/**
 * Snap `time` to the nearest target within `thresholdPx` screen pixels. Targets
 * are pre-filtered/ordered by the caller (cut edges, word/sentence boundaries,
 * playhead); nearest wins. Returns `time` unchanged when nothing is close.
 */
export function snapTime(
  time: number,
  targets: number[],
  pxPerSecond: number,
  thresholdPx = 8,
): number {
  let best = time
  let bestPx = thresholdPx
  for (const target of targets) {
    const distPx = Math.abs(target - time) * pxPerSecond
    if (distPx < bestPx) {
      bestPx = distPx
      best = target
    }
  }
  return best
}
