import createClient from 'openapi-fetch'
import type { paths } from '@/api/schema'

// Typesafe fetch client generated against the FastAPI OpenAPI spec.
// Paths, params, request bodies, and responses are all inferred from `schema.d.ts`.
export const apiClient = createClient<paths>({ baseUrl: '/' })

/** Extract a human-readable message from an openapi-fetch error body. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = (error as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string }
      if (typeof first?.msg === 'string') return first.msg
    }
  }
  return fallback
}
