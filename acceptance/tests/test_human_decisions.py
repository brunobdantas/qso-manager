import importlib

import pytest

from acceptance._helpers import adif_record, import_records, reconcile


def _logical_uuid_and_identity(db):
    from app.models.models import LogicalQSO, QSOIdentity

    lq = db.query(LogicalQSO).one()
    assert lq.qso_identity_id is not None, "LogicalQSO must be linked to persistent QSOIdentity before human decisions"
    identity = db.query(QSOIdentity).filter(QSOIdentity.id == lq.qso_identity_id).one()
    return lq.uuid, identity


def test_manual_override_survives_reconciliation_and_cluster_evolution(db):
    from app.models.models import LogicalQSO, LogicalQSOFieldOverride, QSOIdentity
    from app.services.safe_update_service import SafeUpdateService

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120010")])
    reconcile(db)
    lq_uuid, identity = _logical_uuid_and_identity(db)
    identity_uuid = identity.uuid

    updated = SafeUpdateService(db).apply_safe_update(
        lq_uuid, {"county": "Campinas"}, "acceptance manual correction"
    )
    assert updated.county == "Campinas"
    overrides = db.query(LogicalQSOFieldOverride).all()
    assert len(overrides) == 1, "apply_safe_update must persist a LogicalQSOFieldOverride"
    assert overrides[0].qso_identity_id == identity.id

    reconcile(db)
    lq = db.query(LogicalQSO).one()
    assert lq.county == "Campinas"
    assert db.query(QSOIdentity).one().uuid == identity_uuid
    provenance = lq.field_provenance or {}
    assert provenance.get("county", {}).get("source") == "MANUAL_OVERRIDE"

    import_records(db, "MSHV", [adif_record(time_on="120005")])
    reconcile(db)
    lq = db.query(LogicalQSO).one()
    assert lq.county == "Campinas"
    assert db.query(QSOIdentity).one().uuid == identity_uuid
    assert db.query(LogicalQSOFieldOverride).count() == 1


def test_manual_override_survives_restart(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.models.models import LogicalQSO, LogicalQSOFieldOverride
    from app.services.safe_update_service import SafeUpdateService

    path = tmp_path / "override-restart.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120010")])
    reconcile(db)
    lq = db.query(LogicalQSO).one()
    SafeUpdateService(db).apply_safe_update(lq.uuid, {"county": "Campinas"}, "restart test")
    db.close()
    engine.dispose()

    engine2 = create_engine(f"sqlite:///{path}")
    Session2 = sessionmaker(bind=engine2, expire_on_commit=False)
    db2 = Session2()
    assert db2.query(LogicalQSOFieldOverride).count() == 1
    reconcile(db2)
    assert db2.query(LogicalQSO).one().county == "Campinas"
    db2.close()
    engine2.dispose()


def test_all_update_paths_reject_protected_and_unknown_fields(db):
    from app.models.models import LogicalQSO
    from app.services.safe_update_service import SafeUpdateService
    from app.services.qso_update_service import QSOUpdateService

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    reconcile(db)
    lq = db.query(LogicalQSO).one()
    original_uuid = lq.uuid

    safe = SafeUpdateService(db)
    for method in (safe.build_safe_update, safe.apply_safe_update):
        with pytest.raises(ValueError):
            method(original_uuid, {"uuid": "evil"}, "protected")
        with pytest.raises(ValueError):
            method(original_uuid, {"field_does_not_exist": "x"}, "unknown")

    update = QSOUpdateService(db)
    with pytest.raises(ValueError):
        update.update_by_uuid(original_uuid, {"uuid": "evil"}, reason="protected")
    with pytest.raises(ValueError):
        update.update_by_uuid(original_uuid, {"field_does_not_exist": "x"}, reason="unknown")

    legacy = getattr(update, "update_qso", None)
    if legacy is not None:
        with pytest.raises((ValueError, TypeError)):
            legacy(str(lq.id), {"uuid": "evil"})

    db.expire_all()
    assert db.query(LogicalQSO).one().uuid == original_uuid


def _resolution_service(db):
    try:
        module = importlib.import_module("app.services.divergence_resolution_service")
    except ModuleNotFoundError:
        pytest.fail("DivergenceResolutionService must exist at app.services.divergence_resolution_service")
    cls = getattr(module, "DivergenceResolutionService", None)
    assert cls is not None, "Module must expose DivergenceResolutionService"
    return cls(db)


def test_divergence_resolution_survives_reconciliation_and_cluster_evolution(db):
    from app.models.models import Divergence, DivergenceResolution, LogicalQSO, QSOIdentity

    import_records(db, "QRZ", [adif_record(time_on="120000", freq_mhz="14.076000")])
    import_records(db, "WRL", [adif_record(time_on="120000", freq_mhz="14.076500")])
    reconcile(db)

    divergence = db.query(Divergence).filter(Divergence.field_name == "freq_hz").one()
    identity_uuid = db.query(QSOIdentity).one().uuid
    service = _resolution_service(db)
    resolved = service.resolve_divergence(
        divergence.id,
        resolved_value="14076000",
        reason="acceptance manual resolution",
    )
    assert resolved is not None
    db.expire_all()
    current = db.query(Divergence).filter(Divergence.field_name == "freq_hz").one()
    assert current.status == "resolved"
    assert str(current.resolution) == "14076000"
    assert db.query(DivergenceResolution).count() == 1

    reconcile(db)
    current = db.query(Divergence).filter(Divergence.field_name == "freq_hz").one()
    assert current.status == "resolved"
    assert str(current.resolution) == "14076000"
    assert current.resolution_reason == "acceptance manual resolution"
    assert db.query(QSOIdentity).one().uuid == identity_uuid

    import_records(db, "MSHV", [adif_record(time_on="120000", freq_mhz="14.076000")])
    reconcile(db)
    current = db.query(Divergence).filter(Divergence.field_name == "freq_hz").first()
    assert current is not None
    assert current.status == "resolved"
    assert str(current.resolution) == "14076000"
    assert db.query(QSOIdentity).one().uuid == identity_uuid
    assert db.query(DivergenceResolution).count() == 1
