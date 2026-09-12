import json
from pathlib import Path

from app.services.fast_adif_comparison_service import FastADIFComparisonService


def test_shared_v9_matching_contract_vectors():
    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / "test_vectors" / "qso_matching_v9.json").read_text(encoding="utf-8"))
    comparator = FastADIFComparisonService()

    for case in data["cases"]:
        left = comparator._normalize([case["left"]], "LEFT")[0]
        right = comparator._normalize([case["right"]], "RIGHT")[0]
        evidence = comparator._candidate(left, right)
        actual = "none" if evidence is None else evidence["kind"]
        assert actual == case["expected"], case["name"]
