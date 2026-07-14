import { useQuery } from '@tanstack/react-query'

// QA diff view types. Hand-written so the comparison surface stays decoupled
// from the generated review API types.

export type DiffWord = {
  text: string
  start: number
  end: number
  pipeline_kept: boolean
  human_kept: boolean
}

export type DiffSentence = {
  idx: number
  text: string
  start: number
  end: number
  pipeline_kept: boolean
  human_kept: boolean
  words: DiffWord[]
}

export type DiffSummary = {
  has_ground_truth: boolean
  raw_sentences: number
  raw_words: number
  pipeline_kept_sentences: number
  human_kept_sentences: number
  pipeline_kept_words: number
  human_kept_words: number
  agree_keep: number
  agree_cut: number
  pipeline_only_cut: number
  human_only_cut: number
}

export type DiffPayload = {
  video: { id: string; source_name: string; duration: number; has_ground_truth: boolean }
  summary: DiffSummary
  sentences: DiffSentence[]
}

/** Load the raw-transcript diff (pipeline vs human edit) for a single video. */
export function useDiff(videoId: string) {
  return useQuery({
    queryKey: ['videos', videoId, 'diff'],
    enabled: videoId.length > 0,
    queryFn: async () => {
      const res = await fetch(`/api/videos/${encodeURIComponent(videoId)}/diff`)
      if (!res.ok) {
        let detail = 'Failed to load diff'
        try {
          const body = (await res.json()) as { detail?: unknown }
          if (typeof body.detail === 'string') detail = body.detail
        } catch {
          // ignore non-JSON error bodies
        }
        throw new Error(detail)
      }
      return (await res.json()) as DiffPayload
    },
  })
}
