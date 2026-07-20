import '@videojs/react/video/skin.css'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useHotkeys, type UseHotkeyDefinition } from '@tanstack/react-hotkeys'
import { Agentation } from 'agentation'
import { Check, CircleHelp, Redo2, Scissors, Sparkles, Undo2 } from 'lucide-react'
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom'
import { useBoolean, useEventCallback } from 'usehooks-ts'

import { DiffBoardView } from '@/DiffBoardView'
import { DiffView } from '@/DiffView'
import { HelpDrawer } from '@/components/help-drawer'
import { MediaColumn } from '@/components/media-column'
import { PaneVisibilityControls } from '@/components/pane-visibility-controls'
import type { AuditionRange } from '@/components/playback-sync'
import { ResizableSplit } from '@/components/resizable-split'
import { TimelineStrip } from '@/components/timeline/timeline-strip'
import { TranscriptView } from '@/components/transcript-view'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ViewSwitch } from '@/components/view-switch'
import { VideoList } from '@/components/video-list'
import { useReview, useVideos } from '@/api'
import type { ReviewPayload, VideoSummary } from '@/api'
import { useEditorSelection } from '@/hooks/use-editor-selection'
import { useReviewSession } from '@/hooks/use-review-session'
import { Player } from '@/lib/player'
import { videoPath, type VideoView } from '@/lib/routes'
import type { TimeRange } from '@/lib/timeline-model'

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<VideoList />} />
        <Route path="/board" element={<DiffBoardView />} />
        <Route path="/videos/:videoId" element={<VideoViewRedirect />} />
        <Route path="/videos/:videoId/transcript" element={<VideoEditor view="transcript" />} />
        <Route path="/videos/:videoId/compare" element={<VideoEditor view="compare" />} />
        <Route path="/videos/:videoId/*" element={<VideoViewRedirect />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {import.meta.env.DEV && <Agentation />}
    </>
  )
}

function VideoViewRedirect() {
  const { videoId = '' } = useParams()
  const { search } = useLocation()
  return <Navigate to={videoPath(videoId, 'transcript', search)} replace />
}

function VideoEditor({ view }: { view: VideoView }) {
  const videosQuery = useVideos()
  const { videoId = '' } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.toString()
  const videoHidden = searchParams.get('video') === 'hidden'
  const transcriptHidden = searchParams.get('transcript') === 'hidden'

  const setPaneHidden = useCallback(
    (pane: 'video' | 'transcript', hidden: boolean) => {
      const next = new URLSearchParams(searchParams)
      if (hidden) next.set(pane, 'hidden')
      else next.delete(pane)
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const selectVideo = useCallback(
    (nextVideoId: string) => navigate(videoPath(nextVideoId, view, search)),
    [navigate, search, view],
  )

  useEffect(() => {
    const video = videosQuery.data?.find((candidate) => candidate.id === videoId)
    const viewName = view === 'compare' ? 'Compare' : 'Transcript'
    document.title = video
      ? `${video.source_name} · ${viewName} · AI Video Editor`
      : `${viewName} · AI Video Editor`
  }, [videoId, videosQuery.data, view])

  const message = videosQuery.isPending
    ? 'Loading videos…'
    : videosQuery.error
      ? videosQuery.error.message
      : (videosQuery.data?.length ?? 0) > 0
        ? 'Select a video to start reviewing.'
        : 'No processed videos found.'

  return (
    <>
      {/* Keyed only on the video so switching Transcript↔Compare keeps playback stable. */}
      <Player.Provider key={videoId || 'empty'}>
        {view === 'compare' ? (
          <DiffView
            videoId={videoId}
            videos={videosQuery.data ?? []}
            message={message}
            onSelect={selectVideo}
            search={search}
            videoHidden={videoHidden}
            transcriptHidden={transcriptHidden}
            onVideoHiddenChange={(hidden) => setPaneHidden('video', hidden)}
            onTranscriptHiddenChange={(hidden) => setPaneHidden('transcript', hidden)}
          />
        ) : (
          <Workspace
            videoId={videoId}
            videos={videosQuery.data ?? []}
            message={message}
            onSelect={selectVideo}
            search={search}
            videoHidden={videoHidden}
            transcriptHidden={transcriptHidden}
            onVideoHiddenChange={(hidden) => setPaneHidden('video', hidden)}
            onTranscriptHiddenChange={(hidden) => setPaneHidden('transcript', hidden)}
          />
        )}
      </Player.Provider>
    </>
  )
}

type WorkspaceProps = {
  videoId: string
  videos: VideoSummary[]
  message: string
  onSelect: (id: string) => void
  search: string
  videoHidden: boolean
  transcriptHidden: boolean
  onVideoHiddenChange: (hidden: boolean) => void
  onTranscriptHiddenChange: (hidden: boolean) => void
}

function Workspace({
  videoId,
  videos,
  message,
  onSelect,
  search,
  videoHidden,
  transcriptHidden,
  onVideoHiddenChange,
  onTranscriptHiddenChange,
}: WorkspaceProps) {
  const player = Player.usePlayer()
  const paused = Player.usePlayer((state) => state.paused)
  const review = useReview(videoId)
  const payload = (review.data as ReviewPayload | undefined) ?? null
  const session = useReviewSession(payload, videoId)

  const previewEdit = useBoolean(true)
  const loopAudition = useBoolean(false)
  const followTimelinePlayback = useBoolean(false)
  const followTranscriptPlayback = useBoolean(true)
  const helpOpen = useBoolean(false)
  const timelineCollapsed = useBoolean(false)
  const timelineEditing = useBoolean(false)

  // The one active time selection on the timeline (a pending cut, or a selected
  // existing cut). Exactly one selection is active app-wide: setting this clears
  // the transcript's word selection and vice versa.
  const [timeSelection, setTimeSelection] = useState<TimeRange | null>(null)

  const [auditionRange, setAuditionRange] = useState<AuditionRange | null>(null)
  const [activeIdx, setActiveIdx] = useState<number | null>(null)
  const [status, setStatus] = useState('')

  const wordRefs = useRef(new Map<number, HTMLSpanElement>())
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const onStatus = useEventCallback((text: string) => setStatus(text))

  const scrollToWord = useEventCallback((idx: number, band = false) => {
    const element = wordRefs.current.get(idx)
    if (!element) return
    if (!band || !scrollRef.current) {
      element.scrollIntoView({ block: 'nearest' })
      return
    }
    const box = element.getBoundingClientRect()
    const container = scrollRef.current.getBoundingClientRect()
    const margin = container.height * 0.2
    if (box.top < container.top + margin || box.bottom > container.bottom - margin) {
      element.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  })

  const audition = useEventCallback((start: number, end: number, label: string) => {
    setAuditionRange({ start, end, label })
    void player.seek(start)
    void player.play()
    setStatus(`Auditioning ${label}.`)
  })

  const selection = useEditorSelection({
    session,
    activeIdx,
    // Disabled while a timeline selection is active, so the shared verbs
    // (X/⏎/L/Esc) act on exactly one selection.
    enabled: payload !== null && !helpOpen.value && timeSelection === null,
    onAudition: audition,
    onStatus,
    scrollToWord,
    onSelectionPlaced: () => setTimeSelection(null),
  })

  // Timeline selection ⇒ drop the transcript's word selection and reveal the
  // overlapped words so the reviewer sees what speech the range covers.
  const clearWordSelection = selection.clearSelection
  useEffect(() => {
    if (!timeSelection) return
    clearWordSelection()
    const word =
      session.words.find((w) => timeSelection.start >= w.start && timeSelection.start <= w.end) ??
      session.words.find((w) => w.start >= timeSelection.start)
    if (word) scrollToWord(word.idx, true)
  }, [timeSelection, session.words, clearWordSelection, scrollToWord])

  // A new video clears any stale timeline selection.
  useEffect(() => setTimeSelection(null), [videoId])

  const finish = useEventCallback(async () => {
    if (!payload) return
    setStatus('Saving your review and rendering the final video…')
    await session.approveAndFinish()
  })

  // Global hotkeys — active in both modes.
  const baseEnabled = payload !== null && !helpOpen.value
  const globalHotkeys: UseHotkeyDefinition[] = [
    { hotkey: 'Space', callback: () => player.togglePaused(), options: { enabled: baseEnabled } },
    {
      hotkey: 'Mod+S',
      callback: () => void finish(),
      options: { enabled: baseEnabled, ignoreInputs: false },
    },
    { hotkey: 'Mod+Z', callback: () => session.undo(), options: { enabled: baseEnabled } },
    { hotkey: 'Mod+Shift+Z', callback: () => session.redo(), options: { enabled: baseEnabled } },
    { hotkey: 'Mod+Y', callback: () => session.redo(), options: { enabled: baseEnabled } },
    { hotkey: 'Shift+L', callback: () => loopAudition.toggle(), options: { enabled: baseEnabled } },
    {
      hotkey: 'F',
      callback: () => followTimelinePlayback.toggle(),
      options: { enabled: baseEnabled },
    },
  ]

  useHotkeys(globalHotkeys, {
    conflictBehavior: 'allow',
    preventDefault: true,
    stopPropagation: true,
  })

  // Follow playback in the transcript: keep the active word in view without jitter.
  useEffect(() => {
    if (!followTranscriptPlayback.value || activeIdx === null) return
    scrollToWord(activeIdx, true)
  }, [activeIdx, followTranscriptPlayback.value, scrollToWord])

  const finishLabel =
    session.finishState === 'saving'
      ? 'Saving…'
      : session.finishState === 'rendering'
        ? 'Rendering…'
        : session.finishState === 'done'
          ? 'Finished'
          : 'Approve & finish'
  const finishBusy = session.finishState === 'saving' || session.finishState === 'rendering'

  const statusText = review.isLoading
    ? 'Loading review…'
    : review.error
      ? review.error.message
      : status || (payload ? defaultHint() : message)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-card px-4 py-2.5">
        <span className="text-sm font-extrabold tracking-tight">AI Video Editor</span>
        <ViewSwitch videoId={videoId} view="transcript" search={search} />

        <Select value={videoId} onValueChange={onSelect}>
          <SelectTrigger size="sm" className="w-[260px]">
            <SelectValue placeholder="Select a video" />
          </SelectTrigger>
          <SelectContent>
            {videos.map((video) => (
              <SelectItem key={video.id} value={video.id}>
                {video.source_name}
                {video.has_review ? ' • reviewed' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <PaneVisibilityControls
          videoHidden={videoHidden}
          transcriptHidden={transcriptHidden}
          onVideoHiddenChange={onVideoHiddenChange}
          onTranscriptHiddenChange={onTranscriptHiddenChange}
        />

        <div className="ml-auto flex items-center gap-2">
          {payload && session.isDirty && (
            <Badge variant="outline" className="border-changed/60 text-changed">
              Unsaved
            </Badge>
          )}
          <Button
            size="sm"
            className="bg-keep text-white hover:bg-keep/90"
            onClick={finish}
            disabled={!payload || finishBusy}
          >
            {session.finishState === 'done' ? <Check /> : <Sparkles />}
            {finishLabel}
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Help and keyboard shortcuts"
            onClick={() => helpOpen.setValue(true)}
          >
            <CircleHelp />
          </Button>
        </div>
      </header>

      {payload ? (
        <ResizableSplit
          sidebarHidden={videoHidden}
          mainHidden={transcriptHidden}
          sidebar={
            <MediaColumn
              videoId={payload.video.id}
              session={session}
              previewEdit={previewEdit.value}
              onPreviewEditChange={previewEdit.setValue}
              auditionRange={auditionRange}
              loopAudition={loopAudition.value}
              suspendPreview={timeSelection !== null || timelineEditing.value}
              onActive={setActiveIdx}
              onAuditionEnd={() => {
                setAuditionRange(null)
                setStatus('Audition complete.')
              }}
            >
              <EditorControls session={session} selection={selection} />
            </MediaColumn>
          }
          main={
            <TranscriptView
              sentences={payload.sentences}
              wordStatus={session.wordStatus}
              selection={selection}
              activeIdx={activeIdx}
              wordRefs={wordRefs}
              scrollRef={scrollRef}
              follow={followTranscriptPlayback.value}
              onToggleFollow={followTranscriptPlayback.toggle}
              onManualScroll={() => {
                if (!paused) followTranscriptPlayback.setFalse()
              }}
            />
          }
        />
      ) : (
        <div className="flex flex-1 items-center justify-center p-12 text-center text-muted-foreground">
          {statusText}
        </div>
      )}

      {payload && (
        <TimelineStrip
          videoId={payload.video.id}
          duration={payload.video.duration}
          cutRanges={session.cutRanges}
          words={session.words}
          sentences={payload.sentences}
          timeSelection={timeSelection}
          onTimeSelectionChange={setTimeSelection}
          onCommitCut={session.addCutRange}
          onRestore={session.removeCutRange}
          onCommitRanges={session.commitRanges}
          onAudition={audition}
          onEditingChange={timelineEditing.setValue}
          follow={followTimelinePlayback.value}
          onToggleFollow={followTimelinePlayback.toggle}
          onDisableFollow={followTimelinePlayback.setFalse}
          collapsed={timelineCollapsed.value}
          onToggleCollapsed={timelineCollapsed.toggle}
        />
      )}

      <footer className="shrink-0 truncate border-t bg-card px-4 py-2 text-sm text-muted-foreground">
        {statusText}
      </footer>
      <HelpDrawer open={helpOpen.value} onClose={() => helpOpen.setValue(false)} />
    </div>
  )
}

// The four editing actions that earn a permanent slot under the video.
function EditorControls({
  session,
  selection,
}: {
  session: ReturnType<typeof useReviewSession>
  selection: ReturnType<typeof useEditorSelection>
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <Button
          variant="destructive"
          size="sm"
          onClick={() => selection.applySelection(true)}
          disabled={!selection.hasSelection}
        >
          <Scissors />
          Cut ⌫
        </Button>
        <Button
          size="sm"
          className="bg-keep text-white hover:bg-keep/90"
          onClick={() => selection.applySelection(false)}
          disabled={!selection.hasSelection}
        >
          <Check />
          Keep ⏎
        </Button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Button variant="outline" size="sm" onClick={session.undo} disabled={!session.canUndo}>
          <Undo2 />
          Undo ⌘Z
        </Button>
        <Button variant="outline" size="sm" onClick={session.redo} disabled={!session.canRedo}>
          <Redo2 />
          Redo ⇧⌘Z
        </Button>
      </div>
    </div>
  )
}

function defaultHint(): string {
  return 'Click a word to place the cursor · double-click selects · X cuts · L auditions.'
}
