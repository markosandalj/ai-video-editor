from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Protocol

from uuid import UUID

from ai_video_editor.worker.contracts import (
    GoogleDriveFinalVideo,
    GoogleDriveOutput,
    GoogleDriveSource,
    S3ObjectReference,
)


class SourceNotFound(Exception):
    pass


class SourceAccessDenied(Exception):
    pass


class SourceChanged(Exception):
    pass


class SourceDownloadFailed(Exception):
    pass


class ArtifactUploadFailed(Exception):
    pass


class ProcessedAudioMissing(Exception):
    pass


class ProcessedAudioDownloadFailed(Exception):
    pass


class DuplicateOutputArtifacts(Exception):
    pass


class OutputUploadFailed(Exception):
    pass


class DriveSourceProvider(Protocol):
    def download(self, source: GoogleDriveSource, destination: Path) -> Path: ...


class AnalysisArtifactStore(Protocol):
    def upload(
        self,
        source: Path,
        *,
        key: str,
        mime_type: str,
    ) -> S3ObjectReference: ...


class ProcessedAudioProvider(Protocol):
    def download(self, reference: S3ObjectReference, destination: Path) -> Path: ...


class DriveOutputProvider(Protocol):
    def find_completed(
        self, job_id: UUID, output: GoogleDriveOutput
    ) -> GoogleDriveFinalVideo | None: ...

    def upload(
        self,
        job_id: UUID,
        source: Path,
        output: GoogleDriveOutput,
    ) -> GoogleDriveFinalVideo: ...


class GoogleDriveSourceProvider:
    """Downloads and verifies one immutable Drive source with worker OAuth."""

    def __init__(self, service):
        self._service = service

    @classmethod
    def from_oauth(
        cls,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> GoogleDriveSourceProvider:
        return cls(
            _google_drive_service(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )
        )

    def download(self, source: GoogleDriveSource, destination: Path) -> Path:
        try:
            metadata = (
                self._service.files()
                .get(
                    fileId=source.file_id,
                    fields="id,headRevisionId,size,mimeType,md5Checksum",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:
            self._raise_drive_failure(exc)
            raise AssertionError("unreachable")

        if not isinstance(metadata, dict) or metadata.get("id") != source.file_id:
            raise SourceChanged
        live_size = _metadata_int(metadata.get("size"))
        live_checksum = metadata.get("md5Checksum")
        expected_checksum = source.checksum.value if source.checksum is not None else None
        if (
            metadata.get("headRevisionId") != source.head_revision_id
            or live_size != source.size_bytes
            or metadata.get("mimeType") != source.mime_type
            or (expected_checksum is not None and live_checksum != expected_checksum)
        ):
            raise SourceChanged

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            from googleapiclient.http import MediaIoBaseDownload

            request = self._service.files().get_media(
                fileId=source.file_id,
                supportsAllDrives=True,
            )
            with destination.open("wb") as output:
                downloader = MediaIoBaseDownload(output, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
        except Exception as exc:
            destination.unlink(missing_ok=True)
            self._raise_drive_failure(exc)
            raise AssertionError("unreachable")

        digest = _md5(destination)
        if (
            destination.stat().st_size != source.size_bytes
            or (live_checksum is not None and digest != live_checksum)
            or (expected_checksum is not None and digest != expected_checksum)
        ):
            destination.unlink(missing_ok=True)
            raise SourceChanged
        return destination

    @staticmethod
    def _raise_drive_failure(exc: Exception) -> None:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 404:
            raise SourceNotFound from exc
        if status in {401, 403}:
            raise SourceAccessDenied from exc
        raise SourceDownloadFailed from exc


class R2AnalysisArtifactStore:
    _UPLOAD_FAILURE_MESSAGE = "Analysis artifact upload could not be verified"

    def __init__(self, client, *, bucket: str):
        if not bucket:
            raise ValueError("VIDEO_PROCESSING_S3_BUCKET is required")
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_credentials(
        cls,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> R2AnalysisArtifactStore:
        return cls(
            _r2_client(
                endpoint_url=endpoint_url,
                bucket=bucket,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            ),
            bucket=bucket,
        )

    def upload(
        self,
        source: Path,
        *,
        key: str,
        mime_type: str,
    ) -> S3ObjectReference:
        try:
            source_size = source.stat().st_size
            self._client.upload_file(
                str(source),
                self._bucket,
                key,
                ExtraArgs={"ContentType": mime_type},
            )
            metadata = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise ArtifactUploadFailed(self._UPLOAD_FAILURE_MESSAGE) from exc
        size = metadata.get("ContentLength")
        etag = metadata.get("ETag")
        stored_mime_type = metadata.get("ContentType")
        if (
            type(size) is not int
            or size <= 0
            or size != source_size
            or stored_mime_type != mime_type
            or not isinstance(etag, str)
            or not etag
        ):
            raise ArtifactUploadFailed(self._UPLOAD_FAILURE_MESSAGE)
        return S3ObjectReference(
            type="s3_object",
            key=key,
            size_bytes=size,
            mime_type=mime_type,
            etag=etag.strip('"'),
        )


class R2ProcessedAudioProvider:
    """Downloads a durable Processed Audio object and verifies its manifest."""

    def __init__(self, client, *, bucket: str):
        if not bucket:
            raise ValueError("VIDEO_PROCESSING_S3_BUCKET is required")
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_credentials(
        cls,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> R2ProcessedAudioProvider:
        return cls(
            _r2_client(
                endpoint_url=endpoint_url,
                bucket=bucket,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            ),
            bucket=bucket,
        )

    def download(self, reference: S3ObjectReference, destination: Path) -> Path:
        try:
            metadata = self._client.head_object(
                Bucket=self._bucket,
                Key=reference.key,
            )
        except Exception as exc:
            if _is_missing_s3_object(exc):
                raise ProcessedAudioMissing from exc
            raise ProcessedAudioDownloadFailed from exc

        size = metadata.get("ContentLength")
        etag = _clean_etag(metadata.get("ETag"))
        mime_type = metadata.get("ContentType")
        if (
            type(size) is not int
            or size != reference.size_bytes
            or etag != _clean_etag(reference.etag)
            or (mime_type is not None and mime_type != reference.mime_type)
        ):
            raise ProcessedAudioDownloadFailed

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(
                self._bucket,
                reference.key,
                str(destination),
            )
        except Exception as exc:
            destination.unlink(missing_ok=True)
            if _is_missing_s3_object(exc):
                raise ProcessedAudioMissing from exc
            raise ProcessedAudioDownloadFailed from exc
        if not destination.is_file() or destination.stat().st_size != reference.size_bytes:
            destination.unlink(missing_ok=True)
            raise ProcessedAudioDownloadFailed
        return destination


class GoogleDriveOutputProvider:
    """Creates a UUID-marked file, then resumably updates that stable Drive ID."""

    APP_PROPERTY_KEY = "video_processing_job_id"

    def __init__(self, service):
        self._service = service

    @classmethod
    def from_oauth(
        cls,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> GoogleDriveOutputProvider:
        return cls(
            _google_drive_service(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )
        )

    def find_completed(
        self, job_id: UUID, output: GoogleDriveOutput
    ) -> GoogleDriveFinalVideo | None:
        matches = self._find(job_id, output)
        if len(matches) > 1:
            raise DuplicateOutputArtifacts
        if not matches or not _is_complete_drive_video(matches[0]):
            return None
        return _drive_final_video(matches[0])

    def upload(
        self,
        job_id: UUID,
        source: Path,
        output: GoogleDriveOutput,
    ) -> GoogleDriveFinalVideo:
        matches = self._find(job_id, output)
        if len(matches) > 1:
            raise DuplicateOutputArtifacts
        if matches and _is_complete_drive_video(matches[0]):
            return _drive_final_video(matches[0])

        if matches:
            file_id = matches[0].get("id")
            if not isinstance(file_id, str) or not file_id:
                raise OutputUploadFailed
        else:
            try:
                created = (
                    self._service.files()
                    .create(
                        body={
                            "name": output.display_name,
                            "parents": [output.folder_id],
                            "mimeType": "video/mp4",
                            "appProperties": {
                                self.APP_PROPERTY_KEY: str(job_id),
                            },
                        },
                        fields="id",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
            except Exception as exc:
                after_create = self._find(job_id, output)
                if len(after_create) > 1:
                    raise DuplicateOutputArtifacts from exc
                if not after_create:
                    raise OutputUploadFailed from exc
                if _is_complete_drive_video(after_create[0]):
                    return _drive_final_video(after_create[0])
                file_id = after_create[0].get("id")
            else:
                file_id = created.get("id") if isinstance(created, dict) else None
            if not isinstance(file_id, str) or not file_id:
                raise OutputUploadFailed

        try:
            from googleapiclient.http import MediaFileUpload

            request = self._service.files().update(
                fileId=file_id,
                media_body=MediaFileUpload(
                    str(source),
                    mimetype="video/mp4",
                    resumable=True,
                ),
                fields=_DRIVE_FINAL_FIELDS,
                supportsAllDrives=True,
            )
            response = None
            while response is None:
                _, response = request.next_chunk()
        except Exception as exc:
            reconciled = self._reconcile_after_unknown(job_id, output)
            if reconciled is not None:
                return reconciled
            raise OutputUploadFailed from exc

        matches = self._find(job_id, output)
        if len(matches) > 1:
            raise DuplicateOutputArtifacts
        if len(matches) != 1 or not _is_complete_drive_video(matches[0]):
            raise OutputUploadFailed
        final = _drive_final_video(matches[0])
        if final.size_bytes != source.stat().st_size or final.checksum.value != _md5(source):
            raise OutputUploadFailed
        return final

    def _reconcile_after_unknown(
        self, job_id: UUID, output: GoogleDriveOutput
    ) -> GoogleDriveFinalVideo | None:
        matches = self._find(job_id, output)
        if len(matches) > 1:
            raise DuplicateOutputArtifacts
        if len(matches) == 1 and _is_complete_drive_video(matches[0]):
            return _drive_final_video(matches[0])
        return None

    def _find(self, job_id: UUID, output: GoogleDriveOutput) -> list[dict[str, object]]:
        escaped_folder = _drive_query_value(output.folder_id)
        escaped_job_id = _drive_query_value(str(job_id))
        query = (
            f"'{escaped_folder}' in parents and trashed = false and "
            "appProperties has { "
            f"key='{self.APP_PROPERTY_KEY}' and value='{escaped_job_id}'"
            " }"
        )
        try:
            response = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields=f"files({_DRIVE_FINAL_FIELDS})",
                    pageSize=10,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:
            raise OutputUploadFailed from exc
        files = response.get("files") if isinstance(response, dict) else None
        if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
            raise OutputUploadFailed
        return files


def _google_drive_service(*, client_id: str, client_secret: str, refresh_token: str):
    if not all((client_id, client_secret, refresh_token)):
        raise ValueError("Worker Google Drive OAuth credentials are incomplete")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _r2_client(
    *, endpoint_url: str, bucket: str, access_key_id: str, secret_access_key: str
):
    if not all((endpoint_url, bucket, access_key_id, secret_access_key)):
        raise ValueError("Worker R2 credentials are incomplete")
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name="auto",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )


def _metadata_int(value: object) -> int | None:
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if type(value) is int:
        return value
    return None


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(io.DEFAULT_BUFFER_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


_DRIVE_FINAL_FIELDS = "id,headRevisionId,size,mimeType,md5Checksum"


def _is_complete_drive_video(metadata: dict[str, object]) -> bool:
    return (
        isinstance(metadata.get("id"), str)
        and isinstance(metadata.get("headRevisionId"), str)
        and _metadata_int(metadata.get("size")) not in {None, 0}
        and metadata.get("mimeType") == "video/mp4"
        and isinstance(metadata.get("md5Checksum"), str)
        and bool(metadata.get("md5Checksum"))
    )


def _drive_final_video(metadata: dict[str, object]) -> GoogleDriveFinalVideo:
    return GoogleDriveFinalVideo(
        type="google_drive",
        file_id=metadata["id"],
        head_revision_id=metadata["headRevisionId"],
        size_bytes=_metadata_int(metadata["size"]),
        mime_type="video/mp4",
        checksum={"algorithm": "md5", "value": metadata["md5Checksum"]},
    )


def _drive_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _clean_etag(value: object) -> str | None:
    return value.strip('"') if isinstance(value, str) and value else None


def _is_missing_s3_object(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    error = response.get("Error") if isinstance(response, dict) else None
    code = error.get("Code") if isinstance(error, dict) else None
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode") if isinstance(response, dict) else None
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404
