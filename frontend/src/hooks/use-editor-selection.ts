import { useMemo, useState } from 'react'
import { useHotkeys, type UseHotkeyDefinition } from '@tanstack/react-hotkeys'
import * as R from 'remeda'
import { useEventCallback } from 'usehooks-ts'

import type { ReviewSentence } from '@/api'
import type { ReviewSession } from '@/hooks/use-review-session'
import { Player } from '@/lib/player'
import { needsReview, sentenceRange } from '@/lib/review-model'

type Options = {
  sentences: ReviewSentence[]
  session: ReviewSession
  activeIdx: number | null
  enabled: boolean
  onAudition: (start: number, end: number, label: string) => void
  onStatus: (message: string) => void
  scrollToWord: (idx: number, band?: boolean) => void
  // Fired whenever a word selection is established, so the timeline can drop its
  // own selection — the app keeps exactly one active selection at a time.
  onSelectionPlaced?: () => void
}

/**
 * The transcript editor's selection model and editing actions, lifted out of the
 * view so both the words themselves and the sidebar's Cut/Keep buttons drive one
 * source of truth. Registers the editor-scoped hotkeys while enabled.
 */
export function useEditorSelection({
  sentences,
  session,
  activeIdx,
  enabled,
  onAudition,
  onStatus,
  scrollToWord,
  onSelectionPlaced,
}: Options) {
  const player = Player.usePlayer()
  const { words, wordByIdx, wordIndexByIdx, sentenceByWord, setCut } = session

  const [anchor, setAnchor] = useState<number | null>(null)
  const [focusIdx, setFocusIdx] = useState<number | null>(null)

  const selectionRange = useMemo<[number, number] | null>(() => {
    if (anchor === null || focusIdx === null) return null
    return [Math.min(anchor, focusIdx), Math.max(anchor, focusIdx)]
  }, [anchor, focusIdx])

  const currentIdx = focusIdx ?? anchor ?? activeIdx
  const currentSentence = currentIdx === null ? null : (sentenceByWord.get(currentIdx) ?? null)
  // Any placed selection — including a single clicked word — counts, so the
  // Cut/Keep buttons light up the moment the cursor is on a word.
  const hasSelection = selectionRange !== null
  const isMultiSelection = selectionRange !== null && selectionRange[0] !== selectionRange[1]
  const caretIdx = anchor !== null && anchor === focusIdx ? focusIdx : null

  const clearSelection = useEventCallback(() => {
    setAnchor(null)
    setFocusIdx(null)
  })

  const placeCaret = useEventCallback((idx: number, seekSeconds: number | null) => {
    setAnchor(idx)
    setFocusIdx(idx)
    onSelectionPlaced?.()
    if (seekSeconds !== null) void player.seek(seekSeconds)
  })

  const extendTo = useEventCallback((idx: number) => {
    if (anchor !== null) {
      setFocusIdx(idx)
      onSelectionPlaced?.()
    }
  })

  const selectRange = useEventCallback((range: [number, number], label: string) => {
    setAnchor(range[0])
    setFocusIdx(range[1])
    onSelectionPlaced?.()
    scrollToWord(range[0])
    onStatus(`Selected ${label}.`)
  })

  const moveCaret = useEventCallback((delta: -1 | 1, extend: boolean) => {
    if (words.length === 0) return
    const from = focusIdx ?? anchor ?? activeIdx
    const index = from === null ? -1 : (wordIndexByIdx.get(from) ?? -1)
    const nextWord = words[Math.max(0, Math.min(words.length - 1, index + delta))]
    if (!nextWord) return
    if (extend && anchor !== null) setFocusIdx(nextWord.idx)
    else placeCaret(nextWord.idx, nextWord.start)
    scrollToWord(nextWord.idx)
  })

  const selectCurrentSentence = useEventCallback(() => {
    if (!currentSentence) return
    const range = sentenceRange(currentSentence)
    if (range) selectRange(range, 'sentence')
  })

  const applySelection = useEventCallback((cut: boolean) => {
    if (!selectionRange) {
      if (currentIdx !== null) {
        setCut(currentIdx, currentIdx, cut)
        onStatus(cut ? 'Cut current word.' : 'Kept current word.')
      }
      return
    }
    setCut(selectionRange[0], selectionRange[1], cut)
    const count = selectionRange[1] - selectionRange[0] + 1
    onStatus(`${cut ? 'Cut' : 'Kept'} ${count} word${count === 1 ? '' : 's'}.`)
  })

  const auditionContext = useEventCallback(() => {
    if (selectionRange) {
      const first = wordByIdx.get(selectionRange[0])
      const last = wordByIdx.get(selectionRange[1])
      if (first && last) {
        onAudition(first.start, last.end, `${selectionRange[1] - selectionRange[0] + 1} words`)
        return
      }
    }
    if (currentSentence) onAudition(currentSentence.start, currentSentence.end, 'sentence')
  })

  const jumpToNextFlag = useEventCallback(() => {
    const time = player.currentTime ?? 0
    const next =
      sentences.find((s) => needsReview(s) && s.start > time + 0.05) ?? sentences.find(needsReview)
    if (!next) {
      onStatus('Nothing flagged for review in this lecture.')
      return
    }
    const first = (next.words ?? [])[0]
    void player.seek(next.start)
    if (first) {
      placeCaret(first.idx, null)
      scrollToWord(first.idx, true)
    }
    onStatus('Jumped to the next flagged sentence.')
  })

  const copySelection = useEventCallback(() => {
    if (!selectionRange) return
    const text = words
      .filter((word) => word.idx >= selectionRange[0] && word.idx <= selectionRange[1])
      .map((word) => word.text)
      .join(' ')
      .trim()
    if (!text) return
    void navigator.clipboard?.writeText(text).then(
      () => onStatus('Copied selection.'),
      () => onStatus('Copy failed.'),
    )
  })

  const findMatchesJump = useEventCallback((query: string, direction: 1 | -1) => {
    const q = query.trim().toLowerCase()
    if (!q) return
    const matches = words.filter((word) => word.text.toLowerCase().includes(q))
    if (matches.length === 0) {
      onStatus('No matches.')
      return
    }
    const time = player.currentTime ?? 0
    const target =
      direction === 1
        ? (matches.find((word) => word.start > time + 0.05) ?? matches[0])
        : (R.findLast(matches, (word) => word.start < time - 0.05) ?? matches.at(-1)!)
    placeCaret(target.idx, target.start)
    scrollToWord(target.idx, true)
  })

  const hotkeys: UseHotkeyDefinition[] = [
    { hotkey: 'ArrowLeft', callback: () => moveCaret(-1, false), options: { enabled } },
    { hotkey: 'Shift+ArrowLeft', callback: () => moveCaret(-1, true), options: { enabled } },
    { hotkey: 'ArrowRight', callback: () => moveCaret(1, false), options: { enabled } },
    { hotkey: 'Shift+ArrowRight', callback: () => moveCaret(1, true), options: { enabled } },
    { hotkey: 'S', callback: selectCurrentSentence, options: { enabled } },
    { hotkey: 'X', callback: () => applySelection(true), options: { enabled } },
    { hotkey: 'Backspace', callback: () => applySelection(true), options: { enabled } },
    { hotkey: 'Delete', callback: () => applySelection(true), options: { enabled } },
    { hotkey: 'Enter', callback: () => applySelection(false), options: { enabled } },
    { hotkey: 'L', callback: auditionContext, options: { enabled } },
    { hotkey: 'N', callback: jumpToNextFlag, options: { enabled } },
    { hotkey: 'Mod+C', callback: copySelection, options: { enabled } },
    { hotkey: 'Escape', callback: clearSelection, options: { enabled, ignoreInputs: true } },
  ]

  useHotkeys(hotkeys, { conflictBehavior: 'allow', preventDefault: true, stopPropagation: true })

  return {
    anchor,
    focusIdx,
    caretIdx,
    selectionRange,
    hasSelection,
    isMultiSelection,
    placeCaret,
    extendTo,
    clearSelection,
    applySelection,
    auditionContext,
    selectCurrentSentence,
    jumpToNextFlag,
    findMatchesJump,
  }
}

export type EditorSelection = ReturnType<typeof useEditorSelection>
