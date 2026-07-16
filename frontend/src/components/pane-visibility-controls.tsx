import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'

import { Button } from '@/components/ui/button'

type PaneVisibilityControlsProps = {
  videoHidden: boolean
  transcriptHidden: boolean
  onVideoHiddenChange: (hidden: boolean) => void
  onTranscriptHiddenChange: (hidden: boolean) => void
}

export function PaneVisibilityControls({
  videoHidden,
  transcriptHidden,
  onVideoHiddenChange,
  onTranscriptHiddenChange,
}: PaneVisibilityControlsProps) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border p-0.5">
      <Button
        size="xs"
        variant={videoHidden ? 'secondary' : 'ghost'}
        aria-label={videoHidden ? 'Show video side' : 'Minimize video side'}
        title={videoHidden ? 'Show video side' : 'Minimize video side'}
        onClick={() => onVideoHiddenChange(!videoHidden)}
      >
        {videoHidden ? <PanelLeftOpen /> : <PanelLeftClose />}
        Video
      </Button>
      <Button
        size="xs"
        variant={transcriptHidden ? 'secondary' : 'ghost'}
        aria-label={transcriptHidden ? 'Show transcript side' : 'Minimize transcript side'}
        title={transcriptHidden ? 'Show transcript side' : 'Minimize transcript side'}
        onClick={() => onTranscriptHiddenChange(!transcriptHidden)}
      >
        Transcript
        {transcriptHidden ? <PanelRightOpen /> : <PanelRightClose />}
      </Button>
    </div>
  )
}
