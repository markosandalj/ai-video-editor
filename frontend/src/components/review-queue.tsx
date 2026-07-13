import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronLeft, ChevronRight, Play, Scissors, Sparkles } from 'lucide-react'
import { useEventCallback } from 'usehooks-ts'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { ReviewSession } from '@/hooks/use-review-session'
import { Player } from '@/lib/player'
import { reasonLabel, type ReviewFlag, sentenceDecisionFromStatus } from '@/lib/review-model'
import { cn } from '@/lib/utils'
import { formatTimestamp } from '@/lib/format'

type ReviewQueueProps = {
  flags: ReviewFlag[]
  session: ReviewSession
  onAudition: (start: number, end: number, label: string) => void
  onOpenTranscript: () => void
  onFinish: () => void
}

// The professor's primary surface. One flagged sentence at a time: hear it, then
// keep it or cut it. The AI's suggestion and reason are guidance, not chrome.
export function ReviewQueue({
  flags,
  session,
  onAudition,
  onOpenTranscript,
  onFinish,
}: ReviewQueueProps) {
  const player = Player.usePlayer()
  const { wordStatus, setCut, sentenceByWord, finishState } = session
  const [index, setIndex] = useState(0)
  const [decided, setDecided] = useState<Set<number>>(new Set())

  // A fresh video resets the walk-through.
  useEffect(() => {
    setIndex(0)
    setDecided(new Set())
  }, [flags])

  const flag = flags[index] ?? null

  // Park the playhead at the top of the flagged sentence when it comes up.
  useEffect(() => {
    if (flag) void player.seek(flag.start)
  }, [flag, player])

  const sentence = flag ? (sentenceByWord.get(flag.firstWordIdx) ?? null) : null
  const decision = sentence ? sentenceDecisionFromStatus(sentence, wordStatus) : 'kept'

  const decide = useEventCallback((cut: boolean) => {
    if (!flag?.wordRange) return
    setCut(flag.wordRange[0], flag.wordRange[1], cut)
    setDecided((current) => new Set(current).add(flag.sentenceIdx))
    // Advance to the next still-undecided flag, else just step forward.
    setIndex((current) => {
      const nextUndecided = flags.findIndex(
        (candidate, i) => i > current && !decided.has(candidate.sentenceIdx),
      )
      return nextUndecided === -1 ? Math.min(current + 1, flags.length) : nextUndecided
    })
  })

  const reviewedCount = decided.size
  const allDone = flags.length > 0 && reviewedCount === flags.length
  const atEnd = index >= flags.length

  const reason = useMemo(() => (flag ? reasonLabel(flag.reason) : ''), [flag])

  if (flags.length === 0) {
    return (
      <QueueShell heading="Nothing needs your review" progress={null}>
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex size-14 items-center justify-center rounded-full bg-keep/15 text-keep">
            <Check className="size-7" />
          </div>
          <p className="max-w-sm text-muted-foreground">
            The AI was confident about every cut in this lecture. You can render it as-is, or open
            the full transcript to look around.
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onOpenTranscript}>
              Open transcript
            </Button>
            <FinishButton onFinish={onFinish} finishState={finishState} />
          </div>
        </div>
      </QueueShell>
    )
  }

  if (atEnd || allDone) {
    return (
      <QueueShell
        heading="You've reviewed everything"
        progress={{ reviewed: reviewedCount, total: flags.length }}
      >
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex size-14 items-center justify-center rounded-full bg-keep/15 text-keep">
            <Sparkles className="size-7" />
          </div>
          <p className="max-w-sm text-muted-foreground">
            {reviewedCount} of {flags.length} suggestions decided. Approve to save your edit and
            render the finished video.
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setIndex(0)}>
              Back to start
            </Button>
            <FinishButton onFinish={onFinish} finishState={finishState} />
          </div>
        </div>
      </QueueShell>
    )
  }

  return (
    <QueueShell
      heading={`Suggestion ${index + 1} of ${flags.length}`}
      progress={{ reviewed: reviewedCount, total: flags.length }}
    >
      <div className="flex items-center gap-2">
        {reason && <Badge variant="secondary">{reason}</Badge>}
        <span className="text-xs tabular-nums text-muted-foreground">
          {formatTimestamp(flag!.start)}
        </span>
        <span
          className={cn(
            'ml-auto rounded-full px-2 py-0.5 text-xs font-medium',
            decision === 'cut' ? 'bg-cut/15 text-cut' : 'bg-keep/15 text-keep',
          )}
        >
          {decision === 'cut' ? 'Will be cut' : decision === 'partial' ? 'Partly cut' : 'Kept in'}
        </span>
      </div>

      <blockquote
        className={cn(
          'my-5 border-l-2 pl-4 text-xl leading-relaxed',
          decision === 'cut'
            ? 'border-cut/40 text-muted-foreground line-through decoration-cut/50'
            : 'border-border text-foreground',
        )}
      >
        {flag!.text}
      </blockquote>

      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">
          {flag!.aiKept ? 'The AI kept this in. ' : 'The AI suggests removing this. '}
        </span>
        {flag!.rationale || 'No explanation was recorded for this suggestion.'}
      </p>

      <div className="mt-6 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() => onAudition(flag!.start, flag!.end, 'this sentence')}
        >
          <Play />
          Hear it
        </Button>
        <div className="ml-auto flex gap-2">
          <Button
            variant={decision === 'kept' ? 'default' : 'outline'}
            className={cn(decision === 'kept' && 'bg-keep text-white hover:bg-keep/90')}
            onClick={() => decide(false)}
          >
            <Check />
            Keep it
          </Button>
          <Button
            variant={decision === 'cut' ? 'destructive' : 'outline'}
            onClick={() => decide(true)}
          >
            <Scissors />
            Cut it
          </Button>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between border-t pt-4">
        <Button
          variant="ghost"
          size="sm"
          disabled={index === 0}
          onClick={() => setIndex((current) => Math.max(0, current - 1))}
        >
          <ChevronLeft />
          Previous
        </Button>
        <button
          type="button"
          className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          onClick={onOpenTranscript}
        >
          Edit the full transcript instead
        </button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIndex((current) => Math.min(flags.length, current + 1))}
        >
          Skip
          <ChevronRight />
        </Button>
      </div>
    </QueueShell>
  )
}

function QueueShell({
  heading,
  progress,
  children,
}: {
  heading: string
  progress: { reviewed: number; total: number } | null
  children: React.ReactNode
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto my-8 w-full max-w-2xl px-6">
        <div className="mb-4 flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold tracking-tight">{heading}</h2>
          {progress && (
            <span className="text-xs tabular-nums text-muted-foreground">
              {progress.reviewed} / {progress.total} reviewed
            </span>
          )}
        </div>
        {progress && (
          <div className="mb-6 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${progress.total ? (progress.reviewed / progress.total) * 100 : 0}%` }}
            />
          </div>
        )}
        <div className="rounded-xl border bg-card p-6 shadow-sm">{children}</div>
      </div>
    </div>
  )
}

function FinishButton({
  onFinish,
  finishState,
}: {
  onFinish: () => void
  finishState: ReviewSession['finishState']
}) {
  const label =
    finishState === 'saving'
      ? 'Saving…'
      : finishState === 'rendering'
        ? 'Rendering…'
        : finishState === 'done'
          ? 'Done'
          : 'Approve & finish'
  const busy = finishState === 'saving' || finishState === 'rendering'
  return (
    <Button className="bg-keep text-white hover:bg-keep/90" disabled={busy} onClick={onFinish}>
      {finishState === 'done' ? <Check /> : <Sparkles />}
      {label}
    </Button>
  )
}
