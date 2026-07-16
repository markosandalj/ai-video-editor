export function formatTimestamp(seconds: number) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export function formatDuration(seconds: number) {
  const roundedSeconds = Math.round(seconds)
  const mins = Math.floor(roundedSeconds / 60)
  const secs = roundedSeconds % 60
  return `${mins}m ${secs}s`
}
