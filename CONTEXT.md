# AI Video Editor

AI Video Editor performs expensive media analysis and rendering requested by
Gradivo without owning the editorial workflow.

## Language

**Video Processing Job**:
One immutable remote execution request from Gradivo. It performs either an
analysis of a Raw Recording or a render of an accepted cut-range snapshot. Its
Gradivo-generated UUID is shared unchanged by both systems.
_Avoid_: Queue Item, review job

**Processed Audio**:
The lossless FLAC produced by analysis after audio extraction and noise
reduction. It is a private, job-scoped S3 artifact retained for a later render,
which combines it with the original Drive video's image stream.
_Avoid_: Final audio, temporary WAV

**Review Proxy**:
The private browser-playable analysis artifact containing the complete uncut
Raw Recording timeline with Processed Audio. Cuts are previewed by Gradivo
playback behavior and are never burned into this file.
_Avoid_: automatic edit, final render, cut preview file

**Final Render Artifact**:
The reviewed MP4 produced by a render job and uploaded directly to Gradivo's
specified Google Drive output folder. It is a durable human-workspace artifact,
not an S3 processing object or a Mux asset.
_Avoid_: Review Proxy, student video

**Analysis Use Case**:
The reusable headless application operation that turns one verified local Raw
Recording into analysis data, a Review Proxy, and Processed Audio. The worker calls this operation; results use the versioned HTTP contract.
_Avoid_: analysis CLI, preprocessing job

**Render Use Case**:
The reusable headless application operation that combines a verified local Raw
Recording, durable Processed Audio, and one immutable human edit snapshot into
a Final Render Artifact. The worker calls this operation from the immutable Gradivo request.
_Avoid_: final-render command, automatic render
