import { Button } from '@/components/ui/button'

export type AppView = 'editor' | 'diff'

/** Top-level switch between the review editor and the dev-only compare view. */
export function ViewSwitch({ view, onChange }: { view: AppView; onChange: (v: AppView) => void }) {
  return (
    <div className="flex items-center gap-0.5 rounded-md border p-0.5">
      <Button
        size="xs"
        variant={view === 'editor' ? 'secondary' : 'ghost'}
        onClick={() => onChange('editor')}
      >
        Editor
      </Button>
      <Button
        size="xs"
        variant={view === 'diff' ? 'secondary' : 'ghost'}
        onClick={() => onChange('diff')}
      >
        Compare
      </Button>
    </div>
  )
}
