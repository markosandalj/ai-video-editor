import { type CSSProperties, type PointerEvent, type ReactNode, useRef } from 'react'
import { useEventListener, useLocalStorage, useMediaQuery } from 'usehooks-ts'

import { cn } from '@/lib/utils'

const SIDEBAR_DEFAULT_WIDTH = '50%'
const SIDEBAR_MIN_WIDTH = 300
const SIDEBAR_MAX_FRACTION = 0.75

type ResizableSplitProps = {
  sidebar: ReactNode
  main: ReactNode
  storageKey?: string
}

export function ResizableSplit({
  sidebar,
  main,
  storageKey = 'review-sidebar-width-v2',
}: ResizableSplitProps) {
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [width, setWidth] = useLocalStorage<number | null>(storageKey, null)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const sidebarStyle: CSSProperties | undefined = isDesktop
    ? { width: width ?? SIDEBAR_DEFAULT_WIDTH }
    : undefined
  const containerWidth = containerRef.current?.getBoundingClientRect().width ?? null
  const sidebarPercent = width && containerWidth ? Math.round((width / containerWidth) * 100) : 50

  const stopDragging = () => {
    if (!dragging.current) return
    dragging.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  const onResizeStart = (event: PointerEvent<HTMLDivElement>) => {
    if (!isDesktop) return
    dragging.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  useEventListener('pointermove', (event) => {
    if (!dragging.current || !containerRef.current) return
    const { left, width: currentContainerWidth } = containerRef.current.getBoundingClientRect()
    const max = currentContainerWidth * SIDEBAR_MAX_FRACTION
    setWidth(Math.round(Math.min(max, Math.max(SIDEBAR_MIN_WIDTH, event.clientX - left))))
  })

  useEventListener('pointerup', stopDragging)
  useEventListener('pointercancel', stopDragging)

  return (
    <div ref={containerRef} className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
      <div
        className="flex min-h-0 shrink-0 flex-col overflow-y-auto border-b md:border-b-0 md:border-r"
        style={sidebarStyle}
      >
        {sidebar}
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        aria-valuenow={sidebarPercent}
        aria-valuemin={0}
        aria-valuemax={SIDEBAR_MAX_FRACTION * 100}
        className={cn(
          'hidden shrink-0 touch-none md:block',
          'w-1.5 cursor-col-resize bg-border/50 transition-colors',
          'hover:bg-border active:bg-primary/40',
        )}
        onPointerDown={onResizeStart}
      />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">{main}</div>
    </div>
  )
}
