import { Link } from 'react-router-dom'

import { buttonVariants } from '@/components/ui/button'
import { videoPath, type VideoView } from '@/lib/routes'
import { cn } from '@/lib/utils'

const VIEWS: Array<{ value: VideoView; label: string }> = [
  { value: 'transcript', label: 'Transcript' },
  { value: 'compare', label: 'Compare' },
]

/** Top-level switch between transcript editing and QA comparison. */
export function ViewSwitch({
  videoId,
  view,
  search,
}: {
  videoId: string
  view: VideoView
  search?: string
}) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border p-0.5">
      {VIEWS.map((entry) => (
        <Link
          key={entry.value}
          to={videoPath(videoId, entry.value, search)}
          className={cn(
            buttonVariants({
              size: 'xs',
              variant: view === entry.value ? 'secondary' : 'ghost',
            }),
          )}
        >
          {entry.label}
        </Link>
      ))}
    </div>
  )
}
