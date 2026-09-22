from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from ai_video_editor.worker.contracts import (
    GoogleDriveOutput,
    GoogleDriveSource,
    S3ObjectReference,
)
from ai_video_editor.worker.providers import (
    ArtifactUploadFailed,
    DuplicateOutputArtifacts,
    GoogleDriveOutputProvider,
    GoogleDriveSourceProvider,
    ProcessedAudioDownloadFailed,
    ProcessedAudioMissing,
    R2AnalysisArtifactStore,
    R2ProcessedAudioProvider,
    SourceAccessDenied,
    SourceChanged,
    SourceDownloadFailed,
    SourceNotFound,
)


class Executable:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeDriveFiles:
    def __init__(self, metadata, content: bytes = b""):
        self.metadata = metadata
        self.content = content

    def get(self, **kwargs):
        del kwargs
        return Executable(self.metadata)

    def get_media(self, **kwargs):
        del kwargs
        return self.content


class FakeDriveService:
    def __init__(self, metadata, content: bytes = b""):
        self._files = FakeDriveFiles(metadata, content)

    def files(self):
        return self._files


def test_drive_metadata_mismatch_fails_before_media_download(tmp_path: Path) -> None:
    source = GoogleDriveSource(
        type="google_drive",
        file_id="file-1",
        head_revision_id="revision-1",
        size_bytes=4,
        mime_type="video/mp4",
        checksum={"algorithm": "md5", "value": "expected"},
    )
    provider = GoogleDriveSourceProvider(
        FakeDriveService(
            {
                "id": "file-1",
                "headRevisionId": "changed",
                "size": "4",
                "mimeType": "video/mp4",
                "md5Checksum": "expected",
            }
        )
    )

    with pytest.raises(SourceChanged):
        provider.download(source, tmp_path / "source.mp4")


def test_drive_download_verifies_metadata_and_downloaded_checksum(tmp_path: Path) -> None:
    content = b"video-bytes"
    checksum = hashlib.md5(content, usedforsecurity=False).hexdigest()
    source = GoogleDriveSource(
        type="google_drive",
        file_id="file-1",
        head_revision_id="revision-1",
        size_bytes=len(content),
        mime_type="video/mp4",
        checksum={"algorithm": "md5", "value": checksum},
    )
    provider = GoogleDriveSourceProvider(
        FakeDriveService(
            {
                "id": "file-1",
                "headRevisionId": "revision-1",
                "size": str(len(content)),
                "mimeType": "video/mp4",
                "md5Checksum": checksum,
            },
            content,
        )
    )

    class FakeDownload:
        def __init__(self, output, request):
            self.output = output
            self.request = request

        def next_chunk(self):
            self.output.write(self.request)
            return None, True

    destination = tmp_path / "source.mp4"
    with patch("googleapiclient.http.MediaIoBaseDownload", FakeDownload):
        assert provider.download(source, destination) == destination

    assert destination.read_bytes() == content


@pytest.mark.parametrize(
    ("status", "failure"),
    [
        (404, SourceNotFound),
        (403, SourceAccessDenied),
        (429, SourceDownloadFailed),
        (500, SourceDownloadFailed),
    ],
)
def test_drive_provider_maps_http_failures(status: int, failure) -> None:
    error = RuntimeError("provider response must not cross the boundary")
    error.resp = SimpleNamespace(status=status)

    with pytest.raises(failure):
        GoogleDriveSourceProvider._raise_drive_failure(error)


def test_r2_upload_returns_stable_verified_reference(tmp_path: Path) -> None:
    source = tmp_path / "artifact.flac"
    source.write_bytes(b"flac")

    class FakeS3:
        def __init__(self):
            self.upload = None

        def upload_file(self, filename, bucket, key, ExtraArgs):
            self.upload = (filename, bucket, key, ExtraArgs)

        def head_object(self, *, Bucket, Key):
            assert (Bucket, Key) == ("dev-bucket", "jobs/job/processed-audio.flac")
            return {
                "ContentLength": 4,
                "ContentType": "audio/flac",
                "ETag": '"etag-value"',
            }

    client = FakeS3()
    result = R2AnalysisArtifactStore(client, bucket="dev-bucket").upload(
        source,
        key="jobs/job/processed-audio.flac",
        mime_type="audio/flac",
    )

    assert result.key == "jobs/job/processed-audio.flac"
    assert result.etag == "etag-value"
    assert result.size_bytes == source.stat().st_size
    assert result.mime_type == "audio/flac"
    assert client.upload[3] == {"ContentType": "audio/flac"}


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "ContentLength": 3,
            "ContentType": "audio/flac",
            "ETag": '"etag-value"',
        },
        {
            "ContentLength": 4,
            "ContentType": "application/octet-stream",
            "ETag": '"etag-value"',
        },
        {"ContentLength": 4, "ETag": '"etag-value"'},
    ],
    ids=["size-mismatch", "mime-mismatch", "mime-missing"],
)
def test_r2_upload_rejects_unverified_size_or_mime(
    metadata: dict[str, object], tmp_path: Path
) -> None:
    source = tmp_path / "artifact.flac"
    source.write_bytes(b"flac")

    class FakeS3:
        def upload_file(self, *args, **kwargs):
            del args, kwargs

        def head_object(self, **kwargs):
            del kwargs
            return metadata

    with pytest.raises(ArtifactUploadFailed) as failure:
        R2AnalysisArtifactStore(FakeS3(), bucket="dev-bucket").upload(
            source,
            key="jobs/job/processed-audio.flac",
            mime_type="audio/flac",
        )

    assert str(failure.value) == "Analysis artifact upload could not be verified"


def test_r2_processed_audio_download_verifies_manifest(tmp_path: Path) -> None:
    reference = _processed_audio_reference()

    class FakeS3:
        def head_object(self, *, Bucket, Key):
            assert (Bucket, Key) == ("dev-bucket", reference.key)
            return {
                "ContentLength": 4,
                "ContentType": "audio/flac",
                "ETag": '"etag-1"',
            }

        def download_file(self, bucket, key, filename):
            assert (bucket, key) == ("dev-bucket", reference.key)
            Path(filename).write_bytes(b"flac")

    destination = tmp_path / "processed.flac"
    provider = R2ProcessedAudioProvider(FakeS3(), bucket="dev-bucket")
    assert provider.download(reference, destination) == destination
    assert destination.read_bytes() == b"flac"


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        ("NoSuchKey", ProcessedAudioMissing),
        ("AccessDenied", ProcessedAudioDownloadFailed),
    ],
)
def test_r2_processed_audio_maps_provider_failures(
    error_code, expected, tmp_path: Path
) -> None:
    class ProviderError(Exception):
        response = {"Error": {"Code": error_code}}

    class FakeS3:
        def head_object(self, **kwargs):
            del kwargs
            raise ProviderError

    with pytest.raises(expected):
        R2ProcessedAudioProvider(FakeS3(), bucket="dev-bucket").download(
            _processed_audio_reference(), tmp_path / "processed.flac"
        )


def _processed_audio_reference() -> S3ObjectReference:
    return S3ObjectReference(
        type="s3_object",
        key="jobs/analysis/processed.flac",
        size_bytes=4,
        mime_type="audio/flac",
        etag="etag-1",
    )


class FakeDriveOutputFiles:
    def __init__(
        self,
        source: Path,
        *,
        create_unknown: bool = False,
        update_unknown: bool = False,
    ):
        self.source = source
        self.create_unknown = create_unknown
        self.update_unknown = update_unknown
        self.matches: list[dict[str, object]] = []
        self.created = 0
        self.updated_file_ids: list[str] = []

    def list(self, **kwargs):
        del kwargs
        return Executable({"files": [dict(item) for item in self.matches]})

    def create(self, **kwargs):
        body = kwargs["body"]
        self.created += 1
        marker = {
            "id": "stable-file-id",
            "headRevisionId": "empty-revision",
            "size": "0",
            "mimeType": body["mimeType"],
            "md5Checksum": hashlib.md5(b"", usedforsecurity=False).hexdigest(),
        }
        self.matches = [marker]

        class Create:
            def execute(inner_self):
                del inner_self
                if self.create_unknown:
                    raise RuntimeError("unknown create outcome")
                return {"id": marker["id"]}

        return Create()

    def update(self, **kwargs):
        file_id = kwargs["fileId"]
        self.updated_file_ids.append(file_id)

        class Update:
            def next_chunk(inner_self):
                del inner_self
                content = self.source.read_bytes()
                self.matches = [
                    {
                        "id": file_id,
                        "headRevisionId": "final-revision",
                        "size": str(len(content)),
                        "mimeType": "video/mp4",
                        "md5Checksum": hashlib.md5(
                            content, usedforsecurity=False
                        ).hexdigest(),
                    }
                ]
                if self.update_unknown:
                    raise RuntimeError("unknown update outcome")
                return None, dict(self.matches[0])

        return Update()


class FakeDriveOutputService:
    def __init__(self, files: FakeDriveOutputFiles):
        self._files = files

    def files(self):
        return self._files


def _drive_output() -> GoogleDriveOutput:
    return GoogleDriveOutput(
        type="google_drive",
        folder_id="folder-1",
        display_name="final.mp4",
    )


@pytest.mark.parametrize(
    ("create_unknown", "update_unknown"),
    [(False, False), (True, False), (False, True)],
)
def test_drive_output_create_empty_then_resumable_update_recovers_unknown_outcomes(
    create_unknown: bool,
    update_unknown: bool,
    tmp_path: Path,
) -> None:
    rendered = tmp_path / "rendered.mp4"
    rendered.write_bytes(b"rendered-video")
    files = FakeDriveOutputFiles(
        rendered,
        create_unknown=create_unknown,
        update_unknown=update_unknown,
    )
    provider = GoogleDriveOutputProvider(FakeDriveOutputService(files))

    result = provider.upload(uuid4(), rendered, _drive_output())

    assert result.file_id == "stable-file-id"
    assert files.created == 1
    assert files.updated_file_ids == ["stable-file-id"]
    assert result.checksum.value == hashlib.md5(
        rendered.read_bytes(), usedforsecurity=False
    ).hexdigest()


def test_drive_output_uuid_lookup_reuses_one_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    rendered = tmp_path / "rendered.mp4"
    rendered.write_bytes(b"rendered-video")
    files = FakeDriveOutputFiles(rendered)
    complete = {
        "id": "stable-file-id",
        "headRevisionId": "final-revision",
        "size": str(rendered.stat().st_size),
        "mimeType": "video/mp4",
        "md5Checksum": hashlib.md5(
            rendered.read_bytes(), usedforsecurity=False
        ).hexdigest(),
    }
    files.matches = [complete]
    provider = GoogleDriveOutputProvider(FakeDriveOutputService(files))

    assert provider.find_completed(uuid4(), _drive_output()).file_id == "stable-file-id"
    files.matches = [complete, {**complete, "id": "duplicate-id"}]
    with pytest.raises(DuplicateOutputArtifacts):
        provider.find_completed(uuid4(), _drive_output())


@pytest.mark.parametrize("provider_type", [GoogleDriveSourceProvider, GoogleDriveOutputProvider])
def test_drive_factories_share_oauth_configuration(provider_type):
    with patch("googleapiclient.discovery.build") as build:
        provider = provider_type.from_oauth(
            client_id="fake-client-id", client_secret="fake-client-secret",
            refresh_token="fake-refresh-token",
        )
    assert provider._service is build.return_value
    args, kwargs = build.call_args
    assert args == ("drive", "v3")
    assert kwargs["cache_discovery"] is False
    credentials = kwargs["credentials"]
    assert credentials.client_id == "fake-client-id"
    assert credentials.client_secret == "fake-client-secret"
    assert credentials.refresh_token == "fake-refresh-token"
    assert credentials.scopes == ["https://www.googleapis.com/auth/drive"]
    with pytest.raises(ValueError, match="incomplete"):
        provider_type.from_oauth(client_id="fake-client-id", client_secret="", refresh_token="")


@pytest.mark.parametrize("provider_type", [R2AnalysisArtifactStore, R2ProcessedAudioProvider])
def test_r2_factories_share_endpoint_and_credentials(provider_type):
    with patch("boto3.client") as client:
        provider = provider_type.from_credentials(
            endpoint_url="https://test.r2.cloudflarestorage.com", bucket="test-bucket",
            access_key_id="fake-access-key", secret_access_key="fake-secret-key",
        )
    assert provider._client is client.return_value
    assert provider._bucket == "test-bucket"
    client.assert_called_once_with(
        "s3", endpoint_url="https://test.r2.cloudflarestorage.com", region_name="auto",
        aws_access_key_id="fake-access-key", aws_secret_access_key="fake-secret-key",
    )
    with pytest.raises(ValueError, match="incomplete"):
        provider_type.from_credentials(endpoint_url="", bucket="test-bucket", access_key_id="", secret_access_key="")
