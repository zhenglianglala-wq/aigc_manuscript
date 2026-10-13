"""Fixture-only live API corpus runner. Refuses a paid model mode."""
import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

def request(base, method, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read()
            return res.status, json.loads(raw) if "json" in res.headers.get("Content-Type", "") else raw.decode()
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())

def validate_document(document, duration):
    errors = []
    story, beats, shots = document.get("story"), document.get("beats", []), document.get("shots", [])
    if not story: return ["missing story"]
    if len(beats) != duration: errors.append("beat count")
    character_ids = {c["id"] for c in story.get("characters", [])}
    scene_ids = {s["id"] for s in story.get("scenes", [])}
    for second, beat in enumerate(beats):
        if (beat.get("start_second"), beat.get("end_second")) != (second, second + 1): errors.append(f"beat coverage {second}")
        for key in ["visual", "action", "camera", "sound", "prompt", "continuity"]:
            if not isinstance(beat.get(key), str): errors.append(f"beat field {second}/{key}")
        if not set(beat.get("character_ids", [])).issubset(character_ids): errors.append(f"character reference {second}")
        if beat.get("scene_id") not in scene_ids: errors.append(f"scene reference {second}")
    cursor, shot_ids = 0, set()
    for shot in shots:
        start, end = shot.get("start_second"), shot.get("end_second")
        if not isinstance(start, int) or not isinstance(end, int) or start != cursor or end <= start:
            errors.append("shot coverage"); continue
        if shot.get("beat_seconds") != list(range(start, end)): errors.append("shot beat mapping")
        if not shot.get("prompt"): errors.append("shot prompt")
        if shot.get("id") in shot_ids: errors.append("duplicate shot id")
        shot_ids.add(shot.get("id")); cursor = end
    if cursor != duration: errors.append("shot final coverage")
    return errors

def complete(base, project, kind, operation=None):
    body = {"kind": kind, "base_revision": project["current_revision"], "idempotency_key": str(time.time_ns())}
    if operation: body.update(operation)
    status, run = request(base, "POST", f"/api/projects/{project['id']}/runs", body)
    assert status == 202, (status, run)
    deadline = time.monotonic() + 30
    while run["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
        assert time.monotonic() < deadline, "task timeout"
        time.sleep(.03); _, run = request(base, "GET", f"/api/runs/{run['id']}")
    assert run["status"] == "succeeded", run
    if run.get("proposal_id"):
        status, project = request(base, "POST", f"/api/proposals/{run['proposal_id']}/apply", {"base_revision": project["current_revision"]})
        assert status == 200, project
    return project, run

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--base-url", default="http://127.0.0.1:8000"); parser.add_argument("--output", default="evals/results/fixture.json")
    args = parser.parse_args()
    _, settings = request(args.base_url, "GET", "/api/settings/model")
    if settings.get("mode") != "fixture": raise SystemExit("Refusing non-fixture evaluation; no paid authorization")
    root = Path(__file__).resolve().parents[1]
    source_hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for directory in ["backend", "agents", "tools", "workflows", "context", "memory", "prompts"] for p in sorted((root / directory).rglob("*")) if p.is_file() and p.suffix in {".py", ".json"}}
    rows = []
    for case in map(json.loads, Path(__file__).with_name("cases.jsonl").read_text().splitlines()):
        project = None; started = time.monotonic()
        try:
            status, project = request(args.base_url, "POST", "/api/projects", {"brief": case["brief"]})
            if not case["expected"]["valid_input"]:
                assert status == 422, (status, project)
            else:
                assert status == 201, (status, project)
                project, _ = complete(args.base_url, project, "expand")
                status, project = request(args.base_url, "POST", f"/api/projects/{project['id']}/story/confirm", {"base_revision": project["current_revision"]})
                assert status == 200, ("story confirm", status, project)
                project, run = complete(args.base_url, project, "timeline")
                if case.get("operation"):
                    before = project["document"]
                    op = case["operation"]
                    project, run = complete(args.base_url, project, "rewrite", op)
                    assert before["story"] == project["document"]["story"], "rewrite changed story bible"
                    for i, beat in enumerate(before["beats"]):
                        if not op["start_second"] <= i < op["end_second"]: assert beat == project["document"]["beats"][i], f"out-of-scope edit {i}"
                        else:
                            for field in op["locked_fields"]: assert beat[field] == project["document"]["beats"][i][field], f"locked field changed {i}/{field}"
                errors = validate_document(project["document"], case["brief"]["duration_seconds"])
                assert not errors, errors
                status, export = request(args.base_url, "GET", f"/api/projects/{project['id']}/exports?format=json")
                assert status == 200, ("export", status, export)
            rows.append({"id": case["id"], "status": "passed", "elapsed_seconds": round(time.monotonic()-started, 3), "human_quality": "not_measured", "cost": None})
        except Exception as error:
            rows.append({"id": case["id"], "status": "failed", "error": str(error), "human_quality": "not_measured", "cost": None})
        finally:
            if isinstance(project, dict) and project.get("id"): request(args.base_url, "DELETE", f"/api/projects/{project['id']}")
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"service": "real", "model": "fixture", "data": "synthetic", "recorded_at": datetime.now(timezone.utc).isoformat(), "python": sys.version, "source_hashes": source_hashes, "case_sha256": hashlib.sha256(Path(__file__).with_name("cases.jsonl").read_bytes()).hexdigest(), "rows": rows}, ensure_ascii=False, indent=2))
    print(json.dumps({s: sum(r["status"] == s for r in rows) for s in ["passed", "failed"]}))
    raise SystemExit(any(r["status"] == "failed" for r in rows))

if __name__ == "__main__": main()
