"""Tests for SafeUpdateService field validation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.models.models import LogicalQSO
from app.services.safe_update_service import SafeUpdateService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    # Create a test LogicalQSO
    test_qso = LogicalQSO(
        uuid="test-uuid-safe",
        callsign="PU2BRU",
        qso_date="2024-01-15",
        time_on="12:00:00",
        band="20M",
        freq_hz=14076000,
        mode="FT4",
        county=""
    )
    session.add(test_qso)
    session.commit()
    
    yield session
    
    session.close()


def test_safe_update_rejects_protected_fields(db):
    """Test that safe update rejects protected fields like uuid, id, created_at, updated_at."""
    service = SafeUpdateService(db)
    
    # Try to update protected fields
    with pytest.raises(ValueError) as exc_info:
        service.build_safe_update("test-uuid-safe", {"uuid": "new-uuid"}, reason="test")
    
    assert "uuid" in str(exc_info.value)
    assert "protected" in str(exc_info.value).lower()
    
    with pytest.raises(ValueError) as exc_info:
        service.build_safe_update("test-uuid-safe", {"id": 999}, reason="test")
    
    assert "id" in str(exc_info.value)
    assert "protected" in str(exc_info.value).lower()
    
    with pytest.raises(ValueError) as exc_info:
        service.build_safe_update("test-uuid-safe", {"created_at": "2023-01-01"}, reason="test")
    
    assert "created_at" in str(exc_info.value)
    assert "protected" in str(exc_info.value).lower()
    
    with pytest.raises(ValueError) as exc_info:
        service.build_safe_update("test-uuid-safe", {"updated_at": "2023-01-01"}, reason="test")
    
    assert "updated_at" in str(exc_info.value)
    assert "protected" in str(exc_info.value).lower()


def test_safe_update_rejects_unknown_fields(db):
    """Test that safe update rejects unknown/invalid fields."""
    service = SafeUpdateService(db)
    
    with pytest.raises(ValueError) as exc_info:
        service.build_safe_update("test-uuid-safe", {"campo_inexistente": "value"}, reason="test")
    
    assert "campo_inexistente" in str(exc_info.value)
    assert "unknown" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()
    
    with pytest.raises(ValueError) as exc_info:
        service.build_safe_update("test-uuid-safe", {"nonexistent_field": "x"}, reason="test")
    
    assert "nonexistent_field" in str(exc_info.value)


def test_safe_update_by_uuid_preserves_other_fields(db):
    """Test that safe update by UUID preserves all other fields."""
    service = SafeUpdateService(db)
    
    # Get the original QSO
    original_qso = db.query(LogicalQSO).filter(LogicalQSO.uuid == "test-uuid-safe").first()
    original_callsign = original_qso.callsign
    original_grid = original_qso.grid if hasattr(original_qso, 'grid') else None
    original_freq = original_qso.freq_hz
    
    # Apply update only to county
    result = service.apply_safe_update(
        "test-uuid-safe",
        {"county": "Campinas"},
        reason="Adding county"
    )
    
    assert result is not None
    assert result.county == "Campinas"
    
    # Verify other fields are preserved
    db.refresh(result)
    assert result.callsign == original_callsign
    assert result.freq_hz == original_freq


def test_qso_update_rejects_protected_fields(db):
    """Test that QSO update service also rejects protected fields."""
    from app.services.qso_update_service import QSOUpdateService
    
    service = QSOUpdateService(db)
    
    with pytest.raises(ValueError) as exc_info:
        service.build_safe_update({"uuid": "evil-uuid"})
    
    assert "uuid" in str(exc_info.value)
    assert "protected" in str(exc_info.value).lower() or "Cannot modify" in str(exc_info.value)
