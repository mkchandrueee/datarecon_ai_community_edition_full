# datarecon/infrastructure/connectors/storage_client_factory.py  (NEW)
# Cloud storage connectivity (PRD Module 1: AWS S3, Azure Blob, ADLS Gen2, GCS).
# Secret material (secret key / SAS / account key / service-account JSON) is
# carried in Connection.password_encrypted and decrypted at the service boundary.
from __future__ import annotations

import builtins
import json
from io import BytesIO

from datarecon.domain.entities.connection import Connection
from datarecon.domain.enums import DatabaseType


class StorageClientFactory:
    """Uniform object-storage facade: download_object(), list_objects(), test()."""

    # ---------- public API ----------
    def download_object(self, c: Connection, key: str, secret: str = "") -> BytesIO:
        return self._impl(c)(c, secret).download(key)

    def list_objects(self, c: Connection, prefix: str, secret: str = "") -> list[str]:
        return self._impl(c)(c, secret).list(prefix)

    def test(self, c: Connection, secret: str = "") -> None:
        self._impl(c)(c, secret).list(prefix="")

    def _impl(self, c: Connection):
        impl = {
            DatabaseType.AWS_S3: _S3Client,
            DatabaseType.AZURE_BLOB: _AzureBlobClient,
            DatabaseType.AZURE_DATA_LAKE: _AdlsClient,
            DatabaseType.GCS: _GcsClient,
        }.get(c.database_type)
        if impl is None:
            raise ValueError(f"{c.database_type.value} is not a storage type.")
        return impl


class _S3Client:
    def __init__(self, c: Connection, secret: str):
        import boto3

        if not c.bucket:
            raise ValueError("S3 connection requires a bucket.")
        kwargs = {"region_name": c.region} if c.region else {}
        if c.username:  # username = access key id; secret = secret access key
            kwargs.update(aws_access_key_id=c.username, aws_secret_access_key=secret)
        endpoint = c.options().get("endpoint_url")
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        self._bucket = c.bucket
        self._client = boto3.client("s3", **kwargs)

    def download(self, key: str) -> BytesIO:
        buf = BytesIO()
        self._client.download_fileobj(self._bucket, key, buf)
        buf.seek(0)
        return buf

    def list(self, prefix: str) -> builtins.list[str]:
        resp = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix, MaxKeys=1000)
        return [o["Key"] for o in resp.get("Contents", [])]


class _AzureBlobClient:
    def __init__(self, c: Connection, secret: str):
        from azure.storage.blob import BlobServiceClient

        if not c.storage_account or not c.bucket:
            raise ValueError("Azure Blob requires a storage account and container.")
        url = f"https://{c.storage_account}.blob.core.windows.net"
        credential = secret or None  # account key or SAS token
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self._container = BlobServiceClient(
            account_url=url, credential=credential
        ).get_container_client(c.bucket)

    def download(self, key: str) -> BytesIO:
        buf = BytesIO(self._container.download_blob(key).readall())
        buf.seek(0)
        return buf

    def list(self, prefix: str) -> builtins.list[str]:
        return [
            b.name
            for _, b in zip(
                range(1000),
                self._container.list_blobs(name_starts_with=prefix),
                strict=False,
            )
        ]


class _AdlsClient:
    def __init__(self, c: Connection, secret: str):
        from azure.storage.filedatalake import DataLakeServiceClient

        if not c.storage_account or not c.bucket:
            raise ValueError("ADLS requires a storage account and filesystem.")
        url = f"https://{c.storage_account}.dfs.core.windows.net"
        credential = secret or None
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self._fs = DataLakeServiceClient(
            account_url=url, credential=credential
        ).get_file_system_client(c.bucket)

    def download(self, key: str) -> BytesIO:
        buf = BytesIO(self._fs.get_file_client(key).download_file().readall())
        buf.seek(0)
        return buf

    def list(self, prefix: str) -> builtins.list[str]:
        return [
            p.name
            for _, p in zip(
                range(1000),
                self._fs.get_paths(path=prefix or None),
                strict=False,
            )
        ]


class _GcsClient:
    def __init__(self, c: Connection, secret: str):
        from google.cloud import storage
        from google.oauth2 import service_account

        if not c.bucket:
            raise ValueError("GCS connection requires a bucket.")
        if secret:  # secret = full service-account JSON
            creds = service_account.Credentials.from_service_account_info(json.loads(secret))
            client = storage.Client(project=c.cloud_project, credentials=creds)
        else:
            client = storage.Client(project=c.cloud_project)
        self._bucket = client.bucket(c.bucket)

    def download(self, key: str) -> BytesIO:
        buf = BytesIO(self._bucket.blob(key).download_as_bytes())
        buf.seek(0)
        return buf

    def list(self, prefix: str) -> builtins.list[str]:
        return [
            b.name
            for b in self._bucket.client.list_blobs(self._bucket, prefix=prefix, max_results=1000)
        ]
