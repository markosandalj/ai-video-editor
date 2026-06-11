import { createPlayer } from '@videojs/react'
import { videoFeatures } from '@videojs/react/video'

// Single typed player factory shared across the app. `Provider` is remounted
// (via a React `key`) whenever the selected video changes, which resets state.
export const Player = createPlayer({ features: videoFeatures })

export const DEFAULT_PLAYBACK_RATE = 1.7
