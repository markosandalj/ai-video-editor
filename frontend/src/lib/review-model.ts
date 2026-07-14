import type { ReviewPayload, ReviewSentence } from '@/api'
import type { TimeRange } from '@/lib/timeline-model'

// How close to a cut span's end the playhead must be before preview-skip
// considers the jump complete.
export const PREVIEW_SKIP_END_EPSILON_SECONDS = 0.05

export const CUT_HISTORY_LIMIT = 100
// v3: drafts store free-form cut ranges, not word-index sets. Old v2 word-set
// drafts are migrated on load (see loadDraft) rather than discarded.
export const REVIEW_DRAFT_VERSION = 3

/** Seed the canonical cut ranges from the payload the backend sends. */
export function buildInitialCutRanges(payload: ReviewPayload): TimeRange[] {
  return (payload.cut_ranges ?? []).map((range) => ({ start: range.start, end: range.end }))
}

export function sentenceRange(sentence: ReviewSentence): [number, number] | null {
  const words = sentence.words ?? []
  const first = words[0]
  const last = words.at(-1)
  return first && last ? [first.idx, last.idx] : null
}

export function activeCutSpan(
  cutSpans: Array<[number, number]>,
  currentTime: number,
): [number, number] | null {
  return (
    cutSpans.find(
      ([trigger, end]) =>
        currentTime >= trigger && currentTime < end - PREVIEW_SKIP_END_EPSILON_SECONDS,
    ) ?? null
  )
}

export function previewSkipTarget(end: number, duration: number): number {
  return duration > 0 ? Math.min(end, duration) : end
}
