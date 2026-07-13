import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient, apiErrorMessage } from '@/api/client'
import type { components } from '@/api/schema'

export type VideoSummary = components['schemas']['ReviewVideoSummary']
export type ReviewPayload = components['schemas']['ReviewPayload']
export type ReviewSentence = components['schemas']['ReviewSentence']
export type ReviewWord = components['schemas']['ReviewWord']
export type CutRange = components['schemas']['CutRange']
export type ReviewSaveResponse = components['schemas']['ReviewSaveResponse']
export type RenderResponse = components['schemas']['RenderResponse']
export type PeaksPayload = components['schemas']['PeaksPayload']

export const videoKeys = {
  all: ['videos'] as const,
  review: (videoId: string) => ['videos', videoId, 'review'] as const,
  peaks: (videoId: string, buckets: number) => ['videos', videoId, 'peaks', buckets] as const,
}

/** List every processed video that has an EDL + transcript sidecar. */
export function useVideos() {
  return useQuery({
    queryKey: videoKeys.all,
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/videos')
      if (error || !data) throw new Error(apiErrorMessage(error, 'Failed to load videos'))
      return data
    },
  })
}

/** Load the word-level review payload for a single video. */
export function useReview(videoId: string) {
  return useQuery({
    queryKey: videoKeys.review(videoId),
    enabled: videoId.length > 0,
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/videos/{video_id}/review', {
        params: { path: { video_id: videoId } },
      })
      if (error || !data) throw new Error(apiErrorMessage(error, 'Failed to load review payload'))
      return data
    },
  })
}

/** Downsampled audio waveform for the timeline strip. Cached indefinitely: the
 *  peaks never change for a given source video. */
export function usePeaks(videoId: string, buckets = 8000) {
  return useQuery({
    queryKey: videoKeys.peaks(videoId, buckets),
    enabled: videoId.length > 0,
    staleTime: Infinity,
    gcTime: Infinity,
    queryFn: async () => {
      const { data, error } = await apiClient.GET('/api/videos/{video_id}/peaks', {
        params: { path: { video_id: videoId }, query: { buckets } },
      })
      if (error || !data) throw new Error(apiErrorMessage(error, 'Failed to load waveform'))
      return data
    },
  })
}

/** Persist reviewer decisions as free-form source-time cut ranges. */
export function useSaveReview(videoId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (cutRanges: CutRange[]) => {
      const { data, error } = await apiClient.POST('/api/videos/{video_id}/review', {
        params: { path: { video_id: videoId } },
        body: { cut_ranges: cutRanges },
      })
      if (error || !data) throw new Error(apiErrorMessage(error, 'Save failed'))
      return data
    },
    onSuccess: () => {
      // Refresh the list so the "reviewed" badge reflects the new sidecar.
      void queryClient.invalidateQueries({ queryKey: videoKeys.all })
    },
  })
}

/** Render the reviewed EDL into a `_reviewed` MP4. */
export function useRenderReview(videoId: string) {
  return useMutation({
    mutationFn: async () => {
      const { data, error } = await apiClient.POST('/api/videos/{video_id}/render', {
        params: { path: { video_id: videoId } },
      })
      if (error || !data) throw new Error(apiErrorMessage(error, 'Render failed'))
      return data
    },
  })
}
