import * as R from 'remeda'

import type { ReviewPayload, ReviewSentence } from '@/api'
import type { WordStatus } from '@/lib/cut-ranges'
import type { TimeRange } from '@/lib/timeline-model'

// How close to a cut span's end the playhead must be before preview-skip
// considers the jump complete.
export const PREVIEW_SKIP_END_EPSILON_SECONDS = 0.05

export const CUT_HISTORY_LIMIT = 100
// v3: drafts store free-form cut ranges, not word-index sets. Old v2 word-set
// drafts are migrated on load (see loadDraft) rather than discarded.
export const REVIEW_DRAFT_VERSION = 3

// The pipeline emits four status buckets. Two of them mean "the AI is unsure":
// `yellow` (kept, but maybe should be cut) and `restore` (cut, but maybe should be
// kept). Those — and only those — are what a human needs to look at. `green`
// (confident keep) and `red` (confident cut) are settled. Everything downstream
// collapses to a single boolean: does this sentence need review?
export function needsReview(sentence: ReviewSentence): boolean {
  return sentence.status === 'yellow' || sentence.status === 'restore'
}

// What the AI proposed for a sentence, independent of the human's current edits.
// We read it from the words' `ai_kept` so it stays consistent with how the cut set
// is seeded. A flagged sentence is either an AI keep the human might cut, or an AI
// cut the human might restore.
export function aiKeptSentence(sentence: ReviewSentence): boolean {
  const words = sentence.words ?? []
  if (words.length === 0) return true
  return words.some((word) => word.ai_kept)
}

export type ReviewFlag = {
  sentenceIdx: number
  firstWordIdx: number
  // Inclusive [first, last] word-index range, for applying keep/cut to the whole
  // sentence at once. Null only for the degenerate empty-sentence case.
  wordRange: [number, number] | null
  start: number
  end: number
  text: string
  aiKept: boolean
  reason: string
  rationale: string
  tags: string[]
}

/** The ordered list of sentences the professor is asked to judge. */
export function buildReviewQueue(payload: ReviewPayload): ReviewFlag[] {
  const flags = payload.sentences.filter(needsReview).map((sentence) => {
    const words = sentence.words ?? []
    const first = words[0]
    return {
      sentenceIdx: sentence.idx,
      firstWordIdx: first?.idx ?? -1,
      wordRange: sentenceRange(sentence),
      start: sentence.start,
      end: sentence.end,
      text: sentence.text,
      aiKept: aiKeptSentence(sentence),
      reason: sentence.reason,
      rationale: sentence.rationale,
      tags: sentence.tags ?? [],
    }
  })
  return R.sortBy(flags, (flag) => flag.start)
}

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

export type SentenceDecision = 'kept' | 'cut' | 'partial'

/** Where a sentence stands right now, from per-word statuses derived off the
 *  canonical cut ranges. Any partially-cut word makes the sentence 'partial'. */
export function sentenceDecisionFromStatus(
  sentence: ReviewSentence,
  wordStatus: Map<number, WordStatus>,
): SentenceDecision {
  const words = sentence.words ?? []
  if (words.length === 0) return 'kept'
  let cut = 0
  for (const word of words) {
    const status = wordStatus.get(word.idx) ?? 'kept'
    if (status === 'partial') return 'partial'
    if (status === 'cut') cut += 1
  }
  if (cut === 0) return 'kept'
  if (cut === words.length) return 'cut'
  return 'partial'
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

// A short, human label for the AI's reason token (e.g. "false_start" → "false start").
export function reasonLabel(reason: string): string {
  const token = reason
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
  if (!token || token === 'speech') return ''
  if (token === 'low_value') return 'low-value'
  return token.replace(/_/g, ' ')
}
