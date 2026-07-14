import { X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer'

const SHORTCUT_GROUPS = [
  {
    title: 'Playback',
    shortcuts: [
      ['Space', 'Play or pause'],
      ['L', 'Hear the current sentence or selection'],
      ['⇧L', 'Loop the audition'],
      ['F', 'Follow playback (auto-scroll the timeline)'],
    ],
  },
  {
    title: 'Transcript editing',
    shortcuts: [
      ['Click', 'Place the cursor and seek there'],
      ['Double-click', 'Select the word'],
      ['← / →', 'Move the cursor word by word'],
      ['⇧← / ⇧→', 'Extend the selection'],
      ['S', 'Select the current sentence'],
      ['X / ⌫', 'Cut the word or selection'],
      ['⏎', 'Keep (un-cut) the selection'],
    ],
  },
  {
    title: 'Timeline',
    shortcuts: [
      ['Drag', 'Select a range to cut'],
      ['Click cut', 'Select an existing cut'],
      ['Drag edge', 'Trim a cut'],
      ['X / ⌫', 'Cut the selected range'],
      ['⏎', 'Restore the selected range'],
      ['i / o', 'Set selection start / end at the playhead'],
      ['⌥ drag', 'Disable snapping'],
      ['⌘/Ctrl scroll', 'Zoom · scroll to pan'],
    ],
  },
  {
    title: 'History & finishing',
    shortcuts: [
      ['⌘Z', 'Undo'],
      ['⇧⌘Z / ⌘Y', 'Redo'],
      ['⌘S', 'Approve & finish'],
    ],
  },
]

const LEGEND = [
  { swatch: 'bg-foreground', label: 'Kept in the final video' },
  { swatch: 'bg-cut/40', label: 'Cut from the final video' },
]

export function HelpDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Drawer swipeDirection="right" open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DrawerContent className="w-full max-w-md rounded-none bg-card">
        <DrawerHeader className="flex shrink-0 items-start justify-between gap-4 border-b px-5 py-4">
          <div>
            <DrawerTitle className="text-base">Help</DrawerTitle>
            <DrawerDescription className="mt-1">
              How the review works, plus keyboard shortcuts for faster editing.
            </DrawerDescription>
          </div>
          <Button type="button" variant="ghost" size="icon-sm" aria-label="Close" onClick={onClose}>
            <X />
          </Button>
        </DrawerHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <section className="mb-6">
            <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              What the colors mean
            </h3>
            <div className="flex flex-col gap-2 rounded-lg border bg-background p-3">
              {LEGEND.map((entry) => (
                <span key={entry.label} className="flex items-center gap-2 text-sm">
                  <i className={`inline-block h-3 w-4.5 rounded-sm ${entry.swatch}`} />
                  {entry.label}
                </span>
              ))}
            </div>
          </section>

          <div className="space-y-5">
            {SHORTCUT_GROUPS.map((group) => (
              <section key={group.title}>
                <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                  {group.title}
                </h3>
                <div className="divide-y rounded-lg border bg-background">
                  {group.shortcuts.map(([keys, description]) => (
                    <div key={keys} className="grid grid-cols-[7rem_1fr] gap-3 px-3 py-2.5">
                      <kbd className="inline-flex h-fit w-fit max-w-full items-center rounded border bg-muted px-2 py-1 font-mono text-xs font-medium text-foreground">
                        {keys}
                      </kbd>
                      <span className="text-sm leading-6 text-muted-foreground">{description}</span>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </div>
      </DrawerContent>
    </Drawer>
  )
}
