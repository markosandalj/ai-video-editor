import { useEffect } from 'react'
import { ExternalLink, Film } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useVideos } from '@/api'
import { Badge } from '@/components/ui/badge'
import { buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDuration } from '@/lib/format'
import { videoPath } from '@/lib/routes'

export function VideoList() {
  const videosQuery = useVideos()
  const videos = videosQuery.data ?? []

  useEffect(() => {
    document.title = 'Videos · AI Video Editor'
  }, [])

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-10 sm:px-8 sm:py-14">
        <header className="flex flex-col gap-3 border-b pb-8 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-3 flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Film className="size-5" />
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight">AI Video Editor</h1>
            <p className="mt-2 text-muted-foreground">
              Open videos in separate tabs and review them side by side.
            </p>
          </div>
          {!videosQuery.isPending && !videosQuery.error && (
            <Badge variant="secondary">
              {videos.length} video{videos.length === 1 ? '' : 's'}
            </Badge>
          )}
        </header>

        {videosQuery.isPending ? (
          <StatusMessage>Loading videos…</StatusMessage>
        ) : videosQuery.error ? (
          <StatusMessage>{videosQuery.error.message}</StatusMessage>
        ) : videos.length === 0 ? (
          <StatusMessage>No processed videos found.</StatusMessage>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {videos.map((video) => (
              <Card key={video.id} className="h-full gap-4 py-5">
                <CardHeader className="gap-3 px-5">
                  <CardTitle className="min-w-0 truncate text-base" title={video.source_name}>
                    {video.source_name}
                  </CardTitle>
                  <div>
                    <Badge variant={video.has_review ? 'default' : 'outline'}>
                      {video.has_review ? 'Reviewed' : 'Needs review'}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="px-5 text-sm text-muted-foreground">
                  {formatDuration(video.duration)}
                </CardContent>
                <CardFooter className="mt-auto gap-2 px-5">
                  {(['transcript', 'compare'] as const).map((view) => (
                    <Link
                      key={view}
                      to={videoPath(video.id, view)}
                      target="_blank"
                      rel="noreferrer"
                      className={buttonVariants({ variant: 'outline', size: 'sm' })}
                    >
                      {view === 'transcript' ? 'Transcript' : 'Compare'}
                      <ExternalLink />
                    </Link>
                  ))}
                </CardFooter>
              </Card>
            ))}
          </div>
        )}
      </div>
    </main>
  )
}

function StatusMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-64 items-center justify-center rounded-xl border border-dashed p-10 text-center text-muted-foreground">
      {children}
    </div>
  )
}
