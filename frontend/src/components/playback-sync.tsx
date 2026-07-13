import { useEffect, useRef } from 'react'

import type { ReviewWord } from '@/api'
import { Player } from '@/lib/player'
import {
  activeCutSpan,
  previewSkipTarget,
  PREVIEW_SKIP_END_EPSILON_SECONDS,
} from '@/lib/review-model'

type SeekableMedia = {
  currentTime: number
  muted?: boolean
  addEventListener?: (type: string, listener: () => void) => void
  removeEventListener?: (type: string, listener: () => void) => void
}

function isSeekableMedia(media: unknown): media is SeekableMedia {
  return (
    typeof media === 'object' &&
    media !== null &&
    'currentTime' in media &&
    typeof (media as { currentTime?: unknown }).currentTime === 'number'
  )
}

export type AuditionRange = {
  start: number
  end: number
  label: string
}

type PlaybackSyncProps = {
  words: ReviewWord[]
  cutSpans: Array<[number, number]>
  previewEdit: boolean
  auditionRange: AuditionRange | null
  loopAudition: boolean
  // While the reviewer is editing on the timeline (dragging, or a pending
  // selection is live), the skip loop stands down so the playhead can't jump
  // out of the region being edited.
  suspendPreview: boolean
  onActive: (idx: number | null) => void
  onAuditionEnd: () => void
}

// Binary-search the sorted word list for the one under the playhead. Replaces the
// per-frame linear scan the old editor did on every karaoke tick.
function findActiveWord(words: ReviewWord[], t: number): number | null {
  let lo = 0
  let hi = words.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const word = words[mid]
    if (t < word.start) hi = mid - 1
    else if (t > word.end) lo = mid + 1
    else return word.idx
  }
  return null
}

/**
 * Lives inside the Player provider and drives two things off the media clock:
 * karaoke highlighting, and — when previewing — skipping over cut regions.
 *
 * The skip has one owner (this rAF loop) rather than the two competing ones the
 * old editor ran. Audio is muted for the duration of each jump: muting is
 * synchronous, but `currentTime =` is not, so without it the tail of a cut word
 * leaks while the seek settles. The loop stands down entirely while auditioning,
 * so "preview edit" no longer skips through the very material being auditioned.
 */
export function PlaybackSync({
  words,
  cutSpans,
  previewEdit,
  auditionRange,
  loopAudition,
  suspendPreview,
  onActive,
  onAuditionEnd,
}: PlaybackSyncProps) {
  const player = Player.usePlayer()
  const media = Player.useMedia()
  const currentTime = Player.usePlayer((state) => state.currentTime)
  const duration = Player.usePlayer((state) => state.duration)
  const paused = Player.usePlayer((state) => state.paused)
  const lastActive = useRef<number | null>(null)

  useEffect(() => {
    const auditioning = auditionRange !== null
    if (!previewEdit || paused || auditioning || suspendPreview || !isSeekableMedia(media)) return

    let frame = 0
    let pendingTarget: number | null = null
    let mutedByUs = false
    let restoreMuted = false
    const supportsSeekedEvent =
      typeof media.addEventListener === 'function' &&
      typeof media.removeEventListener === 'function'

    const restoreAudio = () => {
      if (mutedByUs) {
        media.muted = restoreMuted
        mutedByUs = false
      }
    }

    const onSeeked = () => {
      if (pendingTarget === null) return
      pendingTarget = null
      restoreAudio()
    }

    if (supportsSeekedEvent) media.addEventListener?.('seeked', onSeeked)

    const tick = () => {
      const now = media.currentTime
      if (
        pendingTarget !== null &&
        !supportsSeekedEvent &&
        now >= pendingTarget - PREVIEW_SKIP_END_EPSILON_SECONDS
      ) {
        pendingTarget = null
        restoreAudio()
      }
      if (pendingTarget !== null) {
        frame = requestAnimationFrame(tick)
        return
      }
      const span = activeCutSpan(cutSpans, now)
      if (span) {
        if (!mutedByUs) {
          restoreMuted = media.muted ?? false
          media.muted = true
          mutedByUs = true
        }
        const target = previewSkipTarget(span[1], duration)
        if (pendingTarget === null || target > pendingTarget) {
          pendingTarget = target
          media.currentTime = target
        }
      } else {
        restoreAudio()
      }
      frame = requestAnimationFrame(tick)
    }

    frame = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frame)
      if (supportsSeekedEvent) media.removeEventListener?.('seeked', onSeeked)
      restoreAudio()
    }
  }, [media, duration, paused, previewEdit, cutSpans, auditionRange, suspendPreview])

  // Karaoke highlight + audition boundary handling.
  useEffect(() => {
    if (auditionRange && !paused && currentTime >= auditionRange.end - 0.03) {
      if (loopAudition) void player.seek(auditionRange.start)
      else {
        player.togglePaused()
        onAuditionEnd()
      }
      return
    }

    const active = findActiveWord(words, currentTime)
    if (active !== lastActive.current) {
      lastActive.current = active
      onActive(active)
    }
  }, [currentTime, paused, words, player, auditionRange, loopAudition, onAuditionEnd, onActive])

  return null
}
