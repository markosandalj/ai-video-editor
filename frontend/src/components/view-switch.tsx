import { Button } from '@/components/ui/button'

export type AppView = 'editor' | 'diff'

const VIEWS: Array<{ value: AppView; label: string }> = [
  { value: 'editor', label: 'Transcript' },
  { value: 'diff', label: 'Compare' },
]

/** Top-level switch between transcript editing and QA comparison. */
export function ViewSwitch({ view, onChange }: { view: AppView; onChange: (v: AppView) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border p-0.5">
      {VIEWS.map((entry) => (
        <Button
          key={entry.value}
          size="xs"
          variant={view === entry.value ? 'secondary' : 'ghost'}
          onClick={() => onChange(entry.value)}
        >
          {entry.label}
        </Button>
      ))}
    </div>
  )
}
