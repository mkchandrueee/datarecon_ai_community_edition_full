# datarecon/infrastructure/connectors/mongodb_connector.py  (NEW)
from __future__ import annotations

from typing import Any

from datarecon.domain.entities.connection import Connection


class MongoDBConnector:
    """MongoDB client factory (PRD Module 1)."""

    def create_client(self, c: Connection, plaintext_password: str = "") -> Any:
        from pymongo import MongoClient

        opts = c.options()
        uri = opts.get("uri")
        if uri:
            return MongoClient(uri, serverSelectionTimeoutMS=10_000)
        scheme = "mongodb+srv" if opts.get("srv") else "mongodb"
        kwargs: dict[str, Any] = {
            "host": f"{scheme}://{c.host}"
            + ("" if opts.get("srv") or not c.port else f":{c.port}"),
            "serverSelectionTimeoutMS": 10_000,
        }
        if c.username:
            kwargs.update(
                username=c.username,
                password=plaintext_password,
                authSource=opts.get("auth_source", c.database_name or "admin"),
            )
        return MongoClient(**kwargs)

    def test(self, c: Connection, plaintext_password: str = "") -> None:
        client = self.create_client(c, plaintext_password)
        try:
            client.admin.command("ping")
        finally:
            client.close()
