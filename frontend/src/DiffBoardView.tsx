import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { ExternalLink, LayoutGrid, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useLocalStorage } from 'usehooks-ts'

import { useDiffs, useVideos } from '@/api'
import type { DiffPayload } from '@/api/diff'
import type { VideoSummary } from '@/api/videos'
import { DiffTranscript } from '@/components/diff-transcript'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { videoPath } from '@/lib/routes'
import { cn } from '@/lib/utils'

type Pos = { x: number; y: number }

type DragState =
  | {
      kind: 'card'
      id: string
      originX: number
      originY: number
      pointerX: number
      pointerY: number
    }
  | { kind: 'pan'; originX: number; originY: number; pointerX: number; pointerY: number }
  | null

const SUBJECTS = ['all', 'fizika', 'kemija', 'hrvatski', 'engleski', 'test'] as const
const CARD_W = 420
const CARD_H = 560
const COL_GAP = 24
const ROW_GAP = 24

function subjectOf(id: string): string {
  if (id.startsWith('test-')) return 'test'
  const match = /^([a-z]+)/.exec(id)
  return match?.[1] ?? 'other'
}

function defaultPositions(videos: VideoSummary[]): Record<string, Pos> {
  const columns = ['fizika', 'kemija', 'hrvatski', 'engleski', 'test', 'other']
  const buckets = Object.fromEntries(columns.map((c) => [c, [] as string[]])) as Record<
    string,
    string[]
  >
  for (const video of videos) {
    const subject = subjectOf(video.id)
    ;(buckets[subject] ?? buckets.other).push(video.id)
  }
  const positions: Record<string, Pos> = {}
  columns.forEach((subject, col) => {
    buckets[subject].forEach((id, row) => {
      positions[id] = {
        x: col * (CARD_W + COL_GAP),
        y: row * (CARD_H + ROW_GAP),
      }
    })
  })
  return positions
}

export function DiffBoardView() {
  const videosQuery = useVideos()
  const videos = useMemo(() => videosQuery.data ?? [], [videosQuery.data])
  const videoIds = useMemo(() => videos.map((v) => v.id), [videos])
  const diffQueries = useDiffs(videoIds)

  const [filter, setFilter] = useState<string>('all')
  const [sort, setSort] = useState<'errors' | 'over' | 'miss' | 'name'>('errors')
  const [pan, setPan] = useState<Pos>({ x: 32, y: 48 })
  const [drag, setDrag] = useState<DragState>(null)
  const [focusedId, setFocusedId] = useState<string | null>(null)
  const [positions, setPositions] = useLocalStorage<Record<string, Pos>>(
    'diff-board-positions-v1',
    {},
  )

  const boardRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    document.title = 'Diff board · AI Video Editor'
  }, [])

  // Seed positions for any new videos without wiping user arrangement.
  useEffect(() => {
    if (videos.length === 0) return
    setPositions((prev) => {
      const seeded = defaultPositions(videos)
      const next = { ...prev }
      let changed = false
      for (const [id, pos] of Object.entries(seeded)) {
        if (!next[id]) {
          next[id] = pos
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [videos, setPositions])

  const cards = useMemo(() => {
    const rows = videos.map((video, index) => {
      const query = diffQueries[index]
      const payload = query?.data ?? null
      const over = payload?.summary.pipeline_only_cut ?? 0
      const miss = payload?.summary.human_only_cut ?? 0
      return {
        video,
        payload,
        isLoading: query?.isPending ?? false,
        error: query?.error?.message ?? null,
        subject: subjectOf(video.id),
        over,
        miss,
        errors: over + miss,
      }
    })
    return rows
      .filter((row) => filter === 'all' || row.subject === filter)
      .sort((a, b) => {
        if (sort === 'name') return a.video.id.localeCompare(b.video.id)
        if (sort === 'over') return b.over - a.over || b.miss - a.miss
        if (sort === 'miss') return b.miss - a.miss || b.over - a.over
        return b.errors - a.errors || a.video.id.localeCompare(b.video.id)
      })
  }, [videos, diffQueries, filter, sort])

  const totals = useMemo(
    () =>
      cards.reduce(
        (acc, card) => {
          acc.over += card.over
          acc.miss += card.miss
          return acc
        },
        { over: 0, miss: 0 },
      ),
    [cards],
  )

  const loaded = diffQueries.filter((q) => q.isSuccess).length
  const loading = diffQueries.some((q) => q.isPending)

  const resetColumns = () => {
    setPositions(defaultPositions(videos))
    setPan({ x: 32, y: 48 })
    setFocusedId(null)
  }

  const packVisible = () => {
    const next = { ...positions }
    cards.forEach((card, index) => {
      const col = index % 3
      const row = Math.floor(index / 3)
      next[card.video.id] = {
        x: col * (CARD_W + COL_GAP),
        y: row * (CARD_H + ROW_GAP),
      }
    })
    setPositions(next)
    setPan({ x: 32, y: 48 })
  }

  useEffect(() => {
    if (!drag) return
    const onMove = (event: globalThis.PointerEvent) => {
      const dx = event.clientX - drag.pointerX
      const dy = event.clientY - drag.pointerY
      if (drag.kind === 'pan') {
        setPan({ x: drag.originX + dx, y: drag.originY + dy })
        return
      }
      setPositions((prev) => ({
        ...prev,
        [drag.id]: { x: drag.originX + dx, y: drag.originY + dy },
      }))
    }
    const onUp = () => setDrag(null)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [drag, setPositions])

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-card px-4 py-2.5">
        <Link to="/" className="text-sm font-extrabold tracking-tight hover:underline">
          AI Video Editor
        </Link>
        <Badge variant="secondary" className="gap-1">
          <LayoutGrid className="size-3.5" />
          Diff board
        </Badge>
        <div className="flex flex-wrap items-center gap-1">
          {SUBJECTS.map((subject) => (
            <Button
              key={subject}
              size="xs"
              variant={filter === subject ? 'secondary' : 'ghost'}
              onClick={() => setFilter(subject)}
            >
              {subject}
            </Button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Button
            size="xs"
            variant={sort === 'errors' ? 'secondary' : 'ghost'}
            onClick={() => setSort('errors')}
          >
            Errors
          </Button>
          <Button
            size="xs"
            variant={sort === 'over' ? 'secondary' : 'ghost'}
            onClick={() => setSort('over')}
          >
            Overcuts
          </Button>
          <Button
            size="xs"
            variant={sort === 'miss' ? 'secondary' : 'ghost'}
            onClick={() => setSort('miss')}
          >
            Misses
          </Button>
          <Button
            size="xs"
            variant={sort === 'name' ? 'secondary' : 'ghost'}
            onClick={() => setSort('name')}
          >
            Name
          </Button>
          <Button size="xs" variant="outline" onClick={packVisible}>
            Pack visible
          </Button>
          <Button size="xs" variant="outline" onClick={resetColumns}>
            <RotateCcw className="size-3.5" />
            Reset columns
          </Button>
        </div>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b px-4 py-2 text-xs">
        <span className="font-medium text-cut">{totals.over} over-cut sentences</span>
        <span className="font-medium text-changed">{totals.miss} missed-cut sentences</span>
        <span className="text-muted-foreground">
          {loaded}/{videos.length} diffs loaded
          {loading ? ' · loading…' : ''}
          {' · '}
          drag card headers to move · drag empty board to pan · same markup as Compare → Diff
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-3 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            <i className="inline-block size-2.5 rounded-sm bg-cut" /> over-cut
          </span>
          <span className="flex items-center gap-1.5">
            <i className="inline-block size-2.5 rounded-sm bg-changed" /> missed cut
          </span>
          <span className="flex items-center gap-1.5">
            <i className="inline-block size-2.5 rounded-sm bg-muted-foreground/50" /> both cut
          </span>
        </span>
      </div>

      <div
        ref={boardRef}
        className={cn(
          'relative min-h-0 flex-1 overflow-hidden bg-muted/20',
          drag?.kind === 'pan' ? 'cursor-grabbing' : 'cursor-grab',
        )}
        onPointerDown={(event) => {
          if (
            event.target === boardRef.current ||
            (event.target as HTMLElement).dataset.board === '1'
          ) {
            setDrag({
              kind: 'pan',
              originX: pan.x,
              originY: pan.y,
              pointerX: event.clientX,
              pointerY: event.clientY,
            })
          }
        }}
      >
        <div
          data-board="1"
          className="absolute"
          style={{
            left: pan.x,
            top: pan.y,
            width: 3200,
            height: 8000,
          }}
        >
          {(['fizika', 'kemija', 'hrvatski', 'engleski', 'test'] as const).map((subject, index) => (
            <div
              key={subject}
              className="pointer-events-none absolute text-xs font-semibold tracking-wide text-muted-foreground uppercase"
              style={{ left: index * (CARD_W + COL_GAP), top: -28, width: CARD_W }}
            >
              {subject}
            </div>
          ))}

          {cards.map((card) => {
            const pos = positions[card.video.id] ?? { x: 0, y: 0 }
            const focused = focusedId === card.video.id
            return (
              <DiffBoardCard
                key={card.video.id}
                video={card.video}
                payload={card.payload}
                isLoading={card.isLoading}
                error={card.error}
                over={card.over}
                miss={card.miss}
                subject={card.subject}
                focused={focused}
                style={{ left: pos.x, top: pos.y, zIndex: focused ? 30 : 1 }}
                onFocus={() => setFocusedId(card.video.id)}
                onDragStart={(clientX, clientY) => {
                  setFocusedId(card.video.id)
                  setDrag({
                    kind: 'card',
                    id: card.video.id,
                    originX: pos.x,
                    originY: pos.y,
                    pointerX: clientX,
                    pointerY: clientY,
                  })
                }}
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}

function DiffBoardCard({
  video,
  payload,
  isLoading,
  error,
  over,
  miss,
  subject,
  focused,
  style,
  onFocus,
  onDragStart,
}: {
  video: VideoSummary
  payload: DiffPayload | null
  isLoading: boolean
  error: string | null
  over: number
  miss: number
  subject: string
  focused: boolean
  style: CSSProperties
  onFocus: () => void
  onDragStart: (clientX: number, clientY: number) => void
}) {
  return (
    <article
      className={cn(
        'absolute flex flex-col overflow-hidden rounded-xl border bg-card shadow-sm',
        focused ? 'border-primary ring-2 ring-primary/20' : 'border-border',
      )}
      style={{ ...style, width: CARD_W, height: CARD_H }}
      onPointerDown={onFocus}
    >
      <header
        className="flex shrink-0 cursor-grab items-start gap-2 border-b bg-card px-3 py-2 active:cursor-grabbing"
        onPointerDown={(event) => {
          event.stopPropagation()
          onDragStart(event.clientX, event.clientY)
        }}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold" title={video.source_name}>
            {video.id}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {subject}
            {payload?.summary.has_ground_truth === false ? ' · no human edit' : ''}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <div className="flex gap-1">
            <Badge variant="outline" className="border-cut/50 text-cut tabular-nums">
              {over}
            </Badge>
            <Badge variant="outline" className="border-changed/60 text-changed tabular-nums">
              {miss}
            </Badge>
          </div>
          <Link
            to={videoPath(video.id, 'compare')}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: 'ghost', size: 'xs' }), 'h-6 px-1.5')}
            onPointerDown={(event) => event.stopPropagation()}
          >
            Compare
            <ExternalLink className="size-3" />
          </Link>
        </div>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        <div className="px-3 py-3">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading full transcript diff…</p>
          ) : error ? (
            <p className="text-sm text-cut">{error}</p>
          ) : payload ? (
            <DiffTranscript sentences={payload.sentences} mode="diff" compact />
          ) : (
            <p className="text-sm text-muted-foreground">No diff payload.</p>
          )}
        </div>
      </ScrollArea>
    </article>
  )
}
