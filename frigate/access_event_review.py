"""Shared access-event queries and transactional administrator decisions."""

import time
from contextlib import contextmanager

from peewee import fn
from playhouse.sqlite_ext import SqliteExtDatabase
from playhouse.sqliteq import SqliteQueueDatabase

from frigate.models import AccessEvent, AccessEventReview

FINAL_STATUSES = ("valid", "warning", "unknown")
DOOR_EVENT_CODES = ("DoorStatus", "DoorCard", "KeepLightOn", "DoorOpen", "DoorClose")


@contextmanager
def access_event_transaction():
    """Use a dedicated writer because queued SQLite does not support atomic()."""
    database = AccessEvent._meta.database
    if isinstance(database, SqliteQueueDatabase):
        transaction_db = SqliteExtDatabase(
            database.database,
            timeout=60,
            pragmas={"foreign_keys": 1},
        )
        with transaction_db.connection_context(), transaction_db.atomic("IMMEDIATE"):
            yield transaction_db
    else:
        with database.atomic("IMMEDIATE"):
            yield database


def granted_events():
    """Select normalized grants, excluding controller door-state messages."""
    return AccessEvent.select().where(
        (AccessEvent.raw_record["status"] == "OK")
        & ~AccessEvent.raw_record["event_code"].in_(DOOR_EVENT_CODES)
    )


def filter_access_events(
    query,
    *,
    start=None,
    end=None,
    device_id=None,
    name=None,
    user_id=None,
    card_no=None,
    door_id=None,
    camera=None,
    source=None,
    reviewed=None,
):
    """Apply identical search constraints to review results and status counts."""
    if start is not None:
        query = query.where(AccessEvent.occurred_at >= start)
    if end is not None:
        query = query.where(AccessEvent.occurred_at <= end)
    if device_id:
        query = query.where(AccessEvent.device_id == device_id)
    if camera:
        query = query.where(AccessEvent.camera == camera)
    if door_id is not None:
        query = query.where(AccessEvent.raw_record["door_id"].cast("text") == door_id)
    if source:
        query = query.where(
            fn.COALESCE(AccessEvent.raw_record["_source"], "controller") == source
        )
    if reviewed is not None:
        query = query.where(AccessEvent.review_status.is_null(not reviewed))
    for value, key in (
        (name, "user_name"),
        (user_id, "user_id"),
        (card_no, "card_number"),
    ):
        if value and value.strip():
            query = query.where(
                fn.INSTR(
                    fn.LOWER(fn.COALESCE(AccessEvent.raw_record[key].cast("text"), "")),
                    value.strip().lower(),
                )
                > 0
            )
    return query


class AccessReviewError(Exception):
    """A stable API failure for missing, unfinished, or stale events."""

    def __init__(self, reason: str, status_code: int):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


def submit_access_review(
    event_id: str,
    reviewer: str,
    action: str,
    classification: str | None,
    expected_revision: int,
) -> None:
    """Atomically update the shared decision and append its audit history."""
    with access_event_transaction() as database:
        event = (
            AccessEvent.select()
            .where(AccessEvent.id == event_id)
            .bind(database)
            .first()
        )
        if event is None:
            raise AccessReviewError("event_not_found", 404)
        if event.review_revision != expected_revision:
            raise AccessReviewError("review_conflict", 409)
        if (
            event.raw_record.get("status") != "OK"
            or event.raw_record.get("event_code") in DOOR_EVENT_CODES
            or event.verification_status not in FINAL_STATUSES
        ):
            raise AccessReviewError("event_not_ready", 409)
        status = event.verification_status if action == "confirm" else classification
        if action not in ("confirm", "correct") or status not in FINAL_STATUSES:
            raise AccessReviewError("invalid_review", 422)
        reviewed_at = time.time()
        updated = (
            AccessEvent.update(
                review_status=status,
                reviewed_at=reviewed_at,
                reviewed_by=reviewer,
                review_revision=expected_revision + 1,
            )
            .where(
                (AccessEvent.id == event_id)
                & (AccessEvent.review_revision == expected_revision)
            )
            .bind(database)
            .execute()
        )
        if updated != 1:
            raise AccessReviewError("review_conflict", 409)
        AccessEventReview.insert(
            event_id=event_id,
            revision=expected_revision + 1,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            previous_status=event.review_status or event.verification_status,
            status=status,
            action=action,
        ).bind(database).execute()
