from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.db.database import Base
from app.models.models import LogicalQSO, QSOIdentity, SyncJob
from app.adapters.qrz import QRZAdapter, QRZSafetyError
from app.adapters.wrl_udp import WRLUDPAdapter, WRLSafetyError
from app.services.integration_service import IntegrationService


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def make_qso(db, *, uuid="qso-uuid-1", callsign="K1ABC", time_on="12:39:00"):
    identity = QSOIdentity(uuid=f"identity-{uuid}", callsign=callsign, qso_date="2026-09-04", time_on=time_on)
    db.add(identity)
    db.flush()
    qso = LogicalQSO(
        uuid=uuid,
        qso_identity_id=identity.id,
        callsign=callsign,
        qso_date="2026-09-04",
        time_on=time_on,
        band="15M",
        freq_hz=21076900,
        mode="MFSK",
        submode="FT4",
        operating_mode="FT4",
        status="reconciled",
        divergence_count=0,
    )
    db.add(qso)
    db.commit()
    return qso


def test_qrz_preview_is_dry_run_and_exact(db):
    qso = make_qso(db)
    result = IntegrationService(db).qrz_preview(qso.uuid)
    assert result["dry_run"] is True
    assert result["real_write_allowed"] is False
    assert result["locator"] == {"CALL": "K1ABC", "QSO_DATE": "20260904", "TIME_ON": "123900"}
    assert "<CALL:5>K1ABC" in result["adif_record"]
    assert "<SUBMODE:3>FT4" in result["adif_record"]


def test_qrz_live_write_is_fail_closed(db):
    qso = make_qso(db)
    with pytest.raises(QRZSafetyError, match="locked"):
        IntegrationService(db).qrz_live_apply(qso.uuid)


def test_qrz_exact_locator_rejects_ambiguity(db):
    make_qso(db, uuid="a")
    make_qso(db, uuid="b")
    with pytest.raises(QRZSafetyError, match="Ambiguous"):
        IntegrationService(db).qrz_preview("a")


def test_qrz_requires_time_on(db):
    qso = make_qso(db, time_on=None)
    with pytest.raises(QRZSafetyError, match="TIME_ON"):
        IntegrationService(db).qrz_preview(qso.uuid)


def test_wrl_adapter_rejects_non_loopback():
    for host in ("192.168.1.10", "8.8.8.8", "example.com"):
        with pytest.raises(WRLSafetyError):
            WRLUDPAdapter(host, 2237)


def test_wrl_adapter_accepts_loopback():
    WRLUDPAdapter("127.0.0.1", 2237)
    WRLUDPAdapter("127.0.0.2", 2237)
    WRLUDPAdapter("::1", 2237)
    WRLUDPAdapter("localhost", 2237)


def test_wrl_dry_run_never_calls_socket(db, monkeypatch):
    qso = make_qso(db)
    def should_not_send(*args, **kwargs):
        raise AssertionError("socket send must not run in dry-run")
    monkeypatch.setattr(WRLUDPAdapter, "send", should_not_send)
    result = IntegrationService(db).wrl_send(qso.uuid, dry_run=True)
    assert result["sent"] is False
    assert result["dry_run"] is True
    assert db.query(SyncJob).count() == 1


def test_wrl_real_send_disabled_by_default(db, monkeypatch):
    from app.services import integration_service as module
    qso = make_qso(db)
    monkeypatch.setattr(module.settings, "wrl_udp_enabled", False)
    with pytest.raises(WRLSafetyError, match="disabled"):
        IntegrationService(db).wrl_send(qso.uuid, dry_run=False)


def test_wrl_enabled_send_still_uses_validated_loopback(db, monkeypatch):
    from app.services import integration_service as module
    qso = make_qso(db)
    monkeypatch.setattr(module.settings, "wrl_udp_enabled", True)
    monkeypatch.setattr(module.settings, "wrl_udp_host", "127.0.0.1")
    monkeypatch.setattr(WRLUDPAdapter, "send", lambda self, plan: len(plan.payload.encode("utf-8")))
    result = IntegrationService(db).wrl_send(qso.uuid, dry_run=False)
    assert result["sent"] is True
    assert result["host"] == "127.0.0.1"
    assert result["bytes_sent"] > 0
