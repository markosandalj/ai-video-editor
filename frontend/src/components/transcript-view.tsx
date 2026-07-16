import { type RefObject, useRef, useState } from 'react'
import { Crosshair, Search, X } from 'lucide-react'
import { useEventCallback } from 'usehooks-ts'

import type { ReviewSentence } from '@/api'
import { Button } from '@/components/ui/button'
import { Word } from '@/components/word'
import type { WordStatus } from '@/lib/cut-ranges'
import type { EditorSelection } from '@/hooks/use-editor-selection'

type TranscriptViewProps = {
  sentences: ReviewSentence[]
  wordStatus: Map<number, WordStatus>
  selection: EditorSelection
  activeIdx: number | null
  wordRefs: RefObject<Map<number, HTMLSpanElement>>
  scrollRef: RefObject<HTMLDivElement | null>
  follow: boolean
  onToggleFollow: () => void
  onManualScroll: () => void
}

// Presentational transcript. All editing lives in `selection`; this renders words,
// routes their pointer events, and hosts the tucked-away search field.
export function TranscriptView({
  sentences,
  wordStatus,
  selection,
  activeIdx,
  wordRefs,
  scrollRef,
  follow,
  onToggleFollow,
  onManualScroll,
}: TranscriptViewProps) {
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const query = searchQuery.trim().toLowerCase()

  const openSearch = useEventCallback(() => {
    setSearchOpen(true)
    requestAnimationFrame(() => searchInputRef.current?.focus())
  })
  const closeSearch = useEventCallback(() => {
    setSearchOpen(false)
    setSearchQuery('')
  })

  const { selectionRange, caretIdx } = selection

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-card/60 px-4 py-2">
        <p className="truncate text-xs text-muted-foreground">
          {selection.hasSelection
            ? `${selectionRange![1] - selectionRange![0] + 1} word${selectionRange![1] === selectionRange![0] ? '' : 's'} selected · ⌫ cut · ⏎ keep · ⌘C copy`
            : 'Click a word to select it · drag or ⇧-click to extend · X cuts'}
        </p>
        <div className="flex items-center gap-1">
          <Button
            size="icon-sm"
            variant={follow ? 'secondary' : 'ghost'}
            aria-pressed={follow}
            onClick={onToggleFollow}
            aria-label="Follow playback in transcript"
            title="Follow playback in transcript"
          >
            <Crosshair />
          </Button>
          {searchOpen ? (
            <>
              <Search className="size-3.5 shrink-0 text-muted-foreground" />
              <input
                ref={searchInputRef}
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter')
                    selection.findMatchesJump(searchQuery, event.shiftKey ? -1 : 1)
                  if (event.key === 'Escape') closeSearch()
                }}
                placeholder="Find in transcript"
                className="h-7 w-44 rounded-md border bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Close search"
                onClick={closeSearch}
              >
                <X />
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Find in transcript"
              onClick={openSearch}
            >
              <Search />
            </Button>
          )}
        </div>
      </div>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto"
        onWheel={onManualScroll}
        onTouchMove={onManualScroll}
      >
        <article
          aria-label="Transcript editor"
          className="mx-auto my-6 max-w-3xl px-6 text-lg leading-8"
        >
          {sentences.map((sentence) => (
            <p key={sentence.idx} className="relative mb-5 rounded-md last:mb-0">
              {(sentence.words ?? []).map((word) => (
                <Word
                  key={word.idx}
                  idx={word.idx}
                  text={word.text}
                  isCut={(wordStatus.get(word.idx) ?? 'kept') === 'cut'}
                  isPartialCut={(wordStatus.get(word.idx) ?? 'kept') === 'partial'}
                  isSelected={
                    selectionRange !== null &&
                    word.idx >= selectionRange[0] &&
                    word.idx <= selectionRange[1]
                  }
                  isPlaying={word.idx === activeIdx}
                  isCaret={word.idx === caretIdx}
                  isSearchMatch={query.length > 0 && word.text.toLowerCase().includes(query)}
                  registerRef={wordRefs.current}
                  onPointerDown={(idx, event) => {
                    if (event.shiftKey) selection.extendTo(idx)
                    else selection.placeCaret(idx, word.start)
                  }}
                  onPointerEnter={(idx, event) => {
                    if (event.buttons === 1) selection.extendTo(idx)
                  }}
                  onDoubleClick={(idx) => {
                    // Native convention: double-click selects the word. Cutting is an
                    // explicit action (X / ⌫), never an accidental double-click.
                    selection.placeCaret(idx, null)
                  }}
                />
              ))}
            </p>
          ))}
        </article>
      </div>
    </div>
  )
}
