import { type ReactNode, useEffect } from 'react'
import { Eye } from 'lucide-react'
import { Video, VideoSkin } from '@videojs/react/video'

import { Toggle } from '@/components/ui/toggle'
import { PlaybackSync, type AuditionRange } from '@/components/playback-sync'
import type { ReviewSession } from '@/hooks/use-review-session'
import { DEFAULT_PLAYBACK_RATE, Player } from '@/lib/player'

type MediaColumnProps = {
  videoId: string
  session: ReviewSession
  previewEdit: boolean
  onPreviewEditChange: (value: boolean) => void
  auditionRange: AuditionRange | null
  loopAudition: boolean
  suspendPreview: boolean
  onActive: (idx: number | null) => void
  onAuditionEnd: () => void
  children?: ReactNode
}

// The always-mounted left column: the video, the preview-edit toggle, the playback
// engine, and whatever mode-specific controls the caller slots in as children.
// Staying mounted across queue↔editor switches keeps the video from reloading.
export function MediaColumn({
  videoId,
  session,
  previewEdit,
  onPreviewEditChange,
  auditionRange,
  loopAudition,
  suspendPreview,
  onActive,
  onAuditionEnd,
  children,
}: MediaColumnProps) {
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="overflow-hidden rounded-xl bg-black [&_.media-button--pip]:hidden [&_video]:w-full">
        <VideoSkin>
          <Video src={`/media/${videoId}`} playsInline />
        </VideoSkin>
      </div>

      <DefaultPlaybackRate rate={DEFAULT_PLAYBACK_RATE} />

      <PlaybackSync
        words={session.words}
        cutSpans={session.cutSpans}
        previewEdit={previewEdit}
        auditionRange={auditionRange}
        loopAudition={loopAudition}
        suspendPreview={suspendPreview}
        onActive={onActive}
        onAuditionEnd={onAuditionEnd}
      />

      <Toggle
        variant="outline"
        pressed={previewEdit}
        onPressedChange={onPreviewEditChange}
        className="justify-start gap-2"
      >
        <Eye />
        Preview edit
      </Toggle>

      {children}
    </div>
  )
}

function DefaultPlaybackRate({ rate }: { rate: number }) {
  const player = Player.usePlayer()
  const duration = Player.usePlayer((state) => state.duration)
  useEffect(() => {
    if (duration <= 0) return
    player.setPlaybackRate(rate)
  }, [player, rate, duration])
  return null
}
