import { Button } from '@/components/ui/button'

export type AppView = 'queue' | 'editor' | 'diff'

const VIEWS: Array<{ value: AppView; label: string; devOnly?: boolean }> = [
  { value: 'queue', label: 'Review' },
  { value: 'editor', label: 'Transcript' },
  // Pipeline-vs-human evaluation tool — useful in development, not for reviewers.
  { value: 'diff', label: 'Compare', devOnly: true },
]

/** Top-level switch between the guided review queue and the transcript editor. */
export function ViewSwitch({ view, onChange }: { view: AppView; onChange: (v: AppView) => void }) {
  const views = VIEWS.filter((entry) => !entry.devOnly || import.meta.env.DEV)
  return (
    <div className="flex items-center gap-0.5 rounded-md border p-0.5">
      {views.map((entry) => (
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
