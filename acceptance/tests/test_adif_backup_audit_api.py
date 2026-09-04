from pathlib import Path

from acceptance._helpers import adif_record, adif_file, import_records, reconcile


def test_adif_unknown_fields_and_spaces_are_preserved(db):
    from app.models.models import RawQSO

    comment = "A B C"
    import_records(db, "QRZ", [adif_record(
        time_on="120000",
        comment=comment,
        extras={"APP_TEST_UNKNOWN": "hello world"},
    )])
    raw = db.query(RawQSO).one()
    assert raw.raw_data.get("COMMENT") == comment
    assert raw.raw_data.get("APP_TEST_UNKNOWN") == "hello world"


def test_reimport_same_file_does_not_duplicate_qsos(db):
    from app.models.models import RawQSO, NormalizedQSO
    from app.services.import_service import ADIFImportService

    content = adif_file([adif_record(time_on="120000")])
    service = ADIFImportService(db)
    first = service.import_adif(content, "same.adi", "QRZ")
    second = service.import_adif(content, "same.adi", "QRZ")
    assert first["processed_records"] == 1
    assert second["already_imported_files"] == 1
    assert second["processed_records"] == 0
    assert db.query(RawQSO).count() == 1
    assert db.query(NormalizedQSO).count() == 1


def test_backup_json_and_adif_survive_restart(tmp_path, db, monkeypatch):
    from app.models.models import Backup, LogicalQSO
    from app.services.backup_service import BackupService

    import_records(db, "QRZ", [adif_record(time_on="120000", freq_mhz="14.076000")])
    reconcile(db)

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(BackupService, "BACKUP_DIR", str(backup_dir))
    service = BackupService(db)
    json_info = service.create_backup("full", "acceptance json")
    adif_info = service.create_backup("adif", "acceptance adif")

    assert Path(json_info["file_path"]).is_file()
    assert Path(adif_info["file_path"]).is_file()
    adif_text = Path(adif_info["file_path"]).read_text(encoding="utf-8")
    assert "<ADIF_VER:5>3.1.7" in adif_text
    assert "<EOR>" in adif_text
    assert db.query(Backup).count() == 2


def test_reconciliation_audit_is_committed_and_persists(db):
    from app.models.models import AuditEvent, AuditOperation

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    reconcile(db)
    db.expire_all()
    events = db.query(AuditEvent).filter(AuditEvent.operation == AuditOperation.RECONCILIATION).all()
    assert len(events) == 1, "Every completed reconciliation must persist an append-only audit event"


def test_core_api_smoke_and_manual_default_partial(api_env):
    from app.models.models import Import, CoverageType

    client, Session = api_env
    content = adif_file([adif_record(time_on="123900")])
    payload = {
        "content": content,
        "source_name": "QRZ",
        "filename": "qrz-api.adi",
        # coverage_type deliberately omitted
    }
    response = client.post("/api/imports/adif", json=payload)
    assert response.status_code == 200, response.text

    response = client.post("/api/reconciliation")
    assert response.status_code == 200, response.text

    for path in (
        "/api/health",
        "/api/qsos",
        "/api/qsos/normalized",
        "/api/qsos/divergences",
        "/api/audit",
        "/api/backups",
    ):
        r = client.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:500]}"

    db = Session()
    try:
        imported = db.query(Import).one()
        assert getattr(imported.coverage_type, "value", imported.coverage_type) == CoverageType.PARTIAL_EXPORT.value
    finally:
        db.close()
