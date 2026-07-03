import '@videojs/react/video/skin.css'

import { type MouseEvent, type PointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useHotkeys, type UseHotkeyDefinition } from '@tanstack/react-hotkeys'
import { Agentation } from 'agentation'
import { Video, VideoSkin } from '@videojs/react/video'
import {
  Check,
  CircleHelp,
  Eye,
  Flag,
  ListFilter,
  LocateFixed,
  Play,
  Redo2,
  Repeat2,
  Save,
  Scissors,
  Search,
  SkipForward,
  Undo2,
  X,
} from 'lucide-react'
import * as R from 'remeda'
import { useBoolean, useEventCallback } from 'usehooks-ts'

import { DiffView } from '@/DiffView'
import { ResizableSplit } from '@/components/resizable-split'
import { ViewSwitch, type AppView } from '@/components/view-switch'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Toggle } from '@/components/ui/toggle'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useRenderReview, useReview, useSaveReview, useVideos } from '@/api'
import type { ReviewSentence, ReviewWord, VideoSummary } from '@/api'
import { formatDuration, formatTimestamp } from '@/lib/format'
import { DEFAULT_PLAYBACK_RATE, Player } from '@/lib/player'
import { cn } from '@/lib/utils'

// AI-cut words whose keep-likelihood clears this bar are flagged "maybe keep".
const SUGGEST_KEEP_THRESHOLD = 0.4
// AI-kept words whose salience falls below this bar are flagged as "maybe trim".
// Kept deliberately low so only genuinely near-zero-salience words get hinted (~10%).
const TRIM_CANDIDATE_THRESHOLD = 0.1
const CUT_HISTORY_LIMIT = 100
const REVIEW_DRAFT_VERSION = 1
const FILTER_PRIORITY = [
  'duplicate',
  'false_start',
  'silence',
  'low_value',
  'aside',
  'filler_phrase',
  'redundant_explanation',
  'repetition_residue',
  'incomplete_thought',
]
const KEYBOARD_SHORTCUT_GROUPS = [
  {
    title: 'Playback',
    shortcuts: [
      ['Space', 'Play or pause the video'],
      ['L', 'Audition the current sentence or selection'],
      ['⇧L', 'Toggle audition loop mode'],
    ],
  },
  {
    title: 'Cursor And Selection',
    shortcuts: [
      ['← / →', 'Move the caret word by word'],
      ['⇧← / ⇧→', 'Expand the selection word by word'],
      ['S', 'Select the current sentence'],
      ['⇧S', 'Select the current paragraph/chunk'],
      ['Esc', 'Clear the current selection or close this drawer'],
    ],
  },
  {
    title: 'Editing',
    shortcuts: [
      ['⌫ / Delete', 'Cut the selected words'],
      ['Enter', 'Keep the selected words'],
      ['X', 'Cut the current word or selection'],
      ['R', 'Restore AI-cut words in the current selection'],
    ],
  },
  {
    title: 'Navigation',
    shortcuts: [
      ['N', 'Jump to the next AI cut'],
      ['A', 'Jump to the next attention item'],
      ['Search Enter', 'Open the selected search result'],
      ['Search Esc', 'Clear search and filters'],
    ],
  },
  {
    title: 'Save And History',
    shortcuts: [
      ['⌘S / Ctrl+S', 'Save the reviewed edit'],
      ['⌘Z / Ctrl+Z', 'Undo the last edit'],
      ['⇧⌘Z / ⌘Y / Ctrl+Y', 'Redo the last undone edit'],
    ],
  },
]
// How far ahead of a cut word's audio we want to have already seeked away. The
// actual trigger is pulled into the silent gap after the previous kept word (see
// cutSpans), so this only bounds how much of a long pause we preserve.
const PREVIEW_SKIP_ENTRY_MARGIN_SECONDS = 0.15
const PREVIEW_SKIP_END_EPSILON_SECONDS = 0.05
const PREVIEW_SKIP_POSTROLL_SECONDS = 0.12

type StatusKey = 'green' | 'yellow' | 'red' | 'restore'

type StatusMeta = {
  label: string
  dot: string
  text: string
  // Background tint used to make attention items pop in "Attention only" mode.
  emphasis: string
}

const STATUS_META: Record<StatusKey, StatusMeta> = {
  green: {
    label: 'Confident',
    dot: 'bg-status-green',
    text: 'text-status-green',
    emphasis: '',
  },
  yellow: {
    label: 'Needs review',
    dot: 'bg-status-yellow',
    text: 'text-status-yellow',
    emphasis: 'bg-status-yellow/12',
  },
  red: {
    label: 'Confirmed cut',
    dot: 'bg-status-red',
    text: 'text-status-red',
    emphasis: 'bg-status-red/12',
  },
  restore: {
    label: 'Restore?',
    dot: 'bg-status-restore',
    text: 'text-status-restore',
    emphasis: 'bg-status-restore/12',
  },
}

function statusKey(status: string): StatusKey {
  return status === 'yellow' || status === 'red' || status === 'restore' ? status : 'green'
}

// Only decisions the pipeline might have gotten wrong warrant a human look.
// "green" (confident keep) and "red" (confident cut) are settled.
function isAttentionStatus(key: StatusKey): boolean {
  return key === 'yellow' || key === 'restore'
}

function sameCutSet(a: Set<number>, b: Set<number>) {
  if (a.size !== b.size) return false
  for (const value of a) {
    if (!b.has(value)) return false
  }
  return true
}

type AuditionRange = {
  start: number
  end: number
  label: string
}

type LoadedDraft = {
  cutSet: Set<number>
  updatedAt: string
}

type SearchResult = {
  sentence: ReviewSentence
  wordIdx: number | null
  start: number
}

function buildInitialCutSet(payload: { sentences: ReviewSentence[] }) {
  const initialCut = new Set<number>()
  for (const sentence of payload.sentences) {
    for (const word of sentence.words ?? []) {
      if (!word.kept) initialCut.add(word.idx)
    }
  }
  return initialCut
}

function cutSetToArray(cutSet: Set<number>) {
  return R.pipe(
    Array.from(cutSet),
    R.sortBy((value) => value),
  )
}

function draftStorageKey(videoId: string) {
  return `ai-video-editor:review-draft:${videoId}:v${REVIEW_DRAFT_VERSION}`
}

function loadDraft(videoId: string, validWordIds: Set<number>): LoadedDraft | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(draftStorageKey(videoId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as {
      version?: number
      cutWords?: unknown
      updatedAt?: unknown
    }
    if (parsed.version !== REVIEW_DRAFT_VERSION || !Array.isArray(parsed.cutWords)) return null
    const cutWords = parsed.cutWords.filter(
      (value): value is number => typeof value === 'number' && validWordIds.has(value),
    )
    return {
      cutSet: new Set(cutWords),
      updatedAt: typeof parsed.updatedAt === 'string' ? parsed.updatedAt : '',
    }
  } catch {
    return null
  }
}

function saveDraft(videoId: string, cutSet: Set<number>, updatedAt: string) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(
    draftStorageKey(videoId),
    JSON.stringify({
      version: REVIEW_DRAFT_VERSION,
      cutWords: cutSetToArray(cutSet),
      updatedAt,
    }),
  )
}

function clearDraft(videoId: string) {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(draftStorageKey(videoId))
}

function sentenceRange(sentence: ReviewSentence): [number, number] | null {
  const sentenceWords = sentence.words ?? []
  const first = sentenceWords[0]
  const last = sentenceWords.at(-1)
  return first && last ? [first.idx, last.idx] : null
}

function normalizeToken(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
}

function labelForToken(value: string) {
  const token = normalizeToken(value)
  return token === 'low_value' ? 'low-value' : token.replace(/_/g, ' ')
}

function sentenceHasLowValueSignal(sentence: ReviewSentence) {
  return (
    statusKey(sentence.status) === 'yellow' ||
    sentence.keep_confidence < 80 ||
    (sentence.words ?? []).some(
      (word) => word.ai_kept && word.keep_score < TRIM_CANDIDATE_THRESHOLD,
    )
  )
}

function metadataTokensForSentence(sentence: ReviewSentence) {
  const tokens = new Set<string>()
  for (const tag of sentence.tags ?? []) {
    const token = normalizeToken(tag)
    if (token) tokens.add(token)
  }
  for (const reason of [sentence.reason, ...(sentence.words ?? []).map((word) => word.reason)]) {
    const token = normalizeToken(reason)
    if (token && token !== 'speech') tokens.add(token)
  }
  if (sentenceHasLowValueSignal(sentence)) tokens.add('low_value')
  return tokens
}

// A cut span the playhead has reached. `trigger` already sits inside the silent
// gap before the cut audio, so no extra lookahead is needed here.
function activeCutSpan(
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

function previewSkipTarget(end: number, duration: number): number {
  const padded = end + PREVIEW_SKIP_POSTROLL_SECONDS
  return duration > 0 ? Math.min(padded, duration) : padded
}

type SeekableMedia = {
  currentTime: number
}

function isSeekableMedia(media: unknown): media is SeekableMedia {
  return (
    typeof media === 'object' &&
    media !== null &&
    'currentTime' in media &&
    typeof (media as { currentTime?: unknown }).currentTime === 'number'
  )
}

type EditorProps = {
  videoId: string
  videos: VideoSummary[]
  message: string
  onSelect: (id: string) => void
  view: AppView
  onViewChange: (view: AppView) => void
}

export default function App() {
  const videosQuery = useVideos()
  const [selectedId, setSelectedId] = useState('')
  const [view, setView] = useState<AppView>('editor')

  useEffect(() => {
    const list = videosQuery.data
    if (!selectedId && list && list.length > 0) setSelectedId(list[0].id)
  }, [videosQuery.data, selectedId])

  const message = videosQuery.isPending
    ? 'Loading videos…'
    : videosQuery.error
      ? videosQuery.error.message
      : (videosQuery.data?.length ?? 0) > 0
        ? 'Select a video to start editing.'
        : 'No processed videos found.'

  return (
    <>
      <Player.Provider key={`${view}:${selectedId || 'empty'}`}>
        {view === 'diff' ? (
          <DiffView
            videoId={selectedId}
            videos={videosQuery.data ?? []}
            message={message}
            onSelect={setSelectedId}
            view={view}
            onViewChange={setView}
          />
        ) : (
          <Editor
            videoId={selectedId}
            videos={videosQuery.data ?? []}
            message={message}
            onSelect={setSelectedId}
            view={view}
            onViewChange={setView}
          />
        )}
      </Player.Provider>
      {import.meta.env.DEV && <Agentation />}
    </>
  )
}

function Editor({ videoId, videos, message, onSelect, view, onViewChange }: EditorProps) {
  const player = Player.usePlayer()
  const paused = Player.usePlayer((state) => state.paused)
  const wordRefs = useRef(new Map<number, HTMLSpanElement>())
  const searchInputRef = useRef<HTMLInputElement>(null)

  const review = useReview(videoId)
  const saveReviewMutation = useSaveReview(videoId)
  const renderReviewMutation = useRenderReview(videoId)
  const payload = review.data ?? null

  const [cutSet, setCutSet] = useState<Set<number>>(new Set())
  const cutSetRef = useRef(cutSet)
  const [savedCutSet, setSavedCutSet] = useState<Set<number>>(new Set())
  const [anchor, setAnchor] = useState<number | null>(null)
  const [focusIdx, setFocusIdx] = useState<number | null>(null)
  const [activeIdx, setActiveIdx] = useState<number | null>(null)
  const [undoStack, setUndoStack] = useState<Array<Set<number>>>([])
  const [redoStack, setRedoStack] = useState<Array<Set<number>>>([])
  const [auditionRange, setAuditionRange] = useState<AuditionRange | null>(null)
  const [draftRestored, setDraftRestored] = useState(false)
  const [lastDraftAt, setLastDraftAt] = useState<string | null>(null)
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeFilters, setActiveFilters] = useState<string[]>([])
  const [activeSearchResultIndex, setActiveSearchResultIndex] = useState(0)
  const [status, setStatus] = useState('')

  const previewEdit = useBoolean(true)
  const focusAttention = useBoolean(false)
  const loopAudition = useBoolean(false)
  const followPlayback = useBoolean(true)
  const shortcutsOpen = useBoolean(false)

  useEffect(() => {
    cutSetRef.current = cutSet
  }, [cutSet])

  // Seed the cut set from the AI decisions when the payload first loads.
  useEffect(() => {
    if (!payload) return
    const initialCut = buildInitialCutSet(payload)
    const validWordIds = new Set<number>()
    for (const sentence of payload.sentences) {
      for (const word of sentence.words ?? []) {
        validWordIds.add(word.idx)
      }
    }
    const draft = loadDraft(payload.video.id, validWordIds)
    const restoredDraft = draft !== null && !sameCutSet(draft.cutSet, initialCut)
    setCutSet(draft?.cutSet ?? initialCut)
    setSavedCutSet(initialCut)
    setUndoStack([])
    setRedoStack([])
    setAuditionRange(null)
    setDraftRestored(restoredDraft)
    setLastDraftAt(draft?.updatedAt || null)
    setLastSavedAt(null)
    setSearchQuery('')
    setActiveFilters([])
    setActiveSearchResultIndex(0)
    setStatus(restoredDraft ? 'Restored unsaved local draft for this video.' : '')
  }, [payload])

  const words = useMemo(
    () => (payload ? R.flatMap(payload.sentences, (sentence) => sentence.words ?? []) : []),
    [payload],
  )

  const wordIndexByIdx = useMemo(() => {
    const map = new Map<number, number>()
    words.forEach((word, index) => map.set(word.idx, index))
    return map
  }, [words])

  const wordByIdx = useMemo(() => {
    const map = new Map<number, ReviewWord>()
    for (const word of words) map.set(word.idx, word)
    return map
  }, [words])

  // Map every word index back to its sentence for playback highlighting.
  const sentenceByWord = useMemo(() => {
    const map = new Map<number, ReviewSentence>()
    if (payload) {
      for (const sentence of payload.sentences) {
        for (const word of sentence.words ?? []) map.set(word.idx, sentence)
      }
    }
    return map
  }, [payload])

  // Ordered list of sentences that need a human look. Attention = the pipeline
  // decision might be wrong: "yellow" (kept, maybe should cut) + "restore" (cut,
  // maybe should keep). "green" (confident keep) and "red" (confident cut) are
  // settled decisions and never count as attention.
  const attentionTargets = useMemo(() => {
    if (!payload) return [] as Array<{ idx: number; start: number; status: StatusKey }>
    const targets = payload.sentences.flatMap((sentence) => {
      const key = statusKey(sentence.status)
      if (!isAttentionStatus(key)) return []
      const firstWord = (sentence.words ?? [])[0]
      return [{ idx: firstWord?.idx ?? -1, start: sentence.start, status: key }]
    })
    return R.sortBy(targets, (target) => target.start)
  }, [payload])

  const selectionRange = useMemo<[number, number] | null>(() => {
    if (anchor === null || focusIdx === null) return null
    return [Math.min(anchor, focusIdx), Math.max(anchor, focusIdx)]
  }, [anchor, focusIdx])

  const currentWordIdx = focusIdx ?? anchor ?? activeIdx
  const currentWord = currentWordIdx === null ? null : (wordByIdx.get(currentWordIdx) ?? null)
  const currentSentence =
    currentWordIdx === null ? null : (sentenceByWord.get(currentWordIdx) ?? null)
  const selectedSentence = anchor === null ? null : (sentenceByWord.get(anchor) ?? null)
  const selectedAttentionSentence =
    selectedSentence && isAttentionStatus(statusKey(selectedSentence.status))
      ? selectedSentence
      : null
  const manualSelectionActive = selectionRange !== null
  const shouldFollowPlayback = followPlayback.value && !paused && !manualSelectionActive

  const isDirty = useMemo(
    () => payload !== null && !sameCutSet(cutSet, savedCutSet),
    [payload, cutSet, savedCutSet],
  )

  useEffect(() => {
    if (!payload) return
    if (!isDirty) {
      clearDraft(payload.video.id)
      setLastDraftAt(null)
      setDraftRestored(false)
      return
    }
    const updatedAt = new Date().toISOString()
    saveDraft(payload.video.id, cutSet, updatedAt)
    setLastDraftAt(updatedAt)
  }, [payload, cutSet, isDirty])

  useEffect(() => {
    if (!isDirty) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [isDirty])

  const filterOptions = useMemo(() => {
    if (!payload) return [] as Array<{ token: string; label: string; count: number }>
    const counts = new Map<string, number>()
    for (const sentence of payload.sentences) {
      for (const token of metadataTokensForSentence(sentence)) {
        counts.set(token, (counts.get(token) ?? 0) + 1)
      }
    }
    return Array.from(counts, ([token, count]) => ({
      token,
      label: labelForToken(token),
      count,
    })).sort((a, b) => {
      const priorityA = FILTER_PRIORITY.indexOf(a.token)
      const priorityB = FILTER_PRIORITY.indexOf(b.token)
      if (priorityA !== -1 || priorityB !== -1) {
        return (priorityA === -1 ? 999 : priorityA) - (priorityB === -1 ? 999 : priorityB)
      }
      return a.label.localeCompare(b.label)
    })
  }, [payload])

  const normalizedSearchQuery = searchQuery.trim().toLowerCase()
  const activeFilterSet = useMemo(() => new Set(activeFilters), [activeFilters])

  const searchResults = useMemo<SearchResult[]>(() => {
    if (!payload || (!normalizedSearchQuery && activeFilterSet.size === 0)) return []

    return payload.sentences.flatMap((sentence) => {
      const tokens = metadataTokensForSentence(sentence)
      const matchesFilters =
        activeFilterSet.size === 0 || Array.from(activeFilterSet).some((token) => tokens.has(token))
      if (!matchesFilters) return []

      const sentenceText = sentence.text.toLowerCase()
      const matchingWord =
        normalizedSearchQuery.length > 0
          ? (sentence.words ?? []).find((word) =>
              word.text.toLowerCase().includes(normalizedSearchQuery),
            )
          : null
      const matchesQuery =
        normalizedSearchQuery.length === 0 ||
        sentenceText.includes(normalizedSearchQuery) ||
        Boolean(matchingWord)
      if (!matchesQuery) return []

      const firstWord = (sentence.words ?? [])[0] ?? null
      return [
        {
          sentence,
          wordIdx: matchingWord?.idx ?? firstWord?.idx ?? null,
          start: matchingWord?.start ?? firstWord?.start ?? sentence.start,
        },
      ]
    })
  }, [payload, normalizedSearchQuery, activeFilterSet])

  const searchResultSentenceIds = useMemo(
    () => new Set(searchResults.map((result) => result.sentence.idx)),
    [searchResults],
  )
  const activeSearchResult = searchResults[activeSearchResultIndex] ?? null

  useEffect(() => {
    setActiveSearchResultIndex(0)
  }, [normalizedSearchQuery, activeFilters])

  useEffect(() => {
    if (activeSearchResultIndex >= searchResults.length) {
      setActiveSearchResultIndex(Math.max(0, searchResults.length - 1))
    }
  }, [activeSearchResultIndex, searchResults.length])

  // Contiguous runs of currently-cut words → [trigger, end] spans skipped during
  // preview. `trigger` is the seek-away point: pulled into the silent gap right
  // after the previous kept word so the cut word's audio never starts, but never
  // earlier than that kept word's end (so we don't clip kept audio). For a long
  // pause before the cut we keep most of it and only seek `ENTRY_MARGIN` early.
  const cutSpans = useMemo(() => {
    const spans: Array<[number, number]> = []
    let start: number | null = null
    let end = 0
    let prevKeptEnd = 0
    let entryGuard = 0
    for (const word of words) {
      if (cutSet.has(word.idx)) {
        if (start === null) {
          start = word.start
          end = word.end
          entryGuard = prevKeptEnd
        } else {
          end = Math.max(end, word.end)
        }
      } else {
        if (start !== null) {
          const trigger = Math.max(entryGuard, start - PREVIEW_SKIP_ENTRY_MARGIN_SECONDS)
          spans.push([trigger, end])
          start = null
        }
        prevKeptEnd = Math.max(prevKeptEnd, word.end)
      }
    }
    if (start !== null) {
      const trigger = Math.max(entryGuard, start - PREVIEW_SKIP_ENTRY_MARGIN_SECONDS)
      spans.push([trigger, end])
    }
    return spans
  }, [words, cutSet])

  const auditionTarget = useMemo<AuditionRange | null>(() => {
    if (!payload) return null
    if (selectionRange && selectionRange[0] !== selectionRange[1]) {
      const firstWord = wordByIdx.get(selectionRange[0])
      const lastWord = wordByIdx.get(selectionRange[1])
      if (firstWord && lastWord) {
        return {
          start: firstWord.start,
          end: lastWord.end,
          label: `${selectionRange[1] - selectionRange[0] + 1} selected words`,
        }
      }
    }

    const idx = focusIdx ?? anchor ?? activeIdx
    const sentence = idx === null ? null : sentenceByWord.get(idx)
    if (!sentence) return null
    return { start: sentence.start, end: sentence.end, label: 'current sentence' }
  }, [payload, selectionRange, wordByIdx, focusIdx, anchor, activeIdx, sentenceByWord])

  const scrollToWord = useEventCallback((idx: number) => {
    wordRefs.current.get(idx)?.scrollIntoView({ block: 'nearest' })
  })

  const seekTo = useEventCallback((seconds: number, play = false) => {
    void player.seek(seconds)
    if (play) void player.play()
  })

  const commitCutSet = useEventCallback((next: Set<number>) => {
    if (sameCutSet(cutSet, next)) return
    setUndoStack((history) => [...history.slice(-(CUT_HISTORY_LIMIT - 1)), new Set(cutSet)])
    setRedoStack([])
    setCutSet(next)
  })

  const setCut = useEventCallback((lo: number, hi: number, cut: boolean) => {
    const next = new Set(cutSet)
    for (const i of R.range(lo, hi + 1)) {
      if (cut) next.add(i)
      else next.delete(i)
    }
    commitCutSet(next)
  })

  const undoCutChange = useEventCallback(() => {
    const previous = undoStack.at(-1)
    if (!previous) return
    setUndoStack(undoStack.slice(0, -1))
    setRedoStack((history) => [new Set(cutSet), ...history.slice(0, CUT_HISTORY_LIMIT - 1)])
    setCutSet(new Set(previous))
    setStatus('Undid last edit.')
  })

  const redoCutChange = useEventCallback(() => {
    const next = redoStack[0]
    if (!next) return
    setRedoStack(redoStack.slice(1))
    setUndoStack((history) => [...history.slice(-(CUT_HISTORY_LIMIT - 1)), new Set(cutSet)])
    setCutSet(new Set(next))
    setStatus('Redid edit.')
  })

  const applySelection = useEventCallback((cut: boolean) => {
    if (!selectionRange) return
    setCut(selectionRange[0], selectionRange[1], cut)
  })

  const selectRange = useEventCallback((range: [number, number], label: string) => {
    setAuditionRange(null)
    setAnchor(range[0])
    setFocusIdx(range[1])
    scrollToWord(range[0])
    setStatus(`Selected ${label}.`)
  })

  const selectCurrentSentence = useEventCallback(() => {
    if (!currentSentence) return
    const range = sentenceRange(currentSentence)
    if (!range) return
    selectRange(range, 'current sentence')
  })

  const selectCurrentChunk = useEventCallback(() => {
    if (!currentSentence) return
    const range = sentenceRange(currentSentence)
    if (!range) return
    selectRange(range, 'current chunk')
  })

  const cutCurrentContext = useEventCallback(() => {
    if (selectionRange) {
      setCut(selectionRange[0], selectionRange[1], true)
      setStatus(`Cut ${selectionRange[1] - selectionRange[0] + 1} selected words.`)
      return
    }
    if (currentWord) {
      setCut(currentWord.idx, currentWord.idx, true)
      setStatus('Cut current word.')
      return
    }
    if (currentSentence) {
      const range = sentenceRange(currentSentence)
      if (!range) return
      setCut(range[0], range[1], true)
      selectRange(range, 'current sentence')
      setStatus('Cut current sentence.')
    }
  })

  const restoreAiCutRange = useEventCallback((range: [number, number]) => {
    const next = new Set(cutSet)
    let restored = 0
    for (const idx of R.range(range[0], range[1] + 1)) {
      const word = wordByIdx.get(idx)
      if (word && !word.ai_kept && next.has(idx)) {
        next.delete(idx)
        restored += 1
      }
    }
    if (restored === 0) {
      setStatus('No AI-cut words in the current selection.')
      return
    }
    commitCutSet(next)
    setStatus(`Restored ${restored} AI-cut word${restored === 1 ? '' : 's'}.`)
  })

  const restoreCurrentAiCut = useEventCallback(() => {
    if (selectionRange) {
      restoreAiCutRange(selectionRange)
      return
    }
    if (currentWord && !currentWord.ai_kept) {
      restoreAiCutRange([currentWord.idx, currentWord.idx])
      return
    }
    if (currentSentence) {
      const range = sentenceRange(currentSentence)
      if (range) restoreAiCutRange(range)
    }
  })

  const setSentenceCut = useEventCallback((sentence: ReviewSentence, cut: boolean) => {
    const range = sentenceRange(sentence)
    if (!range) return
    setCut(range[0], range[1], cut)
    selectRange(range, 'attention chunk')
    setStatus(`${cut ? 'Cut' : 'Kept'} selected attention chunk.`)
  })

  const moveWordCursor = useEventCallback((delta: -1 | 1, extendSelection: boolean) => {
    if (words.length === 0) return
    const currentIdx = focusIdx ?? anchor ?? activeIdx
    const currentIndex = currentIdx === null ? -1 : (wordIndexByIdx.get(currentIdx) ?? -1)
    const nextIndex = Math.max(0, Math.min(words.length - 1, currentIndex + delta))
    const nextWord = words[nextIndex] ?? words[0]
    if (!nextWord) return

    if (extendSelection && anchor !== null) {
      setFocusIdx(nextWord.idx)
    } else {
      setAuditionRange(null)
      setAnchor(nextWord.idx)
      setFocusIdx(nextWord.idx)
      void player.seek(nextWord.start)
    }
    scrollToWord(nextWord.idx)
  })

  const selectWord = useEventCallback((word: ReviewWord, event: PointerEvent) => {
    if (event.shiftKey && anchor !== null) {
      setFocusIdx(word.idx)
      scrollToWord(word.idx)
      return
    }

    const clickedActiveWord = anchor === word.idx && focusIdx === word.idx
    if (clickedActiveWord) {
      void player.play()
      return
    }

    setAnchor(word.idx)
    setFocusIdx(word.idx)
    setAuditionRange(null)
    seekTo(word.start)
  })

  const toggleWord = useEventCallback((idx: number) => {
    setCut(idx, idx, !cutSet.has(idx))
  })

  const togglePlay = useEventCallback(() => {
    player.togglePaused()
  })

  const playAudition = useEventCallback(() => {
    if (!auditionTarget) return
    setAuditionRange(auditionTarget)
    setStatus(
      `Auditioning ${auditionTarget.label} · ${formatDuration(auditionTarget.end - auditionTarget.start)}.`,
    )
    void player.seek(auditionTarget.start)
    void player.play()
  })

  const playSentenceAudition = useEventCallback((sentence: ReviewSentence) => {
    const target = {
      start: sentence.start,
      end: sentence.end,
      label: 'selected attention chunk',
    }
    setAuditionRange(target)
    setStatus(`Auditioning ${target.label} · ${formatDuration(target.end - target.start)}.`)
    void player.seek(target.start)
    void player.play()
  })

  const finishAudition = useEventCallback(() => {
    setAuditionRange(null)
    setStatus('Audition complete.')
  })

  const openSearchResult = useEventCallback((index: number) => {
    const result = searchResults[index]
    if (!result) return
    setActiveSearchResultIndex(index)
    setAuditionRange(null)
    const targetWordIdx = result.wordIdx ?? (result.sentence.words ?? [])[0]?.idx ?? null
    if (targetWordIdx !== null) {
      setAnchor(targetWordIdx)
      setFocusIdx(targetWordIdx)
      scrollToWord(targetWordIdx)
    }
    void player.seek(result.start)
    setStatus(`Search result ${index + 1} of ${searchResults.length}.`)
  })

  const moveSearchResult = useEventCallback((delta: -1 | 1) => {
    if (searchResults.length === 0) return
    const nextIndex =
      (activeSearchResultIndex + delta + searchResults.length) % searchResults.length
    openSearchResult(nextIndex)
  })

  const toggleFilter = useEventCallback((token: string) => {
    setActiveFilters((current) =>
      current.includes(token) ? current.filter((item) => item !== token) : [...current, token],
    )
  })

  const jumpToNextAiCut = useEventCallback(() => {
    const time = player.currentTime ?? 0
    let prevAiKept = true
    for (const word of words) {
      const isAiCut = !word.ai_kept
      if (isAiCut && prevAiKept && word.start > time + 0.05) {
        setAuditionRange(null)
        setAnchor(word.idx)
        setFocusIdx(word.idx)
        void player.seek(word.start)
        scrollToWord(word.idx)
        return
      }
      prevAiKept = !isAiCut
    }
    setStatus('No more AI cuts after the playhead.')
  })

  const jumpToNextAttention = useEventCallback(() => {
    if (attentionTargets.length === 0) {
      setStatus('No attention items flagged by enrichment.')
      return
    }
    const time = player.currentTime ?? 0
    // Cycle: next target after the playhead, wrapping back to the first.
    const next =
      attentionTargets.find((target) => target.start > time + 0.05) ?? attentionTargets[0]
    setAuditionRange(null)
    void player.seek(next.start)
    if (next.idx >= 0) {
      setAnchor(next.idx)
      setFocusIdx(next.idx)
      scrollToWord(next.idx)
    }
    setStatus(`Attention: ${STATUS_META[next.status].label} at ${formatTimestamp(next.start)}.`)
  })

  const handleActive = useEventCallback((idx: number | null) => {
    setActiveIdx(idx)
    if (idx !== null && shouldFollowPlayback) scrollToWord(idx)
  })

  const saveReview = useEventCallback(async () => {
    if (!payload) return
    setStatus('Saving reviewed edit…')
    const cutSnapshot = new Set(cutSet)
    try {
      const cutWords = cutSetToArray(cutSnapshot)
      const saved = await saveReviewMutation.mutateAsync(cutWords)
      const currentMatchesSavedSnapshot = sameCutSet(cutSetRef.current, cutSnapshot)
      setSavedCutSet(cutSnapshot)
      setLastSavedAt(new Date().toISOString())
      setDraftRestored(false)
      if (currentMatchesSavedSnapshot) {
        clearDraft(payload.video.id)
        setLastDraftAt(null)
        setStatus(
          `Saved. Keep ${formatDuration(saved.keep_duration)} · cut ${formatDuration(saved.cut_duration)}.`,
        )
      } else {
        setStatus('Saved. Newer local edits remain unsaved.')
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Save failed.')
    }
  })

  const renderReview = useEventCallback(async () => {
    if (!payload) return
    setStatus('Rendering reviewed video (this can take a while)…')
    try {
      const rendered = await renderReviewMutation.mutateAsync()
      setStatus(`Rendered ${rendered.output_name}.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Render failed.')
    }
  })

  const editorHotkeysEnabled = payload !== null && !shortcutsOpen.value

  const editorHotkeys: UseHotkeyDefinition[] = [
    {
      hotkey: 'Mod+S',
      callback: () => {
        void saveReview()
      },
      options: { enabled: editorHotkeysEnabled, ignoreInputs: false },
    },
    {
      hotkey: 'Mod+Z',
      callback: undoCutChange,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Mod+Shift+Z',
      callback: redoCutChange,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Mod+Y',
      callback: redoCutChange,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'ArrowLeft',
      callback: () => moveWordCursor(-1, false),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Shift+ArrowLeft',
      callback: () => moveWordCursor(-1, true),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'ArrowRight',
      callback: () => moveWordCursor(1, false),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Shift+ArrowRight',
      callback: () => moveWordCursor(1, true),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Space',
      callback: togglePlay,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Backspace',
      callback: () => applySelection(true),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Delete',
      callback: () => applySelection(true),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Enter',
      callback: () => applySelection(false),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'S',
      callback: selectCurrentSentence,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Shift+S',
      callback: selectCurrentChunk,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'X',
      callback: cutCurrentContext,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'R',
      callback: restoreCurrentAiCut,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Escape',
      callback: () => {
        setAnchor(null)
        setFocusIdx(null)
      },
      options: { enabled: editorHotkeysEnabled, ignoreInputs: true },
    },
    {
      hotkey: 'N',
      callback: jumpToNextAiCut,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'A',
      callback: jumpToNextAttention,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'L',
      callback: playAudition,
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Shift+L',
      callback: () => loopAudition.setValue(!loopAudition.value),
      options: { enabled: editorHotkeysEnabled },
    },
    {
      hotkey: 'Enter',
      callback: () => openSearchResult(activeSearchResultIndex),
      options: {
        enabled: editorHotkeysEnabled,
        ignoreInputs: false,
        target: searchInputRef,
      },
    },
    {
      hotkey: 'Escape',
      callback: () => {
        setSearchQuery('')
        setActiveFilters([])
        setActiveSearchResultIndex(0)
      },
      options: {
        enabled: editorHotkeysEnabled,
        ignoreInputs: false,
        target: searchInputRef,
      },
    },
    {
      hotkey: 'Escape',
      callback: () => shortcutsOpen.setValue(false),
      options: { enabled: shortcutsOpen.value },
    },
  ]

  useHotkeys(editorHotkeys, {
    conflictBehavior: 'allow',
    preventDefault: true,
    stopPropagation: true,
  })

  const hasCaret = anchor !== null && focusIdx !== null && anchor === focusIdx
  const selectionCount = selectionRange ? selectionRange[1] - selectionRange[0] + 1 : 0
  const canUndo = undoStack.length > 0
  const canRedo = redoStack.length > 0
  const hasSearch = normalizedSearchQuery.length > 0 || activeFilters.length > 0
  const saveStateText = saveReviewMutation.isPending
    ? 'Saving…'
    : isDirty
      ? 'Unsaved draft'
      : lastSavedAt
        ? 'Saved'
        : draftRestored
          ? 'Draft restored'
          : 'Saved'

  const statusText = review.isLoading
    ? 'Loading review…'
    : review.error
      ? review.error.message
      : status ||
        (payload
          ? 'Ready. Click a word to place the cursor · L auditions locally · select words and press ⌫ to cut.'
          : message)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-card px-4 py-2.5">
        <span className="text-sm font-extrabold tracking-tight">AI Video Editor</span>
        <ViewSwitch view={view} onChange={onViewChange} />

        <Select value={videoId} onValueChange={onSelect}>
          <SelectTrigger size="sm" className="w-[260px]">
            <SelectValue placeholder="Select a video" />
          </SelectTrigger>
          <SelectContent>
            {videos.map((video) => (
              <SelectItem key={video.id} value={video.id}>
                {video.source_name}
                {video.has_review ? ' • reviewed' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {payload && (
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Badge
              variant="outline"
              className={cn(
                isDirty ? 'border-changed/60 text-changed' : 'border-keep/40 text-keep',
              )}
            >
              {isDirty ? 'Unsaved' : 'Saved'}
            </Badge>
          </div>
        )}

        <div className={cn('flex items-center gap-2', !payload && 'ml-auto')}>
          <Button
            size="sm"
            variant={isDirty ? 'default' : 'secondary'}
            onClick={saveReview}
            disabled={!payload || saveReviewMutation.isPending}
          >
            <Save />
            {saveReviewMutation.isPending ? 'Saving…' : 'Save ⌘S'}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={renderReview}
            disabled={!payload || renderReviewMutation.isPending}
          >
            <Redo2 />
            {renderReviewMutation.isPending ? 'Rendering…' : 'Render MP4'}
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Open keyboard shortcuts"
            onClick={() => shortcutsOpen.setValue(true)}
          >
            <CircleHelp />
          </Button>
        </div>
      </header>

      {payload ? (
        <ResizableSplit
          sidebar={
            <div className="flex flex-col gap-3 p-4">
              <div className="overflow-hidden rounded-xl bg-black [&_.media-button--pip]:hidden [&_video]:w-full">
                <VideoSkin>
                  <Video src={`/media/${payload.video.id}`} playsInline />
                </VideoSkin>
              </div>

              <DefaultPlaybackRate rate={DEFAULT_PLAYBACK_RATE} />

              <PlaybackSync
                words={words}
                cutSpans={cutSpans}
                previewEdit={previewEdit.value}
                auditionRange={auditionRange}
                loopAudition={loopAudition.value}
                onActive={handleActive}
                onAuditionEnd={finishAudition}
              />

              <div className="grid grid-cols-2 gap-2">
                <Toggle
                  variant="outline"
                  pressed={previewEdit.value}
                  onPressedChange={previewEdit.setValue}
                  className="justify-start gap-2"
                >
                  <Eye />
                  Preview edit
                </Toggle>
                <Toggle
                  variant="outline"
                  pressed={focusAttention.value}
                  onPressedChange={focusAttention.setValue}
                  className="justify-start gap-2"
                >
                  <ListFilter />
                  Attention only
                </Toggle>
                <Toggle
                  variant="outline"
                  pressed={followPlayback.value}
                  onPressedChange={followPlayback.setValue}
                  className="justify-start gap-2"
                >
                  <LocateFixed />
                  Follow playback
                </Toggle>
              </div>

              <div className="rounded-lg border bg-muted/20 p-3">
                <div className="mb-2 flex items-center gap-2">
                  <Search className="size-4 shrink-0 text-muted-foreground" />
                  <input
                    ref={searchInputRef}
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.currentTarget.value)}
                    placeholder="Search transcript"
                    className="h-8 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  {(searchQuery || activeFilters.length > 0) && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label="Clear search"
                      onClick={() => {
                        setSearchQuery('')
                        setActiveFilters([])
                        setActiveSearchResultIndex(0)
                      }}
                    >
                      <X />
                    </Button>
                  )}
                </div>

                <div className="mb-2 flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    onClick={() => moveSearchResult(-1)}
                    disabled={searchResults.length === 0}
                  >
                    Prev
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    onClick={() => moveSearchResult(1)}
                    disabled={searchResults.length === 0}
                  >
                    Next
                  </Button>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {hasSearch
                      ? `${searchResults.length} result${searchResults.length === 1 ? '' : 's'}`
                      : 'Search or filter'}
                  </span>
                </div>

                {filterOptions.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {filterOptions.slice(0, 12).map((filter) => {
                      const active = activeFilters.includes(filter.token)
                      return (
                        <button
                          key={filter.token}
                          type="button"
                          className={cn(
                            'rounded-full border px-2 py-0.5 text-xs transition-colors',
                            active
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-border bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                          )}
                          onClick={() => toggleFilter(filter.token)}
                        >
                          {filter.label}
                          <span className="ml-1 opacity-70">{filter.count}</span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" size="sm" onClick={undoCutChange} disabled={!canUndo}>
                  <Undo2 />
                  Undo ⌘Z
                </Button>
                <Button variant="outline" size="sm" onClick={redoCutChange} disabled={!canRedo}>
                  <Redo2 />
                  Redo ⇧⌘Z
                </Button>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={playAudition}
                  disabled={!auditionTarget}
                >
                  <Play />
                  Audition (L)
                </Button>
                <Toggle
                  variant="outline"
                  pressed={loopAudition.value}
                  onPressedChange={loopAudition.setValue}
                  className="justify-start gap-2"
                >
                  <Repeat2 />
                  Loop ⇧L
                </Toggle>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => applySelection(true)}
                  disabled={!selectionRange}
                >
                  <Scissors />
                  Cut ⌫
                </Button>
                <Button
                  size="sm"
                  className="bg-keep text-white hover:bg-keep/90"
                  onClick={() => applySelection(false)}
                  disabled={!selectionRange}
                >
                  Keep ⏎
                </Button>
                <Button variant="secondary" size="sm" onClick={jumpToNextAiCut}>
                  <SkipForward />
                  Next AI cut (N)
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={jumpToNextAttention}
                  disabled={attentionTargets.length === 0}
                >
                  <Flag />
                  Attention (A)
                </Button>
              </div>

              <p className="text-xs text-muted-foreground">
                {hasCaret
                  ? 'Cursor on word · click active word to play · ←/→ move'
                  : selectionRange
                    ? `${selectionCount} words selected`
                    : 'Click a word to place the cursor · L auditions the local sentence'}
              </p>

              <div className="rounded-lg border bg-card p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Review inspector
                  </span>
                  {selectedAttentionSentence && (
                    <Badge variant="outline" className="text-[10px]">
                      {STATUS_META[statusKey(selectedAttentionSentence.status)].label}
                    </Badge>
                  )}
                </div>
                {selectedAttentionSentence ? (
                  <PinnedReviewInspector
                    sentence={selectedAttentionSentence}
                    onAudition={() => playSentenceAudition(selectedAttentionSentence)}
                    onRestore={() => {
                      const range = sentenceRange(selectedAttentionSentence)
                      if (range) restoreAiCutRange(range)
                    }}
                    onCut={() => setSentenceCut(selectedAttentionSentence, true)}
                    onKeep={() => setSentenceCut(selectedAttentionSentence, false)}
                  />
                ) : (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Select a review or restore-marked chunk to pin its rationale here. Playback will
                    not change this panel.
                  </p>
                )}
              </div>

              <div className="rounded-lg border bg-muted/20 p-3 text-xs text-muted-foreground">
                <div className="mb-1 flex items-center gap-2 font-medium text-foreground">
                  {isDirty ? (
                    <span className="inline-flex items-center gap-1 text-changed">
                      <Save className="size-3" />
                      {saveStateText}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-keep">
                      <Check className="size-3" />
                      {saveStateText}
                    </span>
                  )}
                </div>
                <p>
                  {isDirty
                    ? `Draft autosaved locally${lastDraftAt ? ` at ${new Date(lastDraftAt).toLocaleTimeString()}` : ''}. Press ⌘S to persist.`
                    : lastSavedAt
                      ? `Persisted at ${new Date(lastSavedAt).toLocaleTimeString()}.`
                      : 'Current decisions match the saved review.'}
                </p>
              </div>

              <Separator />

              <div className="flex flex-col gap-2 text-xs text-muted-foreground">
                <span className="flex items-center gap-2">
                  <i className="inline-block h-3 w-4.5 rounded-sm bg-foreground" /> kept
                </span>
                <span className="flex items-center gap-2">
                  <i className="inline-block h-3 w-4.5 rounded-sm bg-cut opacity-40" /> cut
                </span>
                <span className="flex items-center gap-2">
                  <i className="inline-block h-3 w-4.5 border-b-2 border-dotted border-changed" />{' '}
                  AI suggests keeping
                </span>
                <span className="flex items-center gap-2">
                  <i className="inline-block h-3 w-4.5 border-b-2 border-dotted border-status-yellow" />{' '}
                  low-value · maybe trim
                </span>
                <span className="flex items-center gap-3">
                  <span className="flex items-center gap-1">
                    <i className="inline-block size-2 rounded-full bg-status-yellow" /> review
                  </span>
                  <span className="flex items-center gap-1">
                    <i className="inline-block size-2 rounded-full bg-status-restore" /> restore
                  </span>
                </span>
              </div>
            </div>
          }
          main={
            <ScrollArea className="min-h-0 h-full">
              <article
                aria-label="Transcript editor"
                className="mx-4 my-4 min-h-[calc(100%-2rem)] max-w-4xl rounded-xl border bg-card px-5 py-6 text-lg leading-8 shadow-sm sm:mx-6 sm:my-6 sm:min-h-[calc(100%-3rem)] sm:px-8 sm:py-8"
              >
                {payload.sentences.map((sentence) => {
                  const key = statusKey(sentence.status)
                  const meta = STATUS_META[key]
                  const isAttention = isAttentionStatus(key)
                  const containsActive =
                    activeIdx !== null && sentenceByWord.get(activeIdx)?.idx === sentence.idx
                  const dimmed = focusAttention.value && !isAttention && !containsActive
                  const emphasized = focusAttention.value && isAttention
                  const matchesSearch = searchResultSentenceIds.has(sentence.idx)
                  const isActiveSearchResult = activeSearchResult?.sentence.idx === sentence.idx
                  const paragraph = (
                    <p
                      key={sentence.idx}
                      data-review-status={isAttention ? key : undefined}
                      tabIndex={isAttention ? 0 : undefined}
                      className={cn(
                        'relative mb-5 rounded-md transition-all last:mb-0',
                        isAttention &&
                          'focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring',
                        dimmed && 'opacity-25',
                        emphasized && cn('-mx-2 px-2', meta.emphasis),
                        matchesSearch && 'bg-accent/60 px-2',
                        isActiveSearchResult &&
                          'ring-2 ring-primary/60 ring-offset-2 ring-offset-card',
                      )}
                    >
                      {isAttention && (
                        <span
                          className={cn(
                            'absolute top-[0.7em] -left-3.5 size-2 rounded-full',
                            meta.dot,
                          )}
                          aria-hidden="true"
                        />
                      )}
                      {(sentence.words ?? []).map((word) => (
                        <Word
                          key={word.idx}
                          word={word}
                          isCut={cutSet.has(word.idx)}
                          isSelected={
                            selectionRange !== null &&
                            word.idx >= selectionRange[0] &&
                            word.idx <= selectionRange[1]
                          }
                          isPlaying={word.idx === activeIdx}
                          isCaret={word.idx === focusIdx}
                          isSearchMatch={
                            normalizedSearchQuery.length > 0 &&
                            word.text.toLowerCase().includes(normalizedSearchQuery)
                          }
                          registerRef={wordRefs.current}
                          onPointerDown={(event) => selectWord(word, event)}
                          onPointerEnter={(event) => {
                            if (event.buttons === 1 && anchor !== null) setFocusIdx(word.idx)
                          }}
                          onDoubleClick={(event) => {
                            event.preventDefault()
                            toggleWord(word.idx)
                          }}
                        />
                      ))}
                    </p>
                  )
                  if (!isAttention) return paragraph
                  return (
                    <Tooltip key={sentence.idx}>
                      <TooltipTrigger asChild>{paragraph}</TooltipTrigger>
                      <TooltipContent
                        side="top"
                        align="start"
                        sideOffset={6}
                        className="w-80 max-w-[min(20rem,calc(100vw-2rem))] px-3 py-2 text-left text-pretty"
                      >
                        <SentenceReviewNote sentence={sentence} />
                      </TooltipContent>
                    </Tooltip>
                  )
                })}
              </article>
            </ScrollArea>
          }
        />
      ) : (
        <div className="flex flex-1 items-center justify-center p-12 text-center text-muted-foreground">
          {statusText}
        </div>
      )}

      <footer className="shrink-0 truncate border-t bg-card px-4 py-2 text-sm text-muted-foreground">
        {statusText}
      </footer>
      <KeyboardShortcutDrawer
        open={shortcutsOpen.value}
        onClose={() => shortcutsOpen.setValue(false)}
      />
    </div>
  )
}

function KeyboardShortcutDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        aria-label="Close keyboard shortcuts"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="keyboard-shortcuts-title"
        className="absolute top-0 right-0 flex h-full w-full max-w-md flex-col border-l bg-card shadow-2xl"
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b px-5 py-4">
          <div>
            <h2 id="keyboard-shortcuts-title" className="text-base font-semibold">
              Keyboard Shortcuts
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Fast controls for transcript review, playback, search, and saving.
            </p>
          </div>
          <Button type="button" variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}>
            <X />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <div className="space-y-5">
            {KEYBOARD_SHORTCUT_GROUPS.map((group) => (
              <section key={group.title}>
                <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                  {group.title}
                </h3>
                <div className="divide-y rounded-lg border bg-background">
                  {group.shortcuts.map(([keys, description]) => (
                    <div key={keys} className="grid grid-cols-[7rem_1fr] gap-3 px-3 py-2.5">
                      <kbd className="inline-flex h-fit w-fit max-w-full items-center rounded border bg-muted px-2 py-1 font-mono text-xs font-medium text-foreground">
                        {keys}
                      </kbd>
                      <span className="text-sm leading-6 text-muted-foreground">{description}</span>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      </aside>
    </div>
  )
}

function SentenceReviewNote({ sentence }: { sentence: ReviewSentence }) {
  const key = statusKey(sentence.status)
  const meta = STATUS_META[key]
  const tags = sentence.tags ?? []
  return (
    <div className="text-xs text-background">
      <div className="mb-1.5 flex items-center gap-2">
        <span className={cn('inline-block size-2 rounded-full', meta.dot)} />
        <span className={cn('font-semibold', meta.text)}>{meta.label}</span>
        <span className="ml-auto tabular-nums text-background/70">
          {Math.round(sentence.keep_confidence)}% keep
        </span>
      </div>
      {sentence.rationale ? (
        <p className="leading-relaxed text-background/90">{sentence.rationale}</p>
      ) : (
        <p className="text-background/60">No rationale.</p>
      )}
      {tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded bg-background/15 px-1.5 py-0.5 text-[10px] font-normal text-background/80"
            >
              {tag.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

type PinnedReviewInspectorProps = {
  sentence: ReviewSentence
  onAudition: () => void
  onRestore: () => void
  onCut: () => void
  onKeep: () => void
}

function PinnedReviewInspector({
  sentence,
  onAudition,
  onRestore,
  onCut,
  onKeep,
}: PinnedReviewInspectorProps) {
  const key = statusKey(sentence.status)
  const meta = STATUS_META[key]
  const tags = sentence.tags ?? []
  return (
    <div className="text-xs">
      <div className="mb-2 grid grid-cols-3 gap-2 text-muted-foreground">
        <div className="rounded-md bg-muted/60 p-2">
          <div className={cn('font-semibold tabular-nums', meta.text)}>
            {Math.round(sentence.keep_confidence)}%
          </div>
          <div>keep confidence</div>
        </div>
        <div className="rounded-md bg-muted/60 p-2">
          <div className="font-semibold tabular-nums text-foreground">
            {formatDuration(sentence.end - sentence.start)}
          </div>
          <div>duration</div>
        </div>
        <div className="rounded-md bg-muted/60 p-2">
          <div className="truncate font-semibold text-foreground">
            {labelForToken(sentence.reason || 'unknown')}
          </div>
          <div>reason</div>
        </div>
      </div>

      {sentence.rationale ? (
        <p className="leading-relaxed text-foreground">{sentence.rationale}</p>
      ) : (
        <p className="text-muted-foreground">No rationale from enrichment.</p>
      )}

      {tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {tags.map((tag) => (
            <Badge key={tag} variant="secondary" className="rounded-md text-[10px]">
              {labelForToken(tag)}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button type="button" variant="secondary" size="xs" onClick={onAudition}>
          <Play />
          Audition
        </Button>
        <Button type="button" variant="outline" size="xs" onClick={onRestore}>
          <Undo2 />
          Restore AI cut
        </Button>
        <Button type="button" variant="destructive" size="xs" onClick={onCut}>
          <Scissors />
          Cut chunk
        </Button>
        <Button
          type="button"
          size="xs"
          className="bg-keep text-white hover:bg-keep/90"
          onClick={onKeep}
        >
          <Check />
          Keep chunk
        </Button>
      </div>
    </div>
  )
}

type WordProps = {
  word: ReviewWord
  isCut: boolean
  isSelected: boolean
  isPlaying: boolean
  isCaret: boolean
  isSearchMatch: boolean
  registerRef: Map<number, HTMLSpanElement>
  onPointerDown: (event: PointerEvent) => void
  onPointerEnter: (event: PointerEvent) => void
  onDoubleClick: (event: MouseEvent) => void
}

function Word({
  word,
  isCut,
  isSelected,
  isPlaying,
  isCaret,
  isSearchMatch,
  registerRef,
  onPointerDown,
  onPointerEnter,
  onDoubleClick,
}: WordProps) {
  // AI cut it, but it scores high enough that the human may want to keep it.
  const suggestKeep = !word.ai_kept && isCut && word.keep_score >= SUGGEST_KEEP_THRESHOLD
  // AI kept it, but salience is low enough that it's a candidate to trim.
  const trimCandidate = word.ai_kept && !isCut && word.keep_score < TRIM_CANDIDATE_THRESHOLD
  return (
    <span
      ref={(element) => {
        if (element) registerRef.set(word.idx, element)
        else registerRef.delete(word.idx)
      }}
      data-word-idx={word.idx}
      data-word-caret={isCaret ? 'true' : undefined}
      className={cn(
        'relative inline-block cursor-text rounded px-0.5 transition-colors select-none hover:bg-muted',
        isCut ? 'text-muted-foreground line-through decoration-cut opacity-40' : 'text-foreground',
        suggestKeep && 'border-b-2 border-dotted border-changed no-underline',
        trimCandidate &&
          'text-muted-foreground underline decoration-dotted decoration-status-yellow underline-offset-4',
        isSearchMatch && 'bg-changed/25 text-foreground opacity-100',
        isSelected && !isPlaying && 'bg-primary/25 opacity-100',
        isPlaying && !isSelected && 'bg-playing/30 text-foreground opacity-100',
        isSelected &&
          isPlaying &&
          'bg-primary/25 text-foreground opacity-100 ring-2 ring-playing/70 ring-offset-1 ring-offset-card',
        isCaret &&
          "before:absolute before:top-0.5 before:bottom-0.5 before:-left-0.5 before:w-0.5 before:animate-pulse before:rounded-full before:bg-primary before:content-['']",
      )}
      title={word.reason ? `${word.reason} · keep score ${word.keep_score.toFixed(2)}` : undefined}
      onPointerDown={onPointerDown}
      onPointerEnter={onPointerEnter}
      onDoubleClick={onDoubleClick}
    >
      {word.text}{' '}
    </span>
  )
}

function DefaultPlaybackRate({ rate }: { rate: number }) {
  const player = Player.usePlayer()
  const duration = Player.usePlayer((state) => state.duration)

  // Apply once the media element is attached (duration becomes known).
  useEffect(() => {
    if (duration <= 0) return
    player.setPlaybackRate(rate)
  }, [player, rate, duration])

  return null
}

type PlaybackSyncProps = {
  words: ReviewWord[]
  cutSpans: Array<[number, number]>
  previewEdit: boolean
  auditionRange: AuditionRange | null
  loopAudition: boolean
  onActive: (idx: number | null) => void
  onAuditionEnd: () => void
}

// Lives inside the Player provider and subscribes to `currentTime` so only this
// tiny component re-renders on every tick — the heavy transcript re-renders only
// when the karaoke-highlighted word actually changes.
function PlaybackSync({
  words,
  cutSpans,
  previewEdit,
  auditionRange,
  loopAudition,
  onActive,
  onAuditionEnd,
}: PlaybackSyncProps) {
  const player = Player.usePlayer()
  const media = Player.useMedia()
  const currentTime = Player.usePlayer((state) => state.currentTime)
  const duration = Player.usePlayer((state) => state.duration)
  const paused = Player.usePlayer((state) => state.paused)
  const lastActive = useRef<number | null>(null)

  // Frame-accurate skip: poll the media element's own clock every frame and jump
  // the playhead synchronously by writing `currentTime` directly. `player.seek()`
  // goes through an async pipeline, so audio keeps flowing until it lands — which
  // let the first cut word leak. A direct assignment takes effect immediately.
  useEffect(() => {
    if (!previewEdit || paused || !isSeekableMedia(media)) return

    let frame = 0
    let pendingTarget: number | null = null
    const skipBeforeCutAudio = () => {
      const now = media.currentTime
      // Once the playhead has reached the seek target, the jump landed.
      if (pendingTarget !== null && now >= pendingTarget - PREVIEW_SKIP_END_EPSILON_SECONDS) {
        pendingTarget = null
      }
      const span = activeCutSpan(cutSpans, now)
      if (span) {
        const target = previewSkipTarget(span[1], duration)
        // Avoid re-issuing the same jump on every frame while the seek settles.
        if (pendingTarget === null || target > pendingTarget) {
          pendingTarget = target
          media.currentTime = target
        }
      } else {
        pendingTarget = null
      }
      frame = requestAnimationFrame(skipBeforeCutAudio)
    }

    frame = requestAnimationFrame(skipBeforeCutAudio)
    return () => cancelAnimationFrame(frame)
  }, [media, duration, paused, previewEdit, cutSpans])

  useEffect(() => {
    if (auditionRange && !paused && currentTime >= auditionRange.end - 0.03) {
      if (loopAudition) {
        void player.seek(auditionRange.start)
      } else {
        player.togglePaused()
        onAuditionEnd()
      }
      return
    }

    if (previewEdit && !paused) {
      const span = activeCutSpan(cutSpans, currentTime)
      if (span) {
        const [, end] = span
        void player.seek(previewSkipTarget(end, duration))
        return
      }
    }

    let active: number | null = null
    for (const word of words) {
      if (currentTime < word.start) break
      if (currentTime <= word.end) {
        active = word.idx
        break
      }
    }
    if (active !== lastActive.current) {
      lastActive.current = active
      onActive(active)
    }
  }, [
    currentTime,
    duration,
    paused,
    previewEdit,
    cutSpans,
    words,
    player,
    auditionRange,
    loopAudition,
    onAuditionEnd,
    onActive,
  ])

  return null
}
