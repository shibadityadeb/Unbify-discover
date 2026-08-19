from app.models import DiscoverSession
from app.signals import apply_evidence, top_dims, total_evidence


class FakeDB:
    def add(self, _): pass
    def flush(self): pass


def make_session():
    return DiscoverSession(id="t1", anon_id="a1", dimensions={}, contradictions=[],
                           practical_context={}, counters={}, engagement={})


def test_accumulation_builds_confidence():
    s = make_session()
    db = FakeDB()
    apply_evidence(db, s, [{"dim": "autonomy", "delta": 0.6, "weight": 0.5}], "test")
    c1 = s.dimensions["autonomy"]["confidence"]
    apply_evidence(db, s, [{"dim": "autonomy", "delta": 0.5, "weight": 0.5}], "test")
    apply_evidence(db, s, [{"dim": "autonomy", "delta": 0.4, "weight": 0.5}], "test")
    assert s.dimensions["autonomy"]["confidence"] > c1
    assert s.dimensions["autonomy"]["estimate"] > 0
    assert total_evidence(s) == 3


def test_one_signal_stays_weak():
    s = make_session()
    apply_evidence(FakeDB(), s, [{"dim": "leadership", "delta": 1.0, "weight": 0.5}], "test")
    assert s.dimensions["leadership"]["confidence"] < 0.3


def test_correction_outweighs_inference():
    s = make_session()
    db = FakeDB()
    for _ in range(3):
        apply_evidence(db, s, [{"dim": "leadership", "delta": 0.5, "weight": 0.4}], "inferred")
    before = s.dimensions["leadership"]["estimate"]
    apply_evidence(db, s, [{"dim": "leadership", "delta": -0.6, "weight": 1.4}], "calibration_correction")
    assert s.dimensions["leadership"]["estimate"] < before


def test_contradiction_preserved_not_averaged_away():
    s = make_session()
    db = FakeDB()
    for _ in range(4):
        apply_evidence(db, s, [{"dim": "autonomy", "delta": 0.6, "weight": 0.6}], "test")
    for _ in range(4):
        apply_evidence(db, s, [{"dim": "autonomy", "delta": -0.6, "weight": 0.6}], "test")
    assert any(c["dim"] == "autonomy" for c in s.contradictions)
    assert s.dimensions["autonomy"]["variance"] > 0.3


def test_invalid_dim_ignored():
    s = make_session()
    apply_evidence(FakeDB(), s, [{"dim": "nonsense", "delta": 1, "weight": 1}], "test")
    assert "nonsense" not in s.dimensions
