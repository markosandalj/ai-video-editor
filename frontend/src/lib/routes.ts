export type VideoView = 'transcript' | 'compare'

export function videoPath(videoId: string, view: VideoView, search = ''): string {
  const path = `/videos/${encodeURIComponent(videoId)}/${view}`
  const query = search.replace(/^\?/, '')
  return query ? `${path}?${query}` : path
}
