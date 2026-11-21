"""
- Deliver alert JSON to a configured webhook using HTTPS.
- Persist delivery IDs, payloads, and attempt counts across command restarts.
- Retry transient failures with the same idempotency key.
"""

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from production.category_03_reliability_and_access.oidc import validate_endpoint


class DeliveryFailed(RuntimeError):
    """The webhook could not be confirmed within the delivery attempt budget."""


class NoRedirect(HTTPRedirectHandler):
    """Prevent webhook credentials from following redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Require the configured destination to respond directly."""
        return None


class WebhookNotifier:
    """
    - Persist immutable alert deliveries in a separate SQLite database.
    - Mark successful delivery only after a 2xx response.
    - Preserve one delivery ID through retries and ambiguous network failures.
    """

    def __init__(
        self, url: str, database: Path, *, token: str = "",
        allow_local_http: bool = False,
    ) -> None:
        """
        - Validate the destination and configure bounded HTTP requests.
        - Initialize the durable delivery ledger.
        """
        validate_endpoint(url, allow_local_http)
        self.url = url
        self.database = database
        self.token = token
        self.opener = build_opener(NoRedirect())
        with self.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    delivery_id TEXT PRIMARY KEY NOT NULL,
                    destination_hash TEXT NOT NULL,
                    alerts_json TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK (state IN ('pending', 'sent', 'failed')),
                    last_error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Commit ledger updates and close each connection after use."""
        with closing(sqlite3.connect(self.database, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection

    @classmethod
    def from_environment(cls) -> "WebhookNotifier":
        """Read an explicitly configured webhook and ledger destination."""
        url = os.environ.get("FEEDBACK_ALERT_WEBHOOK_URL", "")
        if not url:
            raise ValueError("Set FEEDBACK_ALERT_WEBHOOK_URL before using --notify.")
        return cls(
            url, Path(os.environ.get("FEEDBACK_NOTIFICATIONS_DB", "notifications.sqlite3")),
            token=os.environ.get("FEEDBACK_ALERT_WEBHOOK_TOKEN", ""),
            allow_local_http=os.environ.get("FEEDBACK_ALERT_ALLOW_LOCAL_HTTP") == "1",
        )

    def deliver(self, alerts: list[dict], delivery_id: str | None = None) -> str:
        """
        - Save an immutable payload before attempting HTTP delivery.
        - Return immediately when the same delivery was already confirmed.
        - Reserve at most three attempts across calls for the same delivery ID.
        """
        delivery_id = delivery_id or uuid4().hex
        if not delivery_id.strip() or not delivery_id.isascii() or any(
            ord(character) < 33 or ord(character) > 126 for character in delivery_id
        ):
            raise ValueError("delivery_id must contain printable ASCII without spaces.")
        destination_hash = hashlib.sha256(self.url.encode("utf-8")).hexdigest()
        alerts_json = json.dumps(alerts, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload = json.dumps({
            "delivery_id": delivery_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "alerts": alerts,
        }, sort_keys=True, allow_nan=False)
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            saved = connection.execute(
                "SELECT * FROM notification_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if saved is None:
                connection.execute(
                    """
                    INSERT INTO notification_deliveries
                        (delivery_id, destination_hash, alerts_json, payload)
                    VALUES (?, ?, ?, ?)
                    """,
                    (delivery_id, destination_hash, alerts_json, payload),
                )
            else:
                if saved["destination_hash"] != destination_hash or saved["alerts_json"] != alerts_json:
                    raise ValueError("The delivery ID already references different content.")
                payload = saved["payload"]
                if saved["state"] == "sent":
                    return delivery_id

        while True:
            with self.connection() as connection:
                rows = connection.execute(
                    """
                    UPDATE notification_deliveries
                    SET attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE delivery_id = ? AND state = 'pending' AND attempts < 3
                    RETURNING attempts
                    """,
                    (delivery_id,),
                ).fetchall()
                if not rows:
                    saved = connection.execute(
                        "SELECT state FROM notification_deliveries WHERE delivery_id = ?",
                        (delivery_id,),
                    ).fetchone()
                    if saved["state"] == "sent":
                        return delivery_id
                    raise DeliveryFailed(f"Delivery {delivery_id} has no attempts remaining.")
                attempt = rows[0]["attempts"]

            headers = {
                "Content-Type": "application/json",
                "Idempotency-Key": delivery_id,
                "X-Delivery-ID": delivery_id,
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            request = Request(self.url, data=payload.encode("utf-8"), headers=headers)
            retryable = False
            failure = None
            try:
                with self.opener.open(request, timeout=5) as response:
                    if not 200 <= response.status < 300:
                        raise DeliveryFailed("Unexpected webhook response.")
            except HTTPError as error:
                failure = f"HTTP{error.code}"
                retryable = error.code == 429 or 500 <= error.code < 600
                error.close()
            except (URLError, OSError) as error:
                failure = type(error).__name__
                retryable = True

            if failure is None:
                with self.connection() as connection:
                    connection.execute(
                        """
                        UPDATE notification_deliveries SET state = 'sent',
                            last_error = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE delivery_id = ?
                        """,
                        (delivery_id,),
                    )
                return delivery_id

            with self.connection() as connection:
                connection.execute(
                    """
                    UPDATE notification_deliveries SET last_error = ?,
                        state = CASE WHEN state = 'sent' THEN 'sent' ELSE ? END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE delivery_id = ?
                    """,
                    (failure, "pending" if retryable and attempt < 3 else "failed", delivery_id),
                )
            if not retryable or attempt >= 3:
                raise DeliveryFailed(f"Delivery {delivery_id} failed with {failure}.")
            time.sleep(0.1 * 2 ** (attempt - 1))
