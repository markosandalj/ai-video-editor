import { type RefObject, useEffect, useMemo, useRef, useState } from 'react'
import { useHotkeys, type UseHotkeyDefinition } from '@tanstack/react-hotkeys'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Crosshair,
  Maximize2,
  Scissors,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'

import { usePeaks } from '@/api'
import type { ReviewSentence, ReviewWord } from '@/api'
import { Button } from '@/components/ui/button'
import { findCutAt, findCutEdge, snapTime } from '@/lib/cut-ranges'
import { formatDuration, formatTimestamp } from '@/lib/format'
import { Player } from '@/lib/player'
import {
  type AttentionBand,
  type TimeRange,
  clampWindow,
  cutDuration,
  keepDuration,
  samplePeaks,
} from '@/lib/timeline-model'

const MINIMAP_HEIGHT = 46
const DETAIL_HEIGHT = 132
const MIN_SPAN_SECONDS = 2
const RULER_HEIGHT = 14
const EDGE_HIT_PX = 6
const DRAG_THRESHOLD_PX = 3
// Below this zoom, word boundaries are packed tighter than snapping can resolve,
// so word snapping is culled (cut edges / sentences / playhead still snap).
const WORD_SNAP_MIN_PXPS = 80
const NICE_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800]
const NO_PEAKS: number[] = []

type Palette = {
  cut: string
  changed: string
  restore: string
  wave: string
  border: string
  playhead: string
  ring: string
  select: string
}

const FALLBACK_PALETTE: Palette = {
  cut: '#e5484d',
  changed: '#e2a336',
  restore: '#8e4ec6',
  wave: '#8b8b8b',
  border: '#d4d4d4',
  playhead: '#111111',
  ring: '#a1a1a1',
  select: '#3b82f6',
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value))
}

function useElementWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.clientWidth)
    const observer = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? 0))
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return width
}

function usePalette(ref: RefObject<HTMLElement | null>): Palette {
  const [palette, setPalette] = useState<Palette>(FALLBACK_PALETTE)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const read = () => {
      const cs = getComputedStyle(el)
      const pick = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback
      setPalette({
        cut: pick('--cut', FALLBACK_PALETTE.cut),
        changed: pick('--changed', FALLBACK_PALETTE.changed),
        restore: pick('--status-restore', FALLBACK_PALETTE.restore),
        wave: pick('--muted-foreground', FALLBACK_PALETTE.wave),
        border: pick('--border', FALLBACK_PALETTE.border),
        playhead: pick('--foreground', FALLBACK_PALETTE.playhead),
        ring: pick('--ring', FALLBACK_PALETTE.ring),
        select: pick('--primary', FALLBACK_PALETTE.select),
      })
    }
    read()
    const observer = new MutationObserver(read)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [ref])
  return palette
}

function useCanvasLayer(
  ref: RefObject<HTMLCanvasElement | null>,
  width: number,
  height: number,
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void,
  deps: unknown[],
) {
  useEffect(() => {
    const canvas = ref.current
    if (!canvas || width <= 0 || height <= 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)
    draw(ctx, width, height)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, width, height, ...deps])
}

function drawWaveform(
  ctx: CanvasRenderingContext2D,
  height: number,
  samples: number[],
  color: string,
  alpha: number,
) {
  ctx.save()
  ctx.globalAlpha = alpha
  ctx.fillStyle = color
  const mid = height / 2
  for (let x = 0; x < samples.length; x++) {
    const amp = samples[x] * mid * 0.92
    ctx.fillRect(x, mid - amp, 1, Math.max(1, amp * 2))
  }
  ctx.restore()
}

function drawRanges(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  ranges: TimeRange[],
  toX: (t: number) => number,
  color: string,
  fillAlpha: number,
  edges: boolean,
) {
  ctx.save()
  for (const range of ranges) {
    const x0 = clamp(toX(range.start), 0, width)
    const x1 = clamp(toX(range.end), 0, width)
    if (x1 <= 0 || x0 >= width || x1 - x0 < 0.5) continue
    ctx.globalAlpha = fillAlpha
    ctx.fillStyle = color
    ctx.fillRect(x0, 0, x1 - x0, height)
    if (edges) {
      ctx.globalAlpha = 0.9
      ctx.fillRect(x0, 0, 1.5, height)
      ctx.fillRect(x1 - 1.5, 0, 1.5, height)
    }
  }
  ctx.restore()
}

function drawSelection(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  selection: TimeRange | null,
  toX: (t: number) => number,
  color: string,
  handles: boolean,
) {
  if (!selection) return
  const x0 = clamp(toX(selection.start), 0, width)
  const x1 = clamp(toX(selection.end), 0, width)
  ctx.save()
  ctx.globalAlpha = 0.18
  ctx.fillStyle = color
  ctx.fillRect(x0, 0, Math.max(2, x1 - x0), height)
  if (handles) {
    ctx.globalAlpha = 0.95
    ctx.fillRect(x0, 0, 2, height)
    ctx.fillRect(x1 - 2, 0, 2, height)
  }
  ctx.restore()
}

function drawAttention(
  ctx: CanvasRenderingContext2D,
  width: number,
  bands: AttentionBand[],
  toX: (t: number) => number,
  palette: Palette,
  bandHeight: number,
) {
  ctx.save()
  ctx.globalAlpha = 0.85
  for (const band of bands) {
    const x0 = clamp(toX(band.start), 0, width)
    const x1 = clamp(toX(band.end), 0, width)
    if (x1 - x0 < 0.5) continue
    ctx.fillStyle = band.kind === 'restore' ? palette.restore : palette.changed
    ctx.fillRect(x0, 0, Math.max(1, x1 - x0), bandHeight)
  }
  ctx.restore()
}

function drawPlayhead(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  x: number,
  color: string,
) {
  if (x < 0 || x > width) return
  ctx.save()
  ctx.fillStyle = color
  ctx.fillRect(x - 0.75, 0, 1.5, height)
  ctx.beginPath()
  ctx.moveTo(x - 4, 0)
  ctx.lineTo(x + 4, 0)
  ctx.lineTo(x, 5)
  ctx.closePath()
  ctx.fill()
  ctx.restore()
}

function niceStep(span: number, targetTicks: number): number {
  const raw = span / targetTicks
  return NICE_STEPS.find((step) => step >= raw) ?? NICE_STEPS[NICE_STEPS.length - 1]
}

function drawRuler(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  view: TimeRange,
  color: string,
) {
  const span = view.end - view.start
  if (span <= 0) return
  const step = niceStep(span, 6)
  ctx.save()
  ctx.fillStyle = color
  ctx.font = '10px ui-sans-serif, system-ui, sans-serif'
  ctx.textBaseline = 'bottom'
  const first = Math.ceil(view.start / step) * step
  for (let t = first; t <= view.end; t += step) {
    const x = ((t - view.start) / span) * width
    ctx.globalAlpha = 0.25
    ctx.fillRect(x, height - RULER_HEIGHT, 1, 5)
    ctx.globalAlpha = 0.7
    ctx.fillText(formatTimestamp(t), x + 3, height)
  }
  ctx.restore()
}

type DragState =
  | { kind: 'select'; anchor: number }
  | { kind: 'edge'; index: number; edge: 'start' | 'end'; origin: TimeRange[] }

export type TimelineStripProps = {
  videoId: string
  duration: number
  cutRanges: TimeRange[]
  attention: AttentionBand[]
  words: ReviewWord[]
  sentences: ReviewSentence[]
  timeSelection: TimeRange | null
  onTimeSelectionChange: (selection: TimeRange | null) => void
  onCommitCut: (range: TimeRange) => void
  onRestore: (range: TimeRange) => void
  onCommitRanges: (ranges: TimeRange[]) => void
  onAudition: (start: number, end: number, label: string) => void
  onEditingChange: (editing: boolean) => void
  follow: boolean
  onToggleFollow: () => void
  collapsed: boolean
  onToggleCollapsed: () => void
}

/**
 * Collapsible free-form timeline: minimap over a zoomable detail track. Drag to
 * paint a pending cut selection, drag a cut's edge to trim it, click a cut to
 * select it; X cuts / ⏎ restores / L auditions the active selection, i·o set its
 * edges at the playhead. Edges snap to cut/word/sentence/playhead boundaries
 * (Alt disables). The canonical cut ranges are the single source of truth.
 */
export function TimelineStrip({
  videoId,
  duration,
  cutRanges,
  attention,
  words,
  sentences,
  timeSelection,
  onTimeSelectionChange,
  onCommitCut,
  onRestore,
  onCommitRanges,
  onAudition,
  onEditingChange,
  follow,
  onToggleFollow,
  collapsed,
  onToggleCollapsed,
}: TimelineStripProps) {
  const player = Player.usePlayer()
  const currentTime = Player.usePlayer((state) => state.currentTime)
  const paused = Player.usePlayer((state) => state.paused)
  const peaksQuery = usePeaks(videoId)
  const peaks = peaksQuery.data?.peaks ?? NO_PEAKS
  const peaksDuration = peaksQuery.data?.duration || duration

  const containerRef = useRef<HTMLDivElement>(null)
  const width = useElementWidth(containerRef)
  const palette = usePalette(containerRef)
  const cols = Math.max(1, Math.floor(width))

  const [view, setView] = useState<TimeRange>({ start: 0, end: duration })
  useEffect(() => {
    setView({ start: 0, end: duration })
  }, [duration, videoId])

  // Live gesture preview (drawn instead of the committed state during a drag).
  const [dragSelection, setDragSelection] = useState<TimeRange | null>(null)
  const [liveRanges, setLiveRanges] = useState<TimeRange[] | null>(null)
  const dragRef = useRef<DragState | null>(null)
  const movedRef = useRef(false)

  const displayRanges = liveRanges ?? cutRanges
  const activeSelection = dragSelection ?? timeSelection

  const minimapBase = useRef<HTMLCanvasElement>(null)
  const minimapHead = useRef<HTMLCanvasElement>(null)
  const detailBase = useRef<HTMLCanvasElement>(null)
  const detailHead = useRef<HTMLCanvasElement>(null)
  const detailWrap = useRef<HTMLDivElement>(null)

  const minimapSamples = useMemo(
    () => samplePeaks(peaks, peaksDuration, 0, duration, cols),
    [peaks, peaksDuration, duration, cols],
  )
  const detailSamples = useMemo(
    () => samplePeaks(peaks, peaksDuration, view.start, view.end, cols),
    [peaks, peaksDuration, view.start, view.end, cols],
  )

  const wordBoundaries = useMemo(() => {
    const set = new Set<number>()
    for (const word of words) {
      set.add(word.cut_in ?? word.start)
      set.add(word.cut_out ?? word.end)
    }
    return [...set].sort((a, b) => a - b)
  }, [words])
  const sentenceStarts = useMemo(() => sentences.map((s) => s.start), [sentences])

  const minimapToX = (t: number) => (duration > 0 ? (t / duration) * width : 0)
  const detailSpan = view.end - view.start
  const pxPerSecond = detailSpan > 0 ? width / detailSpan : 0
  const detailToX = (t: number) => (detailSpan > 0 ? ((t - view.start) / detailSpan) * width : 0)
  const detailTimeAt = (clientX: number) => {
    const rect = detailWrap.current?.getBoundingClientRect()
    if (!rect || rect.width <= 0) return view.start
    const ratio = clamp(clientX - rect.left, 0, rect.width) / rect.width
    return clamp(view.start + ratio * detailSpan, 0, duration)
  }

  const snapTargets = (excludeCutIndex: number | null, altKey: boolean): number[] => {
    if (altKey) return []
    const targets: number[] = [currentTime]
    cutRanges.forEach((range, index) => {
      if (index !== excludeCutIndex) targets.push(range.start, range.end)
    })
    for (const start of sentenceStarts) if (start >= view.start && start <= view.end) targets.push(start)
    if (pxPerSecond >= WORD_SNAP_MIN_PXPS) {
      for (const boundary of wordBoundaries) {
        if (boundary >= view.start && boundary <= view.end) targets.push(boundary)
      }
    }
    return targets
  }

  // --- minimap (overview) ---
  useCanvasLayer(
    minimapBase,
    width,
    MINIMAP_HEIGHT,
    (ctx, w, h) => {
      drawWaveform(ctx, h, minimapSamples, palette.wave, 0.5)
      drawRanges(ctx, w, h, displayRanges, minimapToX, palette.cut, 0.3, false)
      drawAttention(ctx, w, attention, minimapToX, palette, 3)
      drawSelection(ctx, w, h, activeSelection, minimapToX, palette.select, false)
      if (!collapsed && duration > 0) {
        const vx0 = clamp(minimapToX(view.start), 0, w)
        const vx1 = clamp(minimapToX(view.end), 0, w)
        ctx.save()
        ctx.globalAlpha = 0.12
        ctx.fillStyle = palette.ring
        ctx.fillRect(vx0, 0, Math.max(2, vx1 - vx0), h)
        ctx.globalAlpha = 0.9
        ctx.strokeStyle = palette.ring
        ctx.lineWidth = 1
        ctx.strokeRect(vx0 + 0.5, 0.5, Math.max(2, vx1 - vx0) - 1, h - 1)
        ctx.restore()
      }
    },
    [minimapSamples, displayRanges, attention, activeSelection, palette, duration, collapsed, view.start, view.end, width],
  )
  useCanvasLayer(
    minimapHead,
    width,
    MINIMAP_HEIGHT,
    (ctx, w, h) => drawPlayhead(ctx, w, h, minimapToX(currentTime), palette.playhead),
    [currentTime, duration, palette, width],
  )

  // --- detail track ---
  useCanvasLayer(
    detailBase,
    width,
    DETAIL_HEIGHT,
    (ctx, w, h) => {
      const waveH = h - RULER_HEIGHT
      drawWaveform(ctx, waveH, detailSamples, palette.wave, 0.65)
      drawRanges(ctx, w, waveH, displayRanges, detailToX, palette.cut, 0.24, true)
      drawAttention(ctx, w, attention, detailToX, palette, 4)
      drawSelection(ctx, w, waveH, activeSelection, detailToX, palette.select, true)
      drawRuler(ctx, w, h, view, palette.wave)
    },
    [detailSamples, displayRanges, attention, activeSelection, palette, view.start, view.end, width],
  )
  useCanvasLayer(
    detailHead,
    width,
    DETAIL_HEIGHT,
    (ctx, w, h) => drawPlayhead(ctx, w, h - RULER_HEIGHT, detailToX(currentTime), palette.playhead),
    [currentTime, view.start, view.end, palette, width],
  )

  // Wheel zoom (ctrl/meta) and pan (plain) on the detail track.
  useEffect(() => {
    const el = detailWrap.current
    if (!el || collapsed) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const rect = el.getBoundingClientRect()
      const ratio = rect.width > 0 ? clamp(event.clientX - rect.left, 0, rect.width) / rect.width : 0
      setView((current) => {
        const span = current.end - current.start
        if (event.ctrlKey || event.metaKey) {
          const anchor = current.start + ratio * span
          const factor = event.deltaY > 0 ? 1.2 : 1 / 1.2
          const nextSpan = clamp(span * factor, MIN_SPAN_SECONDS, duration)
          return clampWindow(anchor - ratio * nextSpan, anchor - ratio * nextSpan + nextSpan, duration)
        }
        const delta = (event.deltaX !== 0 ? event.deltaX : event.deltaY) * (span / rect.width)
        return clampWindow(current.start + delta, current.end + delta, duration)
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [duration, collapsed])

  // Follow playback: page the detail window forward so the playhead stays in
  // view. Only while playing — a paused reviewer can pan/zoom freely without the
  // view snapping back — and only when zoomed in enough for it to matter.
  useEffect(() => {
    if (!follow || collapsed || paused || dragRef.current) return
    const span = view.end - view.start
    if (span <= 0 || span >= duration - 0.01) return
    const aheadEdge = view.end - span * 0.12
    if (currentTime >= aheadEdge || currentTime < view.start) {
      const maxStart = Math.max(0, duration - span)
      const nextStart = clamp(currentTime - span * 0.08, 0, maxStart)
      if (Math.abs(nextStart - view.start) > 1e-3) setView({ start: nextStart, end: nextStart + span })
    }
  }, [currentTime, follow, collapsed, paused, duration, view.start, view.end])

  // --- detail pointer gestures ---
  const onDetailPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    const t = detailTimeAt(event.clientX)
    const edge = findCutEdge(cutRanges, t, pxPerSecond, EDGE_HIT_PX)
    movedRef.current = false
    if (edge) {
      dragRef.current = { kind: 'edge', index: edge.index, edge: edge.edge, origin: cutRanges }
      setLiveRanges(cutRanges.map((r) => ({ ...r })))
    } else {
      dragRef.current = { kind: 'select', anchor: t }
      setDragSelection({ start: t, end: t })
    }
    onEditingChange(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onDetailPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const t = detailTimeAt(event.clientX)
    if (drag.kind === 'edge') {
      const snapped = snapTime(t, snapTargets(drag.index, event.altKey), pxPerSecond)
      setLiveRanges(applyEdge(drag.origin, drag.index, drag.edge, snapped))
      movedRef.current = true
    } else {
      const snapped = snapTime(t, snapTargets(null, event.altKey), pxPerSecond)
      setDragSelection({ start: Math.min(drag.anchor, snapped), end: Math.max(drag.anchor, snapped) })
      if (Math.abs(t - drag.anchor) * pxPerSecond > DRAG_THRESHOLD_PX) movedRef.current = true
    }
  }

  const onDetailPointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    dragRef.current = null
    event.currentTarget.releasePointerCapture(event.pointerId)
    onEditingChange(false)
    if (!drag) return
    const t = detailTimeAt(event.clientX)
    if (drag.kind === 'edge') {
      const snapped = snapTime(t, snapTargets(drag.index, event.altKey), pxPerSecond)
      onCommitRanges(applyEdge(drag.origin, drag.index, drag.edge, snapped))
      setLiveRanges(null)
      return
    }
    if (movedRef.current) {
      const snapped = snapTime(t, snapTargets(null, event.altKey), pxPerSecond)
      onTimeSelectionChange({ start: Math.min(drag.anchor, snapped), end: Math.max(drag.anchor, snapped) })
    } else {
      const cutIdx = findCutAt(cutRanges, drag.anchor)
      if (cutIdx >= 0) onTimeSelectionChange(cutRanges[cutIdx])
      else {
        onTimeSelectionChange(null)
        void player.seek(drag.anchor)
      }
    }
    setDragSelection(null)
  }

  // Cursor affordance without re-rendering: resize on an edge, crosshair to select.
  const onDetailHover = (event: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current) return
    const el = detailWrap.current
    if (!el) return
    const t = detailTimeAt(event.clientX)
    if (findCutEdge(cutRanges, t, pxPerSecond, EDGE_HIT_PX)) el.style.cursor = 'col-resize'
    else if (findCutAt(cutRanges, t) >= 0) el.style.cursor = 'pointer'
    else el.style.cursor = 'crosshair'
  }

  // Minimap navigation (expanded) / seek (collapsed).
  const draggingMinimap = useRef(false)
  const onMinimapPointer = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const ratio = rect.width > 0 ? clamp(event.clientX - rect.left, 0, rect.width) / rect.width : 0
    const t = ratio * duration
    if (collapsed) void player.seek(t)
    else {
      const span = view.end - view.start
      setView(clampWindow(t - span / 2, t + span / 2, duration))
    }
  }

  const zoomBy = (factor: number) => {
    setView((current) => {
      const span = current.end - current.start
      const center = (current.start + current.end) / 2
      const nextSpan = clamp(span * factor, MIN_SPAN_SECONDS, duration)
      return clampWindow(center - nextSpan / 2, center + nextSpan / 2, duration)
    })
  }

  // --- keyboard verbs on the active time selection + i/o marks ---
  const hasSelection = timeSelection !== null
  const cutSelection = () => {
    if (timeSelection) onCommitCut(timeSelection)
    onTimeSelectionChange(null)
  }
  const restoreSelection = () => {
    if (timeSelection) onRestore(timeSelection)
    onTimeSelectionChange(null)
  }
  const auditionSelection = () => {
    if (timeSelection) onAudition(timeSelection.start, timeSelection.end, 'selection')
  }
  const markIn = () => {
    const end = timeSelection ? Math.max(currentTime, timeSelection.end) : currentTime
    onTimeSelectionChange({ start: currentTime, end })
  }
  const markOut = () => {
    const start = timeSelection ? Math.min(currentTime, timeSelection.start) : currentTime
    onTimeSelectionChange({ start, end: currentTime })
  }

  const hotkeys: UseHotkeyDefinition[] = [
    { hotkey: 'X', callback: cutSelection, options: { enabled: hasSelection } },
    { hotkey: 'Backspace', callback: cutSelection, options: { enabled: hasSelection } },
    { hotkey: 'Delete', callback: cutSelection, options: { enabled: hasSelection } },
    { hotkey: 'Enter', callback: restoreSelection, options: { enabled: hasSelection } },
    { hotkey: 'L', callback: auditionSelection, options: { enabled: hasSelection } },
    { hotkey: 'Escape', callback: () => onTimeSelectionChange(null), options: { enabled: hasSelection, ignoreInputs: true } },
    { hotkey: 'I', callback: markIn, options: { enabled: duration > 0 } },
    { hotkey: 'O', callback: markOut, options: { enabled: duration > 0 } },
  ]
  useHotkeys(hotkeys, { conflictBehavior: 'allow', preventDefault: true, stopPropagation: true })

  const cutSecs = cutDuration(cutRanges)
  const outputSecs = keepDuration(duration, cutRanges)

  return (
    <div ref={containerRef} className="shrink-0 border-t bg-card">
      <div className="flex items-center gap-2 px-4 py-1.5">
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand timeline' : 'Collapse timeline'}
        >
          {collapsed ? <ChevronRight /> : <ChevronDown />}
        </Button>
        <span className="text-xs font-semibold tracking-tight text-muted-foreground">Timeline</span>
        <span className="text-xs text-muted-foreground">
          {cutRanges.length} cut{cutRanges.length === 1 ? '' : 's'} · −{formatDuration(cutSecs)} ·
          output {formatDuration(outputSecs)}
        </span>

        {timeSelection && (
          <div className="flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/5 px-1.5 py-0.5">
            <span className="text-xs font-medium text-primary">
              {formatTimestamp(timeSelection.start)}–{formatTimestamp(timeSelection.end)}
            </span>
            <Button size="icon-xs" variant="ghost" aria-label="Cut selection (X)" onClick={cutSelection}>
              <Scissors />
            </Button>
            <Button size="icon-xs" variant="ghost" aria-label="Restore selection (Enter)" onClick={restoreSelection}>
              <Check />
            </Button>
          </div>
        )}

        {peaksQuery.isPending && (
          <span className="text-xs text-muted-foreground/70">loading waveform…</span>
        )}
        {!collapsed && (
          <div className="ml-auto flex items-center gap-1">
            <Button
              size="icon-sm"
              variant={follow ? 'secondary' : 'ghost'}
              aria-pressed={follow}
              onClick={onToggleFollow}
              aria-label="Follow playback (F)"
              title="Follow playback (F)"
            >
              <Crosshair />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={() => zoomBy(1 / 1.6)} aria-label="Zoom in">
              <ZoomIn />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={() => zoomBy(1.6)} aria-label="Zoom out">
              <ZoomOut />
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => setView({ start: 0, end: duration })}
              aria-label="Fit whole video"
            >
              <Maximize2 />
            </Button>
          </div>
        )}
      </div>

      <div
        className="relative w-full cursor-pointer touch-none"
        style={{ height: MINIMAP_HEIGHT }}
        onPointerDown={(event) => {
          draggingMinimap.current = true
          event.currentTarget.setPointerCapture(event.pointerId)
          onMinimapPointer(event)
        }}
        onPointerMove={(event) => draggingMinimap.current && onMinimapPointer(event)}
        onPointerUp={(event) => {
          draggingMinimap.current = false
          event.currentTarget.releasePointerCapture(event.pointerId)
        }}
      >
        <canvas ref={minimapBase} className="absolute inset-0 h-full w-full" />
        <canvas ref={minimapHead} className="pointer-events-none absolute inset-0 h-full w-full" />
      </div>

      {!collapsed && (
        <div
          ref={detailWrap}
          className="relative w-full touch-none border-t border-border/50"
          style={{ height: DETAIL_HEIGHT }}
          onPointerDown={onDetailPointerDown}
          onPointerMove={(event) => {
            onDetailHover(event)
            onDetailPointerMove(event)
          }}
          onPointerUp={onDetailPointerUp}
          title="Drag to select · click a cut to select · click empty to seek · ⌘/Ctrl+scroll zoom · X cut · ⏎ restore · i/o mark"
        >
          <canvas ref={detailBase} className="absolute inset-0 h-full w-full" />
          <canvas ref={detailHead} className="pointer-events-none absolute inset-0 h-full w-full" />
        </div>
      )}
    </div>
  )
}

/** Move one edge of range `index`, clamped so it can't cross its own opposite
 *  edge (a zero-width result is dropped by normalize on commit). */
function applyEdge(
  ranges: TimeRange[],
  index: number,
  edge: 'start' | 'end',
  time: number,
): TimeRange[] {
  return ranges.map((range, i) => {
    if (i !== index) return range
    if (edge === 'start') return { start: Math.min(time, range.end), end: range.end }
    return { start: range.start, end: Math.max(time, range.start) }
  })
}
