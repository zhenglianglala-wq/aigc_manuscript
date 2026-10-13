"""Prepare a reproducible blinded prompt comparison; no network or model calls."""
import argparse
import csv
import json
import random
from pathlib import Path


def document(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Export must be a JSON object")
    project = value.get("project", value)
    result = project.get("document", project)
    shots = result.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("Export must contain non-empty document.shots")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261012)
    args = parser.parse_args()
    left, right = document(args.baseline), document(args.workflow)
    if len(left["shots"]) != len(right["shots"]):
        raise SystemExit("Comparison requires equal shot counts and aligned time ranges")
    generator = random.Random(args.seed)
    rows, key = [], []
    for index, (a, b) in enumerate(zip(left["shots"], right["shots"]), 1):
        timing = (a["start_second"], a["end_second"])
        if timing != (b["start_second"], b["end_second"]):
            raise SystemExit(f"Shot {index}: time ranges differ")
        swapped = generator.choice([True, False])
        first, second = (b, a) if swapped else (a, b)
        safe = lambda text: "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
        rows.append({"case": index, "start": timing[0], "end": timing[1],
                     "A": safe(first["prompt"]), "B": safe(second["prompt"]),
                     "preferred": "", "notes": ""})
        key.append({"case": index, "A": "workflow" if swapped else "baseline"})
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "blind-review.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "answer-key.json").write_text(json.dumps({"seed": args.seed, "key": key},
            ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(rows)} pairs. Keep answer-key.json away from reviewers.")


if __name__ == "__main__":
    main()
