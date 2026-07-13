import { memo, type MouseEvent, type PointerEvent } from 'react'

import { cn } from '@/lib/utils'

export type WordProps = {
  idx: number
  text: string
  isCut: boolean
  isPartialCut: boolean
  isSelected: boolean
  isPlaying: boolean
  isCaret: boolean
  isSearchMatch: boolean
  registerRef: Map<number, HTMLSpanElement>
  onPointerDown: (idx: number, event: PointerEvent) => void
  onPointerEnter: (idx: number, event: PointerEvent) => void
  onDoubleClick: (idx: number, event: MouseEvent) => void
}

// One transcript word. Memoized on primitive props so a karaoke tick that changes
// a single word's `isPlaying` re-renders only that word, not the whole transcript.
// The old per-word "suggest keep / trim candidate" hints and score tooltips are
// gone — that signal now lives at the sentence level and in the review queue.
export const Word = memo(function Word({
  idx,
  text,
  isCut,
  isPartialCut,
  isSelected,
  isPlaying,
  isCaret,
  isSearchMatch,
  registerRef,
  onPointerDown,
  onPointerEnter,
  onDoubleClick,
}: WordProps) {
  return (
    <span
      ref={(element) => {
        if (element) registerRef.set(idx, element)
        else registerRef.delete(idx)
      }}
      data-word-idx={idx}
      data-word-caret={isCaret ? 'true' : undefined}
      className={cn(
        // `select-none`: the browser's own text selection is disabled so our
        // single selection model owns highlighting. Without it, a native
        // double-click on these inline-block spans selects the whole paragraph.
        // Copy is handled explicitly via ⌘C (see useEditorSelection).
        'relative inline-block cursor-text rounded px-0.5 transition-colors select-none hover:bg-muted',
        isCut && 'text-muted-foreground line-through decoration-cut opacity-40',
        // Partially cut: a free-form edge landed mid-word. Dashed strike, less
        // faded than a full cut, so it reads as "some of this audio is gone".
        isPartialCut && 'text-muted-foreground line-through decoration-dashed decoration-cut/80 opacity-70',
        !isCut && !isPartialCut && 'text-foreground',
        isSearchMatch && 'bg-changed/25 text-foreground opacity-100',
        isSelected && !isPlaying && 'bg-primary/25 opacity-100',
        isPlaying && !isSelected && 'bg-playing/30 text-foreground opacity-100',
        isSelected &&
          isPlaying &&
          'bg-primary/25 text-foreground opacity-100 ring-2 ring-playing/70 ring-offset-1 ring-offset-card',
        isCaret &&
          "before:absolute before:top-0.5 before:bottom-0.5 before:-left-0.5 before:w-0.5 before:animate-pulse before:rounded-full before:bg-primary before:content-['']",
      )}
      onPointerDown={(event) => onPointerDown(idx, event)}
      onPointerEnter={(event) => onPointerEnter(idx, event)}
      onDoubleClick={(event) => onDoubleClick(idx, event)}
    >
      {text}{' '}
    </span>
  )
})
