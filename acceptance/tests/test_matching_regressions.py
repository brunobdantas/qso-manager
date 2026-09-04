from acceptance._helpers import adif_record, import_records, reconcile, logical_source_names


def test_ambiguous_missing_time_sets_needs_review_on_specific_qso(db):
    from app.models.models import LogicalQSO, Source

    import_records(db, "QRZ", [adif_record(time_on=None)])
    import_records(db, "WRL", [adif_record(time_on="120000")])
    import_records(db, "MSHV", [adif_record(time_on="180000")])
    reconcile(db)

    qrz_logicals = [
        lq for lq in db.query(LogicalQSO).all()
        if "QRZ" in logical_source_names(lq)
    ]
    assert len(qrz_logicals) == 1
    assert qrz_logicals[0].status == "needs_review"


def test_exact_multisource_match_is_reconciled(db):
    from app.models.models import LogicalQSO

    import_records(db, "QRZ", [adif_record(time_on="120000")])
    import_records(db, "WRL", [adif_record(time_on="120010")])
    reconcile(db)
    lq = db.query(LogicalQSO).one()
    assert lq.status == "reconciled"
    assert logical_source_names(lq) == {"QRZ", "WRL"}


def test_1239_regression_with_20_seconds_800_hz_and_ft4_equivalence(db):
    from app.models.models import LogicalQSO

    import_records(
        db,
        "QRZ",
        [adif_record(time_on="123900", freq_mhz="21.076100", mode="MFSK", submode="FT4", band="15M")],
    )
    import_records(
        db,
        "WRL",
        [adif_record(time_on="123920", freq_mhz="21.076900", mode="FT4", band="15M")],
    )
    reconcile(db)

    assert db.query(LogicalQSO).count() == 1, "The known 12:39 regression must reconcile as one QSO"
    lq = db.query(LogicalQSO).one()
    assert logical_source_names(lq) == {"QRZ", "WRL"}


def test_1239_qrz_does_not_match_unrelated_1800_qso(db):
    from app.models.models import LogicalQSO

    import_records(db, "QRZ", [adif_record(time_on="123900")])
    import_records(db, "WRL", [adif_record(time_on="180000")])
    reconcile(db)
    assert db.query(LogicalQSO).count() == 2


def test_same_minute_different_bands_remain_distinct(db):
    from app.models.models import LogicalQSO

    import_records(db, "QRZ", [
        adif_record(time_on="120000", band="20M", freq_mhz="14.076000"),
        adif_record(time_on="120020", band="15M", freq_mhz="21.076000"),
    ])
    reconcile(db)
    assert db.query(LogicalQSO).count() == 2
