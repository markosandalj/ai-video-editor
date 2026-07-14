import type { ReviewWord } from '@/api'

export type TimeRange = { start: number; end: number }

/**
 * Derive display cut ranges from the word-index cut set, mirroring how the
 * backend builds the reviewed EDL: contiguous cut words collapse into one
 * source-time span, using the shared acoustic split points (`cut_in`/`cut_out`)
 * when present so preview, timeline, and render all agree on the boundary.
 *
 * Forward-compatible with the canonical-range migration: the timeline consumes
 * `TimeRange[]`, so when cut ranges become the source of truth only the producer
 * of this array changes, not its consumers.
 */
export function deriveCutRanges(words: ReviewWord[], cutSet: Set<number>): TimeRange[] {
  const ranges: TimeRange[] = []
  let start: number | null = null
  let end = 0
  for (const word of words) {
    if (cutSet.has(word.idx)) {
      const wStart = word.cut_in ?? word.start
      const wEnd = word.cut_out ?? word.end
      if (start === null) {
        start = wStart
        end = wEnd
      } else {
        end = Math.max(end, wEnd)
      }
    } else if (start !== null) {
      ranges.push({ start, end })
      start = null
    }
  }
  if (start !== null) ranges.push({ start, end })
  return ranges
}

/** Total seconds removed by the cut ranges (assumed non-overlapping). */
export function cutDuration(cuts: TimeRange[]): number {
  return cuts.reduce((sum, r) => sum + Math.max(0, r.end - r.start), 0)
}

/** Resulting output length = source duration minus everything cut. */
export function keepDuration(duration: number, cuts: TimeRange[]): number {
  return Math.max(0, duration - cutDuration(cuts))
}

/**
 * Reduce the full waveform to one peak (0..1) per output pixel column across the
 * window `[from, to]`. Each column takes the max of the frames it spans, so
 * transient loud moments stay visible even when zoomed far out.
 */
export function samplePeaks(
  peaks: number[],
  peaksDuration: number,
  from: number,
  to: number,
  columns: number,
): number[] {
  const out = new Array<number>(Math.max(0, columns)).fill(0)
  if (peaks.length === 0 || peaksDuration <= 0 || to <= from || columns <= 0) return out
  const perSecond = peaks.length / peaksDuration
  for (let x = 0; x < columns; x++) {
    const t0 = from + ((to - from) * x) / columns
    const t1 = from + ((to - from) * (x + 1)) / columns
    let i0 = Math.floor(t0 * perSecond)
    let i1 = Math.ceil(t1 * perSecond)
    i0 = Math.max(0, Math.min(peaks.length - 1, i0))
    i1 = Math.max(i0 + 1, Math.min(peaks.length, i1))
    let peak = 0
    for (let i = i0; i < i1; i++) if (peaks[i] > peak) peak = peaks[i]
    out[x] = peak
  }
  return out
}

/** Clamp a zoom window to `[0, duration]` while preserving its span. */
export function clampWindow(start: number, end: number, duration: number): TimeRange {
  const span = Math.min(Math.max(end - start, 0), duration)
  let lo = Math.max(0, Math.min(start, duration - span))
  if (!Number.isFinite(lo)) lo = 0
  return { start: lo, end: lo + span }
}
