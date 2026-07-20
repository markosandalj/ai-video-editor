import { cn } from '@/lib/utils'
import type { DiffSentence, DiffWord } from '@/api/diff'

/** Which edit's cuts to strike through. "diff" overlays both at once. */
export type DiffMode = 'diff' | 'human' | 'pipeline'

export function sentenceStripe(sentence: DiffSentence, mode: DiffMode): string {
  if (mode === 'diff') {
    const { pipeline_kept: p, human_kept: h } = sentence
    if (p && h) return 'border-l-keep/30'
    if (!p && !h) return 'border-l-border'
    if (!p && h) return 'border-l-cut'
    return 'border-l-changed'
  }
  const kept = mode === 'human' ? sentence.human_kept : sentence.pipeline_kept
  return kept ? 'border-l-keep/30' : 'border-l-cut/60'
}

export function wordClassName(word: DiffWord, mode: DiffMode): { struck: boolean; tone: string } {
  const p = word.pipeline_kept
  const h = word.human_kept
  if (mode === 'pipeline') {
    return { struck: !p, tone: !p ? 'text-cut/70 decoration-cut' : 'text-foreground' }
  }
  if (mode === 'human') {
    return { struck: !h, tone: !h ? 'text-cut/70 decoration-cut' : 'text-foreground' }
  }
  if (p && h) return { struck: false, tone: 'text-foreground' }
  if (!p && !h)
    return { struck: true, tone: 'text-muted-foreground/50 decoration-muted-foreground' }
  if (!p && h) return { struck: true, tone: 'text-cut decoration-cut' }
  return { struck: true, tone: 'text-changed decoration-changed' }
}

type DiffTranscriptProps = {
  sentences: DiffSentence[]
  mode?: DiffMode
  /** Compact type for board cards. */
  compact?: boolean
  className?: string
}

/** Raw transcript with pipeline/human cuts marked — shared by Compare and Board. */
export function DiffTranscript({
  sentences,
  mode = 'diff',
  compact = false,
  className,
}: DiffTranscriptProps) {
  return (
    <div className={cn(compact ? 'text-sm leading-relaxed' : 'text-lg leading-loose', className)}>
      {sentences.map((sentence) => (
        <DiffSentenceRow key={sentence.idx} sentence={sentence} mode={mode} compact={compact} />
      ))}
    </div>
  )
}

function DiffSentenceRow({
  sentence,
  mode,
  compact,
}: {
  sentence: DiffSentence
  mode: DiffMode
  compact: boolean
}) {
  const disagreement = sentence.pipeline_kept !== sentence.human_kept
  return (
    <div
      className={cn('mb-1 flex gap-2 rounded-r border-l-4 pl-2', sentenceStripe(sentence, mode))}
    >
      <p className="min-w-0 flex-1">
        {mode === 'diff' && disagreement && (
          <span
            className={cn(
              'mr-1 inline-flex items-center rounded px-1.5 py-0.5 align-middle font-semibold',
              compact ? 'text-[9px]' : 'text-[10px]',
              sentence.pipeline_kept ? 'bg-changed/15 text-changed' : 'bg-cut/15 text-cut',
            )}
          >
            {sentence.pipeline_kept ? 'missed cut' : 'over-cut'}
          </span>
        )}
        {sentence.words.map((word) => (
          <DiffWordSpan key={`${sentence.idx}-${word.start}-${word.end}`} word={word} mode={mode} />
        ))}
      </p>
    </div>
  )
}

function DiffWordSpan({ word, mode }: { word: DiffWord; mode: DiffMode }) {
  const { struck, tone } = wordClassName(word, mode)
  return (
    <span className={cn('rounded px-0.5 select-none', struck && 'line-through', tone)}>
      {word.text}{' '}
    </span>
  )
}

export function DiffLegend({ mode }: { mode: DiffMode }) {
  if (mode === 'diff') {
    return (
      <div className="flex flex-col gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-foreground" /> both keep
        </span>
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-cut" /> over-cut · we removed, human
          kept
        </span>
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-changed" /> missed cut · human removed,
          we kept
        </span>
        <span className="flex items-center gap-2">
          <i className="inline-block h-3 w-4.5 rounded-sm bg-muted-foreground/50" /> both cut
        </span>
      </div>
    )
  }
  const who = mode === 'human' ? 'the human editor' : 'our pipeline'
  return (
    <div className="flex flex-col gap-2 text-xs text-muted-foreground">
      <span className="flex items-center gap-2">
        <i className="inline-block h-3 w-4.5 rounded-sm bg-foreground" /> kept by {who}
      </span>
      <span className="flex items-center gap-2">
        <i className="inline-block h-3 w-4.5 rounded-sm bg-cut/70" /> removed by {who}
      </span>
    </div>
  )
}
