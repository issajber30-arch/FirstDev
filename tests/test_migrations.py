# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from conftest import ROOT
from sqlalchemy import CheckConstraint, inspect
from sqlalchemy.exc import IntegrityError

from firstdev.db import make_engine
from firstdev.models import Base


def _upgraded(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return cfg, make_engine(url)


def test_upgrade_matches_models(tmp_path):
    _, engine = _upgraded(tmp_path)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()


def test_check_constraints_match_models(tmp_path):
    # compare_metadata ignores CHECK constraints, so compare them explicitly.
    _, engine = _upgraded(tmp_path)
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        expected = {c.name for c in table.constraints if isinstance(c, CheckConstraint)}
        actual = {c["name"] for c in insp.get_check_constraints(table.name)}
        assert actual == expected, table.name
    engine.dispose()


def test_downgrade_to_base(tmp_path):
    cfg, engine = _upgraded(tmp_path)
    command.downgrade(cfg, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_connection_status_check_accepts_removed(tmp_path):
    # The CHECK widening is hand-written (autogenerate can't see it), so exercise it for real.
    from sqlalchemy import text

    _, engine = _upgraded(tmp_path)
    with engine.begin() as conn:
        for uid in ("a", "b"):
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, role, public_profile, created_at)"
                    " VALUES (:i, :i || '@x.com', 'h', 'developer', 0, '2026-01-01')"
                ),
                {"i": uid},
            )
        ins = (
            "INSERT INTO connections (id, requester_id, addressee_id, status, created_at)"
            " VALUES ('c', 'a', 'b', :s, '2026-01-01')"
        )
        conn.execute(text(ins), {"s": "removed"})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(ins.replace("'c'", "'d'").replace("'a', 'b'", "'b', 'a'")), {"s": "bogus"}
        )
    engine.dispose()
