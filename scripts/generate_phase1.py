"""Generate the fixed Phase 1 fixtures; no external dependencies or source data."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random

VERSION = "1.0.0"
PROFILE = "synthetic-payments-phase1-v1"
PAYMENT_FIELDS = ["attempt_id", "attempted_at", "merchant_id", "payer_bank_id",
                  "payment_method", "amount_paise", "currency", "status", "failure_reason"]
REASONS = ["BANK_TIMEOUT", "INSUFFICIENT_FUNDS", "AUTHENTICATION_FAILED", "LIMIT_EXCEEDED"]
BANKS = [f"BANK_{letter}" for letter in "ABCDE"]
MERCHANTS = [f"M{i:02}" for i in range(1, 21)]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def payments(scenario, rng):
    result = []
    for period in range(2):
        rows = []
        for bank in BANKS:
            for method in ("CARD", "UPI"):
                if scenario == "A":
                    affected = period == 1 and bank == "BANK_B" and method == "UPI"
                    # Every merchant retains its original failure; added failures are timeouts.
                    for index, merchant in enumerate(MERCHANTS):
                        reasons = [""] * (40 if affected else 49) + [REASONS[index % 4]]
                        if affected:
                            reasons += ["BANK_TIMEOUT"] * 9
                        rng.shuffle(reasons)
                        rows.extend((merchant, bank, method, reason) for reason in reasons)
                else:
                    count = 80 if (method == "CARD") == (period == 0) else 20
                    merchants = [merchant for merchant in MERCHANTS for _ in range(count)]
                    successes = len(merchants) * (98 if method == "CARD" else 90) // 100
                    reasons = [""] * successes
                    reasons += [REASONS[i % 4] for i in range(len(merchants) - successes)]
                    rng.shuffle(reasons)
                    rows.extend((merchant, bank, method, reason) for merchant, reason in zip(merchants, reasons))
        rng.shuffle(rows)
        # Quotas apply to the entire period, not separately to each segment.
        dates = [day for day in range(14) for _ in range(714 + (day < 4))]
        for index, ((merchant, bank, method, reason), day) in enumerate(zip(rows, dates)):
            timestamp = datetime(2026, 10, 1 + period * 14 + day,
                                 tzinfo=timezone(timedelta(hours=5, minutes=30)))
            timestamp += timedelta(seconds=rng.randrange(86400))
            result.append(dict(zip(PAYMENT_FIELDS, [
                f"{scenario}{period * 10000 + index + 1:06}", timestamp.isoformat(),
                merchant, bank, method, rng.randint(100, 500000), "INR",
                "FAILED" if reason else "SUCCESS", reason])))
    return result


def generate(root, seed):
    rng = random.Random(seed)
    data = root / "data/synthetic/phase1"
    evaluation = root / "evaluation/phase1"
    merchants = [{"merchant_id": merchant, "merchant_name": f"Fictional Merchant {i + 1:02}",
                  "category": ["retail", "grocery", "dining", "services"][i % 4],
                  "region": ["North", "South", "East", "West"][i // 5]}
                 for i, merchant in enumerate(MERCHANTS)]
    banks = [{"bank_id": bank, "bank_name": f"Fictional Bank {bank[-1]}"} for bank in BANKS]
    scenarios = {"scenario_a": payments("A", rng), "scenario_b": payments("B", rng)}
    originals = scenarios["scenario_a"]
    selected = rng.sample(range(len(originals)), 40)
    duplicate_ids, missing_ids, orphan_ids = selected[:20], selected[20:30], selected[30:]
    dirty = [row.copy() for row in originals]
    for index in missing_ids:
        dirty[index]["attempted_at"] = ""
    for index in orphan_ids:
        dirty[index]["merchant_id"] = "M_ORPHAN"
    dirty.extend(originals[index].copy() for index in duplicate_ids)
    scenarios["scenario_a_dirty"] = dirty
    files = {}
    for scenario, rows in scenarios.items():
        for table, fields, records in (
                ("payments", PAYMENT_FIELDS, rows),
                ("merchants", list(merchants[0]), merchants),
                ("banks", list(banks[0]), banks)):
            path = data / scenario / f"{table}.csv"
            write_csv(path, fields, records)
            files[path.relative_to(root).as_posix()] = {
                "rows": len(records), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    defects = {
        "source": "scenario_a", "target": "scenario_a_dirty",
        "duplicate_attempt_ids": sorted(originals[i]["attempt_id"] for i in duplicate_ids),
        "missing_timestamp_attempt_ids": sorted(originals[i]["attempt_id"] for i in missing_ids),
        "orphan_merchant_attempt_ids": sorted(originals[i]["attempt_id"] for i in orphan_ids),
        "orphan_merchant_value": "M_ORPHAN",
        "additional_duplicate_occurrences": 20,
    }
    defect_path = evaluation / "defect_manifest.json"
    write_json(defect_path, defects)
    write_json(evaluation / "generation_manifest.json", {
        "seed": seed, "profile_id": PROFILE, "schema_version": "1.0.0", "generator_version": VERSION,
        "generator": "scripts/generate_phase1.py", "encoding": "UTF-8", "line_ending": "LF",
        "timestamp_timezone": "+05:30", "amount_paise_range": [100, 500000],
        "daily_quota_scope": "period: 715 attempts on first four dates, then 714 on ten dates",
        "files": files, "defect_manifest_sha256": hashlib.sha256(defect_path.read_bytes()).hexdigest(),
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.output_root.resolve(), args.seed)
    print(f"Generated Phase 1 with seed {args.seed}: {args.output_root.resolve()}")
