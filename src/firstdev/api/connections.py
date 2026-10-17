# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Connections between users of the same world. Anyone may ask anyone, with harassment limits."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.db import get_db
from firstdev.models import Connection, ConnectionStatus, DeveloperProfile, User
from firstdev.worlds import in_world, same_world

router = APIRouter()

DAILY_REQUESTS = 50
DECLINE_COOLDOWN = timedelta(days=30)
# One message for "already connected/pending" and "declined recently", so a requester can't
# learn that they were declined.
UNAVAILABLE = "connection request not possible"

S = ConnectionStatus


class ConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(min_length=1, max_length=36)


class ConnectionOut(BaseModel):
    connection_id: str
    status: ConnectionStatus


class PersonOut(BaseModel):
    """The other party, as an allowlist: no email, no profile details beyond the headline."""

    connection_id: str
    user_id: str
    display_name: str | None
    handle: str | None
    headline: str | None


class PendingOut(PersonOut):
    created_at: datetime


class RequestsOut(BaseModel):
    incoming: list[PendingOut]
    outgoing: list[PendingOut]


def create_request(db: Session, me: User, target_id: str, *, now: datetime) -> Connection:
    """Open a request; `now` is a parameter so the 24h and 30-day windows are testable."""
    if target_id == me.id:
        raise HTTPException(422, "cannot connect to yourself")
    if not in_world(db, target_id, me):  # missing and other-world targets look identical
        raise HTTPException(404, "not found")
    sent = db.scalar(
        select(func.count())
        .select_from(Connection)
        .where(Connection.requester_id == me.id, Connection.created_at > now - timedelta(hours=24))
    )
    if sent >= DAILY_REQUESTS:
        raise HTTPException(429, "daily connection request limit reached")
    pair = db.scalars(
        select(Connection).where(
            or_(
                (Connection.requester_id == me.id) & (Connection.addressee_id == target_id),
                (Connection.requester_id == target_id) & (Connection.addressee_id == me.id),
            )
        )
    ).all()
    for c in pair:  # either direction
        if c.status in (S.pending, S.accepted):
            raise HTTPException(409, UNAVAILABLE)
        if c.status == S.declined and now - (c.responded_at or c.created_at) < DECLINE_COOLDOWN:
            raise HTTPException(409, UNAVAILABLE)
    # (requester, addressee) is unique, so a finished request in the same direction is reopened.
    conn = next((c for c in pair if c.requester_id == me.id), None)
    if conn is None:
        conn = Connection(requester_id=me.id, addressee_id=target_id)
        db.add(conn)
    conn.status, conn.created_at, conn.responded_at = S.pending, now, None
    try:
        db.commit()
    except IntegrityError:  # concurrent duplicate
        db.rollback()
        raise HTTPException(409, UNAVAILABLE) from None
    return conn


def _party(db: Session, conn_id: str, me: User, *, addressee: bool) -> Connection:
    """The connection if `me` is its addressee (or either party) and the other side is in
    the caller's world; 404 otherwise."""
    cond = (
        Connection.addressee_id == me.id
        if addressee
        else or_(Connection.requester_id == me.id, Connection.addressee_id == me.id)
    )
    conn = db.scalar(select(Connection).where(Connection.id == conn_id, cond))
    if conn is None:
        raise HTTPException(404, "not found")
    other = conn.addressee_id if conn.requester_id == me.id else conn.requester_id
    if not in_world(db, other, me):  # defence in depth: such a row should never exist
        raise HTTPException(404, "not found")
    return conn


def respond(db: Session, conn_id: str, me: User, *, accept: bool, now: datetime) -> Connection:
    conn = _party(db, conn_id, me, addressee=True)
    if conn.status != S.pending:
        raise HTTPException(409, f"connection is already {conn.status}")
    conn.status, conn.responded_at = (S.accepted if accept else S.declined), now
    db.commit()
    return conn


@router.post("/connections", status_code=201, response_model=ConnectionOut)
def request_connection(
    body: ConnectIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> ConnectionOut:
    c = create_request(db, user, body.user_id, now=datetime.now(UTC))
    return ConnectionOut(connection_id=c.id, status=c.status)


@router.post("/connections/{conn_id}/accept", response_model=ConnectionOut)
def accept(
    conn_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> ConnectionOut:
    c = respond(db, conn_id, user, accept=True, now=datetime.now(UTC))
    return ConnectionOut(connection_id=c.id, status=c.status)


@router.post("/connections/{conn_id}/decline", response_model=ConnectionOut)
def decline(
    conn_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> ConnectionOut:
    c = respond(db, conn_id, user, accept=False, now=datetime.now(UTC))
    return ConnectionOut(connection_id=c.id, status=c.status)


@router.delete("/connections/{conn_id}", status_code=204)
def remove(
    conn_id: str, user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> None:
    conn = _party(db, conn_id, user, addressee=False)
    # Either party may end an accepted connection; only the requester may cancel a pending one
    # (the addressee must decline, which starts the cooldown). Declined rows stay for the cooldown.
    if not (
        conn.status == S.accepted or (conn.status == S.pending and conn.requester_id == user.id)
    ):
        raise HTTPException(404, "not found")
    conn.status, conn.responded_at = S.removed, datetime.now(UTC)
    db.commit()


def _people(db: Session, me: User, status: ConnectionStatus, *where) -> list[tuple]:
    other = case((Connection.requester_id == me.id, Connection.addressee_id),
                 else_=Connection.requester_id)  # fmt: skip
    stmt = (
        select(Connection, User, DeveloperProfile.headline)
        .join(User, User.id == other)
        .outerjoin(DeveloperProfile, DeveloperProfile.user_id == User.id)
        .where(Connection.status == status, *where)
        .order_by(Connection.created_at.desc())
    )
    return list(db.execute(same_world(stmt, other, me)))


@router.get("/me/connections", response_model=list[PersonOut])
def my_connections(
    user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> list[PersonOut]:
    rows = _people(
        db,
        user,
        S.accepted,
        or_(Connection.requester_id == user.id, Connection.addressee_id == user.id),
    )
    return [
        PersonOut(connection_id=c.id, user_id=u.id, display_name=u.display_name,
                  handle=u.handle, headline=h)
        for c, u, h in rows
    ]  # fmt: skip


@router.get("/me/connection-requests", response_model=RequestsOut)
def my_requests(
    user: User = Depends(auth.current_user), db: Session = Depends(get_db)
) -> RequestsOut:
    def pending(*where) -> list[PendingOut]:
        return [
            PendingOut(connection_id=c.id, user_id=u.id, display_name=u.display_name,
                       handle=u.handle, headline=h, created_at=c.created_at)
            for c, u, h in _people(db, user, S.pending, *where)
        ]  # fmt: skip

    return RequestsOut(
        incoming=pending(Connection.addressee_id == user.id),
        outgoing=pending(Connection.requester_id == user.id),
    )
