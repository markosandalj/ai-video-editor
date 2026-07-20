import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as R from 'remeda'

import { useRenderReview, useSaveReview } from '@/api'
import type { ReviewPayload, ReviewSentence, ReviewWord } from '@/api'
import {
  addCut,
  buildWordStatus,
  normalizeRanges,
  removeCut,
  sameRanges,
  wordStatus as computeWordStatus,
} from '@/lib/cut-ranges'
import { CUT_HISTORY_LIMIT, REVIEW_DRAFT_VERSION, buildInitialCutRanges } from '@/lib/review-model'
import type { TimeRange } from '@/lib/timeline-model'

function draftStorageKey(videoId: string) {
  return `ai-video-editor:review-draft:${videoId}:v${REVIEW_DRAFT_VERSION}`
}

/** Load the current working draft as source-time cut ranges. */
function loadDraft(videoId: string, duration: number): TimeRange[] | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(draftStorageKey(videoId))
    if (raw) {
      const parsed = JSON.parse(raw) as { cutRanges?: unknown }
      if (Array.isArray(parsed.cutRanges)) {
        return normalizeRanges(parsed.cutRanges as TimeRange[], duration, 0)
      }
    }
    return null
  } catch {
    return null
  }
}

function saveDraft(videoId: string, ranges: TimeRange[]) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(
    draftStorageKey(videoId),
    JSON.stringify({ version: REVIEW_DRAFT_VERSION, cutRanges: ranges }),
  )
}

function clearDraft(videoId: string) {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(draftStorageKey(videoId))
}

export type FinishState = 'idle' | 'saving' | 'rendering' | 'done' | 'error'

export type ReviewSession = ReturnType<typeof useReviewSession>

/**
 * Owns the reviewer's working state for one video. The canonical state is a list
 * of free-form cut ranges (source seconds); word/sentence keep status is derived
 * from it. Both the transcript (word-index edits) and the timeline (range edits)
 * drive this one list, which is what the backend saves and renders.
 */
export function useReviewSession(payload: ReviewPayload | null, videoId: string) {
  const saveMutation = useSaveReview(videoId)
  const renderMutation = useRenderReview(videoId)

  const duration = payload?.video.duration ?? 0

  const [cutRanges, setCutRanges] = useState<TimeRange[]>([])
  const [savedRanges, setSavedRanges] = useState<TimeRange[]>([])
  const [undoStack, setUndoStack] = useState<TimeRange[][]>([])
  const [redoStack, setRedoStack] = useState<TimeRange[][]>([])
  const [draftRestored, setDraftRestored] = useState(false)
  const [finishState, setFinishState] = useState<FinishState>('idle')
  const rangesRef = useRef(cutRanges)

  useEffect(() => {
    rangesRef.current = cutRanges
  }, [cutRanges])

  // Flat word list and lookup maps, derived once per payload.
  const words = useMemo<ReviewWord[]>(
    () => (payload ? R.flatMap(payload.sentences, (s) => s.words ?? []) : []),
    [payload],
  )
  const wordByIdx = useMemo(() => {
    const map = new Map<number, ReviewWord>()
    for (const word of words) map.set(word.idx, word)
    return map
  }, [words])
  const wordIndexByIdx = useMemo(() => {
    const map = new Map<number, number>()
    words.forEach((word, index) => map.set(word.idx, index))
    return map
  }, [words])
  const sentenceByWord = useMemo(() => {
    const map = new Map<number, ReviewSentence>()
    if (payload) {
      for (const sentence of payload.sentences) {
        for (const word of sentence.words ?? []) map.set(word.idx, sentence)
      }
    }
    return map
  }, [payload])

  // Everything the transcript reads is a projection of the canonical ranges.
  const wordStatus = useMemo(() => buildWordStatus(words, cutRanges), [words, cutRanges])
  const cutSet = useMemo(() => {
    const set = new Set<number>()
    for (const [idx, status] of wordStatus) if (status === 'cut') set.add(idx)
    return set
  }, [wordStatus])
  const cutSpans = useMemo<Array<[number, number]>>(
    () => cutRanges.map((range) => [range.start, range.end]),
    [cutRanges],
  )

  // Seed from the backend's canonical ranges (or a restored draft) per payload.
  useEffect(() => {
    if (!payload) return
    const initial = buildInitialCutRanges(payload)
    const draft = loadDraft(payload.video.id, payload.video.duration)
    const restored = draft !== null && !sameRanges(draft, initial)
    setCutRanges(draft ?? initial)
    setSavedRanges(initial)
    setUndoStack([])
    setRedoStack([])
    setDraftRestored(restored)
    setFinishState('idle')
  }, [payload])

  const isDirty = useMemo(
    () => payload !== null && !sameRanges(cutRanges, savedRanges),
    [payload, cutRanges, savedRanges],
  )

  // Persist the working draft locally (or clear it once it matches what's saved).
  useEffect(() => {
    if (!payload) return
    if (isDirty) saveDraft(payload.video.id, cutRanges)
    else {
      clearDraft(payload.video.id)
      setDraftRestored(false)
    }
  }, [payload, cutRanges, isDirty])

  // The single mutation entry point: normalize, and if the result differs from
  // the current committed state, push one undo step. One gesture → one commit.
  const commitRanges = useCallback(
    (next: TimeRange[]) => {
      setCutRanges((current) => {
        const normalized = normalizeRanges(next, duration)
        if (sameRanges(current, normalized)) return current
        setUndoStack((history) => [...history.slice(-(CUT_HISTORY_LIMIT - 1)), current])
        setRedoStack([])
        return normalized
      })
    },
    [duration],
  )

  // The source-time span a word range occupies, using the shared acoustic split
  // points so cutting a word doesn't clip its neighbors.
  const spanForWords = useCallback(
    (lo: number, hi: number): TimeRange | null => {
      const first = wordByIdx.get(lo)
      const last = wordByIdx.get(hi)
      if (!first || !last) return null
      return { start: first.cut_in ?? first.start, end: last.cut_out ?? last.end }
    },
    [wordByIdx],
  )

  const setCut = useCallback(
    (lo: number, hi: number, cut: boolean) => {
      const span = spanForWords(Math.min(lo, hi), Math.max(lo, hi))
      if (!span) return
      commitRanges(
        cut
          ? addCut(rangesRef.current, span, duration)
          : removeCut(rangesRef.current, span, duration),
      )
    },
    [spanForWords, commitRanges, duration],
  )

  // Clicking a word toggles the WHOLE word: a partially-cut word restores fully.
  const toggleWord = useCallback(
    (idx: number) => {
      const word = wordByIdx.get(idx)
      if (!word) return
      const kept = computeWordStatus(word, rangesRef.current) === 'kept'
      setCut(idx, idx, kept)
    },
    [wordByIdx, setCut],
  )

  // Timeline range edits.
  const addCutRange = useCallback(
    (range: TimeRange) => commitRanges(addCut(rangesRef.current, range, duration)),
    [commitRanges, duration],
  )
  const removeCutRange = useCallback(
    (range: TimeRange) => commitRanges(removeCut(rangesRef.current, range, duration)),
    [commitRanges, duration],
  )

  const undo = useCallback(() => {
    setUndoStack((history) => {
      const previous = history.at(-1)
      if (!previous) return history
      setRedoStack((stack) => [rangesRef.current, ...stack.slice(0, CUT_HISTORY_LIMIT - 1)])
      setCutRanges(previous)
      return history.slice(0, -1)
    })
  }, [])

  const redo = useCallback(() => {
    setRedoStack((history) => {
      const next = history[0]
      if (!next) return history
      setUndoStack((stack) => [...stack.slice(-(CUT_HISTORY_LIMIT - 1)), rangesRef.current])
      setCutRanges(next)
      return history.slice(1)
    })
  }, [])

  const save = useCallback(async () => {
    if (!payload) return null
    const snapshot = rangesRef.current
    const saved = await saveMutation.mutateAsync(snapshot)
    setSavedRanges(snapshot)
    setDraftRestored(false)
    if (sameRanges(rangesRef.current, snapshot)) clearDraft(payload.video.id)
    return saved
  }, [payload, saveMutation])

  // One-click completion: persist the decisions, then render the final MP4.
  const approveAndFinish = useCallback(async () => {
    if (!payload) return
    try {
      setFinishState('saving')
      await save()
      setFinishState('rendering')
      await renderMutation.mutateAsync()
      setFinishState('done')
    } catch {
      setFinishState('error')
    }
  }, [payload, save, renderMutation])

  return {
    words,
    wordByIdx,
    wordIndexByIdx,
    sentenceByWord,
    cutRanges,
    wordStatus,
    cutSet,
    cutSpans,
    isDirty,
    draftRestored,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    finishState,
    isSaving: saveMutation.isPending,
    setCut,
    toggleWord,
    addCutRange,
    removeCutRange,
    commitRanges,
    undo,
    redo,
    save,
    approveAndFinish,
  }
}
