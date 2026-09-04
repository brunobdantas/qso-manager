import warnings

import pytest
from sqlalchemy.exc import SAWarning

from acceptance._helpers import adif_record, import_records, reconcile, logical_source_names


def test_identity_is_created_and_linked_to_materialized_qso(db):
    from app.models.models import QSOIdentity, LogicalQSO

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120010")])
    reconcile(db)

    identities = db.query(QSOIdentity).all()
    logicals = db.query(LogicalQSO).all()
    assert len(identities) == 1, "One real QSO must create exactly one persistent QSOIdentity"
    assert len(logicals) == 1
    assert logicals[0].qso_identity_id == identities[0].id


def test_identity_survives_reconciliation_and_new_source(db):
    from app.models.models import QSOIdentity, LogicalQSO, QSOSourceLink

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120010")])
    reconcile(db)
    first = db.query(QSOIdentity).one().uuid

    reconcile(db)
    assert db.query(QSOIdentity).one().uuid == first

    import_records(db, "MSHV", [adif_record(time_on="120005")])
    reconcile(db)

    assert db.query(QSOIdentity).count() == 1
    assert db.query(QSOIdentity).one().uuid == first
    assert db.query(LogicalQSO).count() == 1
    assert db.query(QSOSourceLink).count() == 3
    assert logical_source_names(db.query(LogicalQSO).one()) == {"QRZ", "WRL", "MSHV"}


def test_two_real_qsos_same_call_day_keep_distinct_identities(db):
    from app.models.models import QSOIdentity, LogicalQSO

    import_records(
        db,
        "QRZ",
        [adif_record(time_on="120000"), adif_record(time_on="180000")],
    )
    reconcile(db)
    assert db.query(LogicalQSO).count() == 2
    assert db.query(QSOIdentity).count() == 2
    assert len({row.uuid for row in db.query(QSOIdentity).all()}) == 2


def test_identity_survives_database_restart(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.models.models import QSOIdentity, LogicalQSO

    path = tmp_path / "identity-restart.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    db1 = Session()
    import_records(db1, "QRZ", [adif_record(time_on="120000")])
    import_records(db1, "WRL", [adif_record(time_on="120010")])
    reconcile(db1)
    identity_uuid = db1.query(QSOIdentity).one().uuid
    db1.commit()
    db1.close()
    engine.dispose()

    engine2 = create_engine(f"sqlite:///{path}")
    Session2 = sessionmaker(bind=engine2, expire_on_commit=False)
    db2 = Session2()
    assert db2.query(QSOIdentity).one().uuid == identity_uuid
    assert db2.query(LogicalQSO).one().qso_identity_id == db2.query(QSOIdentity).one().id
    db2.close()
    engine2.dispose()


def test_reconciliation_is_idempotent_and_history_grows(db):
    from app.models.models import LogicalQSO, QSOSourceLink, ReconciliationRun

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120010")])
    for expected_runs in (1, 2, 3):
        reconcile(db)
        assert db.query(LogicalQSO).count() == 1
        assert db.query(QSOSourceLink).count() == 2
        assert db.query(ReconciliationRun).count() == expected_runs


def test_complete_link_prevents_transitive_auto_merge(db):
    from app.models.models import LogicalQSO

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120050")])
    import_records(db, "MSHV", [adif_record(time_on="120140")])
    reconcile(db)

    source_sets = [logical_source_names(lq) for lq in db.query(LogicalQSO).all()]
    assert not any(s == {"QRZ", "WRL", "MSHV"} for s in source_sets)


def test_atomic_rebuild_has_no_identity_map_conflict_warning(db):
    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120010")])
    reconcile(db)
    import_records(db, "MSHV", [adif_record(time_on="120005")])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", SAWarning)
        reconcile(db)
    conflicts = [w for w in caught if "Identity map already had an identity" in str(w.message)]
    assert not conflicts, f"Atomic rebuild emitted SQLAlchemy identity-map conflicts: {[str(w.message) for w in conflicts]}"
