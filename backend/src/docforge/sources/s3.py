from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import Any

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from docforge.errors import SourceUnavailableError
from docforge.sources.base import SourceObject, in_scope, is_supported, normalize_prefix


class S3Source:
    """S3-compatible source (AWS S3, MinIO).

    The ETag is used as the listing fingerprint so a scan never downloads unchanged objects.
    Multipart uploads can change the ETag without changing the bytes; the detect stage catches
    that case by comparing the real SHA-256.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        name: str = "s3",
    ) -> None:
        self.name = name
        self._bucket = bucket
        self._prefix = normalize_prefix(prefix)
        self._endpoint_url = endpoint_url
        self._session = aioboto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )
        self._config = Config(
            retries={"max_attempts": 3, "mode": "standard"}, s3={"addressing_style": "path"}
        )

    def _client(self) -> Any:
        return self._session.client("s3", endpoint_url=self._endpoint_url, config=self._config)

    def uri_scope(self, prefix: str) -> str:
        return "/".join(part for part in (self._prefix, normalize_prefix(prefix)) if part)

    async def list_objects(self, prefix: str = "") -> AsyncIterator[SourceObject]:
        full_prefix = self.uri_scope(prefix)
        try:
            async with self._client() as client:
                paginator = client.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                    for item in page.get("Contents", []):
                        key: str = item["Key"]
                        if not in_scope(key, full_prefix) or not is_supported(key):
                            continue
                        etag = str(item["ETag"]).strip('"')
                        yield SourceObject(
                            source=self.name,
                            uri=key,
                            filename=PurePosixPath(key).name,
                            size_bytes=int(item["Size"]),
                            fingerprint=f"etag:{etag}",
                            modified_at=item.get("LastModified"),
                        )
        except (BotoCoreError, ClientError) as exc:
            raise SourceUnavailableError(f"cannot list s3://{self._bucket}/{full_prefix}: {exc}") from exc

    async def read(self, uri: str) -> bytes:
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self._bucket, Key=uri)
                async with response["Body"] as body:
                    data: bytes = await body.read()
                    return data
        except (BotoCoreError, ClientError) as exc:
            raise SourceUnavailableError(f"cannot read s3://{self._bucket}/{uri}: {exc}") from exc
