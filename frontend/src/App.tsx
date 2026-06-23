import '@videojs/react/video/skin.css'

import { type MouseEvent, type PointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Video, VideoSkin } from '@videojs/react/video'
import { CircleHelp, Eye, Flag, ListFilter, Redo2, Save, Scissors, SkipForward } from 'lucide-react'
import * as R from 'remeda'
import { useBoolean, useEventCallback, useEventListener } from 'usehooks-ts'

import { ResizableSplit } from '@/components/resizable-split'
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

type EditorProps = {
  videoId: string
  videos: VideoSummary[]
  message: string
  onSelect: (id: string) => void
}

export default function App() {
  const videosQuery = useVideos()
  const [selectedId, setSelectedId] = useState('')

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
    <Player.Provider key={selectedId || 'empty'}>
      <Editor
        videoId={selectedId}
        videos={videosQuery.data ?? []}
        message={message}
        onSelect={setSelectedId}
      />
    </Player.Provider>
  )
}

function Editor({ videoId, videos, message, onSelect }: EditorProps) {
  const player = Player.usePlayer()
  const wordRefs = useRef(new Map<number, HTMLSpanElement>())

  const review = useReview(videoId)
  const saveReviewMutation = useSaveReview(videoId)
  const renderReviewMutation = useRenderReview(videoId)
  const payload = review.data ?? null

  const [cutSet, setCutSet] = useState<Set<number>>(new Set())
  const [anchor, setAnchor] = useState<number | null>(null)
  const [focusIdx, setFocusIdx] = useState<number | null>(null)
  const [activeIdx, setActiveIdx] = useState<number | null>(null)
  const [status, setStatus] = useState('')

  const previewEdit = useBoolean(true)
  const focusAttention = useBoolean(false)

  // Seed the cut set from the AI decisions when the payload first loads.
  useEffect(() => {
    if (!payload) return
    const initialCut = new Set<number>()
    for (const sentence of payload.sentences) {
      for (const word of sentence.words ?? []) {
        if (!word.kept) initialCut.add(word.idx)
      }
    }
    setCutSet(initialCut)
  }, [payload])

  const words = useMemo(
    () => (payload ? R.flatMap(payload.sentences, (sentence) => sentence.words ?? []) : []),
    [payload],
  )

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

  const stats = useMemo(() => {
    const [cutWords, keptWords] = R.partition(words, (word) => cutSet.has(word.idx))
    const changed = R.sumBy(words, (word) => (cutSet.has(word.idx) === word.ai_kept ? 1 : 0))
    const keptDuration = R.sumBy(keptWords, (word) => Math.max(0, word.end - word.start))
    return { kept: keptWords.length, cut: cutWords.length, changed, keptDuration }
  }, [words, cutSet])

  // Contiguous runs of currently-cut words → time spans skipped during preview.
  const cutSpans = useMemo(() => {
    const spans: Array<[number, number]> = []
    let start: number | null = null
    let end = 0
    for (const word of words) {
      if (cutSet.has(word.idx)) {
        if (start === null) {
          start = word.start
          end = word.end
        } else {
          end = Math.max(end, word.end)
        }
      } else if (start !== null) {
        spans.push([start, end])
        start = null
      }
    }
    if (start !== null) spans.push([start, end])
    return spans
  }, [words, cutSet])

  const scrollToWord = useEventCallback((idx: number) => {
    wordRefs.current.get(idx)?.scrollIntoView({ block: 'nearest' })
  })

  const seekTo = useEventCallback((seconds: number, play = true) => {
    void player.seek(seconds)
    if (play) void player.play()
  })

  const setCut = useEventCallback((lo: number, hi: number, cut: boolean) => {
    setCutSet((current) => {
      const next = new Set(current)
      for (const i of R.range(lo, hi + 1)) {
        if (cut) next.add(i)
        else next.delete(i)
      }
      return next
    })
  })

  const applySelection = useEventCallback((cut: boolean) => {
    if (!selectionRange) return
    setCut(selectionRange[0], selectionRange[1], cut)
  })

  const toggleWord = useEventCallback((idx: number) => {
    setCut(idx, idx, !cutSet.has(idx))
  })

  const togglePlay = useEventCallback(() => {
    player.togglePaused()
  })

  const jumpToNextAiCut = useEventCallback(() => {
    const time = player.currentTime ?? 0
    let prevAiKept = true
    for (const word of words) {
      const isAiCut = !word.ai_kept
      if (isAiCut && prevAiKept && word.start > time + 0.05) {
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
    if (idx !== null) scrollToWord(idx)
  })

  const saveReview = useEventCallback(async () => {
    if (!payload) return
    setStatus('Saving reviewed edit…')
    try {
      const cutWords = R.pipe(
        Array.from(cutSet),
        R.sortBy((value) => value),
      )
      const saved = await saveReviewMutation.mutateAsync(cutWords)
      setStatus(
        `Saved. Keep ${formatDuration(saved.keep_duration)} · cut ${formatDuration(saved.cut_duration)}.`,
      )
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

  const handleKey = useEventCallback((event: KeyboardEvent) => {
    const element = document.activeElement
    const tag = element?.tagName.toLowerCase() ?? ''
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return
    if (element?.getAttribute('role') === 'combobox') return
    if (!payload) return

    switch (event.key) {
      case ' ':
        event.preventDefault()
        togglePlay()
        break
      case 'Backspace':
      case 'Delete':
        event.preventDefault()
        applySelection(true)
        break
      case 'Enter':
        event.preventDefault()
        applySelection(false)
        break
      case 'Escape':
        setAnchor(null)
        setFocusIdx(null)
        break
      case 'n':
      case 'N':
        event.preventDefault()
        jumpToNextAiCut()
        break
      case 'a':
      case 'A':
        event.preventDefault()
        jumpToNextAttention()
        break
    }
  })

  useEventListener('keydown', handleKey)

  const selectionCount = selectionRange ? selectionRange[1] - selectionRange[0] + 1 : 0

  const statusText = review.isLoading
    ? 'Loading review…'
    : review.error
      ? review.error.message
      : status ||
        (payload ? 'Ready. Click a word to jump · select words and press ⌫ to cut.' : message)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-card px-4 py-2.5">
        <span className="text-sm font-extrabold tracking-tight">AI Video Editor</span>

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
            {attentionTargets.length > 0 && (
              <Badge variant="outline" className="border-status-yellow/50 text-status-yellow">
                {attentionTargets.length} to review
              </Badge>
            )}
            <Badge variant="outline" className="border-keep/40 text-keep">
              {stats.kept} kept
            </Badge>
            <Badge variant="outline" className="border-cut/40 text-cut">
              {stats.cut} cut
            </Badge>
            <Badge variant="outline" className="border-changed/50 text-changed">
              {stats.changed} changed
            </Badge>
            <Badge variant="secondary">keep {formatDuration(stats.keptDuration)}</Badge>
          </div>
        )}

        <div className={cn('flex items-center gap-2', !payload && 'ml-auto')}>
          <Button
            size="sm"
            onClick={saveReview}
            disabled={!payload || saveReviewMutation.isPending}
          >
            <Save />
            {saveReviewMutation.isPending ? 'Saving…' : 'Save'}
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
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label="Keyboard shortcuts">
                <CircleHelp />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-56 text-xs leading-relaxed">
              Click a word to jump · shift-click or drag to select · ⌫ cut · ⏎ keep · double-click
              toggles · Space play/pause · N next AI cut · A next attention item · Esc clear
            </TooltipContent>
          </Tooltip>
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
                onActive={handleActive}
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
                {selectionRange
                  ? `${selectionCount} word${selectionCount === 1 ? '' : 's'} selected`
                  : 'Click a word to jump · shift-click or drag to select a range'}
              </p>

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
                          registerRef={wordRefs.current}
                          onPointerDown={(event) => {
                            if (event.shiftKey && anchor !== null) {
                              setFocusIdx(word.idx)
                              return
                            }
                            setAnchor(word.idx)
                            setFocusIdx(word.idx)
                            seekTo(word.start)
                          }}
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

type WordProps = {
  word: ReviewWord
  isCut: boolean
  isSelected: boolean
  isPlaying: boolean
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
      className={cn(
        'cursor-text rounded px-0.5 transition-colors select-none hover:bg-muted',
        isCut ? 'text-muted-foreground line-through decoration-cut opacity-40' : 'text-foreground',
        suggestKeep && 'border-b-2 border-dotted border-changed no-underline',
        trimCandidate &&
          'text-muted-foreground underline decoration-dotted decoration-status-yellow underline-offset-4',
        isSelected && 'bg-primary/25 opacity-100',
        isPlaying && 'bg-playing/30 text-foreground opacity-100',
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
  onActive: (idx: number | null) => void
}

// Lives inside the Player provider and subscribes to `currentTime` so only this
// tiny component re-renders on every tick — the heavy transcript re-renders only
// when the karaoke-highlighted word actually changes.
function PlaybackSync({ words, cutSpans, previewEdit, onActive }: PlaybackSyncProps) {
  const player = Player.usePlayer()
  const currentTime = Player.usePlayer((state) => state.currentTime)
  const paused = Player.usePlayer((state) => state.paused)
  const lastActive = useRef<number | null>(null)

  useEffect(() => {
    if (previewEdit && !paused) {
      for (const [start, end] of cutSpans) {
        if (currentTime >= start - 0.02 && currentTime < end - 0.05) {
          void player.seek(end)
          return
        }
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
  }, [currentTime, paused, previewEdit, cutSpans, words, player, onActive])

  return null
}
