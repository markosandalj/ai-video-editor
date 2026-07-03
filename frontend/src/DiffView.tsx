import { useEffect, useMemo, useRef, useState } from 'react'
import { Video, VideoSkin } from '@videojs/react/video'
import { useEventCallback, useEventListener } from 'usehooks-ts'

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
import { ViewSwitch, type AppView } from '@/components/view-switch'
import { useDiff } from '@/api'
import type { DiffSentence, DiffWord } from '@/api/diff'
import type { VideoSummary } from '@/api/videos'
import { formatDuration, formatTimestamp } from '@/lib/format'
import { DEFAULT_PLAYBACK_RATE, Player } from '@/lib/player'
import { cn } from '@/lib/utils'

// Which edit's cuts to strike through. "diff" overlays both at once.
type Mode = 'diff' | 'human' | 'pipeline'

type DiffViewProps = {
  videoId: string
  videos: VideoSummary[]
  message: string
  onSelect: (id: string) => void
  view: AppView
  onViewChange: (v: AppView) => void
}

const MODES: { value: Mode; label: string }[] = [
  { value: 'diff', label: 'Diff' },
  { value: 'human', label: 'Human edit' },
  { value: 'pipeline', label: 'Pipeline' },
]

export function DiffView({
  videoId,
  videos,
  message,
  onSelect,
  view,
  onViewChange,
}: DiffViewProps) {
  const player = Player.usePlayer()
  const diff = useDiff(videoId)
  const payload = diff.data ?? null
  const hasGt = payload?.summary.has_ground_truth ?? false

  const [mode, setMode] = useState<Mode>('diff')
  const [activeGid, setActiveGid] = useState<number | null>(null)
  const wordRefs = useRef(new Map<number, HTMLSpanElement>())

  // Without ground truth only the pipeline edit is meaningful. Gate on a loaded
  // payload so we don't flip away from "Diff" merely because data is in flight.
  useEffect(() => {
    if (payload && !hasGt && mode !== 'pipeline') setMode('pipeline')
  }, [payload, hasGt, mode])

  // Flat word list (for the karaoke active-word finder) + per-sentence base index.
  const { flatWords, sentenceStartGid } = useMemo(() => {
    const flat: { gid: number; start: number; end: number }[] = []
    const starts: number[] = []
    let gid = 0
    if (payload) {
      for (const s of payload.sentences) {
        starts.push(gid)
        for (const w of s.words) {
          flat.push({ gid, start: w.start, end: w.end })
          gid++
        }
      }
    }
    return { flatWords: flat, sentenceStartGid: starts }
  }, [payload])

  const disagreements = useMemo(
    () => (payload ? payload.sentences.filter((s) => s.pipeline_kept !== s.human_kept) : []),
    [payload],
  )

  const stats = useMemo(() => {
    if (!payload) return null
    let pKept = 0
    let hKept = 0
    let raw = 0
    for (const s of payload.sentences) {
      for (const w of s.words) {
        const d = Math.max(0, w.end - w.start)
        raw += d
        if (w.pipeline_kept) pKept += d
        if (w.human_kept) hKept += d
      }
    }
    return { pKept, hKept, raw }
  }, [payload])

  const seekTo = useEventCallback((seconds: number, play = true) => {
    void player.seek(seconds)
    if (play) void player.play()
  })

  const scrollToGid = useEventCallback((gid: number) => {
    wordRefs.current.get(gid)?.scrollIntoView({ block: 'center' })
  })

  const jumpToNextDisagreement = useEventCallback(() => {
    if (!payload || disagreements.length === 0) return
    const t = player.currentTime ?? 0
    const next = disagreements.find((s) => s.start > t + 0.05) ?? disagreements[0]
    seekTo(next.start)
    const gid = sentenceStartGid[next.idx]
    if (gid !== undefined) scrollToGid(gid)
  })

  const handleKey = useEventCallback((event: KeyboardEvent) => {
    const tag = document.activeElement?.tagName.toLowerCase() ?? ''
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return
    if (document.activeElement?.getAttribute('role') === 'combobox') return
    if (!payload) return
    if (event.key === ' ') {
      event.preventDefault()
      player.togglePaused()
    } else if (event.key === 'd' || event.key === 'D') {
      event.preventDefault()
      jumpToNextDisagreement()
    }
  })
  useEventListener('keydown', handleKey)

  const statusText = diff.isLoading
    ? 'Loading diff…'
    : diff.error
      ? diff.error.message
      : payload
        ? `${disagreements.length} sentence disagreement${disagreements.length === 1 ? '' : 's'} · press D to jump`
        : message

  const s = payload?.summary

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
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex items-center gap-0.5 rounded-md border p-0.5">
          {MODES.map((m) => (
            <Button
              key={m.value}
              size="xs"
              variant={mode === m.value ? 'secondary' : 'ghost'}
              disabled={!hasGt && m.value !== 'pipeline'}
              onClick={() => setMode(m.value)}
            >
              {m.label}
            </Button>
          ))}
        </div>

        {s && (
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            {!hasGt && (
              <Badge variant="outline" className="border-status-yellow/50 text-status-yellow">
                no human edit
              </Badge>
            )}
            <Badge variant="outline" className="border-keep/40 text-keep">
              {s.agree_keep} both keep
            </Badge>
            <Badge variant="outline" className="border-cut/50 text-cut">
              {s.pipeline_only_cut} over-cut
            </Badge>
            <Badge variant="outline" className="border-changed/60 text-changed">
              {s.human_only_cut} missed cut
            </Badge>
            <Badge variant="secondary">{s.agree_cut} both cut</Badge>
          </div>
        )}
      </header>

      {payload ? (
        <ResizableSplit
          storageKey="diff-sidebar-width"
          sidebar={
            <div className="flex flex-col gap-3 p-4">
              <div className="overflow-hidden rounded-xl bg-black [&_.media-button--pip]:hidden [&_video]:w-full">
                <VideoSkin>
                  <Video src={`/media/${payload.video.id}`} playsInline />
                </VideoSkin>
              </div>

              <DiffPlayback words={flatWords} onActive={setActiveGid} />

              <Button
                variant="secondary"
                size="sm"
                onClick={jumpToNextDisagreement}
                disabled={disagreements.length === 0}
              >
                Next disagreement (D)
              </Button>

              {stats && (
                <div className="rounded-lg border bg-card p-3 text-xs">
                  <Row label="Raw" words={s?.raw_words ?? 0} dur={stats.raw} />
                  <Row
                    label="Human edit"
                    words={s?.human_kept_words ?? 0}
                    dur={stats.hKept}
                    total={stats.raw}
                    disabled={!hasGt}
                  />
                  <Row
                    label="Pipeline"
                    words={s?.pipeline_kept_words ?? 0}
                    dur={stats.pKept}
                    total={stats.raw}
                  />
                </div>
              )}

              <Separator />

              <Legend mode={mode} />
            </div>
          }
          main={
            <ScrollArea className="min-h-0 h-full">
              <div className="px-6 py-6 pb-28 text-lg leading-loose">
                {payload.sentences.map((sentence) => (
                  <SentenceRow
                    key={sentence.idx}
                    sentence={sentence}
                    mode={mode}
                    baseGid={sentenceStartGid[sentence.idx] ?? 0}
                    activeGid={activeGid}
                    registerRef={wordRefs.current}
                    onSeek={seekTo}
                  />
                ))}
              </div>
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

function Row({
  label,
  words,
  dur,
  total,
  disabled,
}: {
  label: string
  words: number
  dur: number
  total?: number
  disabled?: boolean
}) {
  const pct = total && total > 0 ? Math.round((dur / total) * 100) : null
  return (
    <div className={cn('flex items-center justify-between py-0.5', disabled && 'opacity-40')}>
      <span className="font-medium">{label}</span>
      <span className="tabular-nums text-muted-foreground">
        {disabled
          ? '—'
          : `${words} words · ${formatDuration(dur)}${pct !== null ? ` · ${pct}%` : ''}`}
      </span>
    </div>
  )
}

// ---- sentence + word rendering -------------------------------------------

// Left-border stripe communicating the sentence-level call for the active mode.
function sentenceStripe(sentence: DiffSentence, mode: Mode): string {
  if (mode === 'diff') {
    const { pipeline_kept: p, human_kept: h } = sentence
    if (p && h) return 'border-l-keep/30'
    if (!p && !h) return 'border-l-border'
    if (!p && h) return 'border-l-cut' // we over-cut (removed human-kept content)
    return 'border-l-changed' // human cut, we kept (missed cut)
  }
  const kept = mode === 'human' ? sentence.human_kept : sentence.pipeline_kept
  return kept ? 'border-l-keep/30' : 'border-l-cut/60'
}

function SentenceRow({
  sentence,
  mode,
  baseGid,
  activeGid,
  registerRef,
  onSeek,
}: {
  sentence: DiffSentence
  mode: Mode
  baseGid: number
  activeGid: number | null
  registerRef: Map<number, HTMLSpanElement>
  onSeek: (seconds: number, play?: boolean) => void
}) {
  const disagreement = sentence.pipeline_kept !== sentence.human_kept
  return (
    <div
      className={cn('mb-1 flex gap-2 rounded-r border-l-4 pl-2', sentenceStripe(sentence, mode))}
    >
      <div className="flex shrink-0 items-start gap-1 pt-2">
        <Button
          variant="ghost"
          size="xs"
          className="font-mono text-xs text-muted-foreground tabular-nums"
          onClick={() => onSeek(sentence.start, false)}
        >
          {formatTimestamp(sentence.start)}
        </Button>
      </div>
      <p className="flex-1">
        {mode === 'diff' && disagreement && (
          <span
            className={cn(
              'mr-1 inline-flex items-center rounded px-1.5 py-0.5 align-middle text-[10px] font-semibold',
              sentence.pipeline_kept ? 'bg-changed/15 text-changed' : 'bg-cut/15 text-cut',
            )}
          >
            {sentence.pipeline_kept ? 'missed cut' : 'over-cut'}
          </span>
        )}
        {sentence.words.map((word, pos) => {
          const gid = baseGid + pos
          return (
            <DiffWordSpan
              key={gid}
              word={word}
              mode={mode}
              isActive={gid === activeGid}
              registerRef={registerRef}
              gid={gid}
              onSeek={onSeek}
            />
          )
        })}
      </p>
    </div>
  )
}

function wordClassName(word: DiffWord, mode: Mode): { struck: boolean; tone: string } {
  const p = word.pipeline_kept
  const h = word.human_kept
  if (mode === 'pipeline') {
    return { struck: !p, tone: !p ? 'text-cut/70 decoration-cut' : 'text-foreground' }
  }
  if (mode === 'human') {
    return { struck: !h, tone: !h ? 'text-cut/70 decoration-cut' : 'text-foreground' }
  }
  // diff
  if (p && h) return { struck: false, tone: 'text-foreground' }
  if (!p && !h)
    return { struck: true, tone: 'text-muted-foreground/50 decoration-muted-foreground' }
  if (!p && h) return { struck: true, tone: 'text-cut decoration-cut' } // over-cut
  return { struck: true, tone: 'text-changed decoration-changed' } // missed cut
}

function DiffWordSpan({
  word,
  mode,
  isActive,
  registerRef,
  gid,
  onSeek,
}: {
  word: DiffWord
  mode: Mode
  isActive: boolean
  registerRef: Map<number, HTMLSpanElement>
  gid: number
  onSeek: (seconds: number, play?: boolean) => void
}) {
  const { struck, tone } = wordClassName(word, mode)
  return (
    <span
      ref={(element) => {
        if (element) registerRef.set(gid, element)
        else registerRef.delete(gid)
      }}
      className={cn(
        'cursor-pointer rounded px-0.5 transition-colors select-none hover:bg-muted',
        struck && 'line-through',
        tone,
        isActive && 'bg-playing/30 text-foreground no-underline opacity-100',
      )}
      onPointerDown={() => onSeek(word.start)}
    >
      {word.text}{' '}
    </span>
  )
}

function Legend({ mode }: { mode: Mode }) {
  if (mode === 'diff') {
    return (
      <div className="flex flex-col gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-foreground" /> both keep
        </span>
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-cut" /> over-cut · we removed, human
          kept
        </span>
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-changed" /> missed cut · human removed,
          we kept
        </span>
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-muted-foreground/50" /> both cut
        </span>
        <span className="pt-1 leading-relaxed">
          Words struck through were removed by that editor. Stripe colour on the left marks the
          sentence-level call.
        </span>
      </div>
    )
  }
  const who = mode === 'human' ? 'the human editor' : 'our pipeline'
  return (
    <div className="flex flex-col gap-2 text-xs text-muted-foreground">
      <span className="flex items-center gap-2">
        <i className="inline-block h-3 w-4.5 rounded-sm bg-foreground" /> kept by {who}
      </span>
      <span className="flex items-center gap-2">
        <i className="inline-block h-3 w-4.5 rounded-sm bg-cut/70" /> removed by {who}
      </span>
      <span className="pt-1 leading-relaxed">
        Showing the {mode === 'human' ? 'manual baseline' : 'pipeline'} edit over the raw
        transcript. Switch to “Diff” to see both at once.
      </span>
    </div>
  )
}

// Subscribes to playback time so only this tiny node re-renders each tick; the
// heavy transcript re-renders only when the highlighted word actually changes.
function DiffPlayback({
  words,
  onActive,
}: {
  words: { gid: number; start: number; end: number }[]
  onActive: (gid: number | null) => void
}) {
  const player = Player.usePlayer()
  const currentTime = Player.usePlayer((state) => state.currentTime)
  const duration = Player.usePlayer((state) => state.duration)
  const last = useRef<number | null>(null)

  useEffect(() => {
    if (duration > 0) player.setPlaybackRate(DEFAULT_PLAYBACK_RATE)
  }, [player, duration])

  useEffect(() => {
    let active: number | null = null
    for (const w of words) {
      if (currentTime < w.start) break
      if (currentTime <= w.end) {
        active = w.gid
        break
      }
    }
    if (active !== last.current) {
      last.current = active
      onActive(active)
    }
  }, [currentTime, words, onActive])

  return null
}
