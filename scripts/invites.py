# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Manage signup invite codes in the app's database (FIRSTDEV_DATABASE_URL).

invites.py create --label "Dana (Wix)"   prints the code ONCE
invites.py list                          id, label, status, dates; never codes or hashes
invites.py revoke --id ID | --label L    revoke unused codes
"""

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from firstdev import invites
from firstdev.db import get_engine
from firstdev.models import InviteCode


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "-"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--label", required=True)
    sub.add_parser("list")
    r = sub.add_parser("revoke")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--label")
    args = p.parse_args(argv)

    with Session(get_engine()) as db:
        if args.cmd == "create":
            if not 1 <= len(args.label) <= 100:
                p.error("--label must be 1-100 characters")
            print(invites.create(db, args.label))
            print("Shown once; it cannot be recovered.", file=sys.stderr)
        elif args.cmd == "list":
            for row in db.scalars(select(InviteCode).order_by(InviteCode.created_at)):
                print(
                    f"{row.id}  {row.label}  {invites.status(row)}  "
                    f"created {_fmt(row.created_at)}  used {_fmt(row.used_at)}"
                )
        else:
            match = InviteCode.id == args.id if args.id else InviteCode.label == args.label
            res = db.execute(
                update(InviteCode)
                .where(match, InviteCode.used_at.is_(None), InviteCode.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
            db.commit()
            if res.rowcount == 0:
                print("no unused, unrevoked code matched", file=sys.stderr)
                return 1
            print(f"revoked {res.rowcount}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
