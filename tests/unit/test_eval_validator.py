import copy
from evals.runner import validate_document

def document():
    return {"story": {"characters": [{"id": "c"}], "scenes": [{"id": "s"}]}, "beats": [{"start_second": i, "end_second": i+1, "visual": "v", "action": "a", "camera": "c", "sound": "s", "prompt": "p", "continuity": "x", "character_ids": ["c"], "scene_id": "s"} for i in range(5)], "shots": [{"id": "shot", "start_second": 0, "end_second": 5, "beat_seconds": list(range(5)), "prompt": "p"}]}

def test_valid(): assert validate_document(document(), 5) == []

def test_gap_and_unknown_reference():
    data = document(); data["beats"][2]["start_second"] = 3; data["beats"][1]["scene_id"] = "foreign"
    errors = validate_document(data, 5)
    assert "beat coverage 2" in errors and "scene reference 1" in errors

def test_shot_mapping_and_final_coverage():
    data = document(); data["shots"][0]["end_second"] = 4
    assert "shot beat mapping" in validate_document(data, 5)
    assert "shot final coverage" in validate_document(data, 5)

def test_fixed_corpus():
    from evals.build_cases import build
    cases = build(); assert len(cases) == 50
    assert len({c["id"] for c in cases}) == 50
    assert sum(not c["expected"]["valid_input"] for c in cases) == 3
