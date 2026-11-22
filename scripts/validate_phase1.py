"""Validate CSVs and run independent SQLite reference queries, without generator imports."""
import argparse
from collections import Counter
from contextlib import closing
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SQL_PATH = ROOT / "evaluation/phase1/reference.sql"
SCHEMAS = {
    "payments": ["attempt_id", "attempted_at", "merchant_id", "payer_bank_id", "payment_method",
                 "amount_paise", "currency", "status", "failure_reason"],
    "merchants": ["merchant_id", "merchant_name", "category", "region"],
    "banks": ["bank_id", "bank_name"],
}
VALID_REASONS = {"BANK_TIMEOUT", "INSUFFICIENT_FUNDS", "AUTHENTICATION_FAILED", "LIMIT_EXCEEDED"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load_tables(folder):
    tables = {}
    for table, fields in SCHEMAS.items():
        with (folder / f"{table}.csv").open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != fields:
                raise ValueError(f"{table}: unexpected CSV columns {reader.fieldnames}")
            rows = list(reader)
            if any(None in row or any(value is None for value in row.values()) for row in rows):
                raise ValueError(f"{table}: malformed CSV row width")
            tables[table] = rows
    return tables


def quality(tables):
    payments = tables["payments"]
    merchants = tables["merchants"]
    banks = tables["banks"]
    merchant_ids = {row["merchant_id"] for row in merchants}
    bank_ids = {row["bank_id"] for row in banks}
    ids = Counter(row["attempt_id"] for row in payments)
    counts = {
        "duplicate_occurrences": sum(count - 1 for count in ids.values()),
        "duplicate_merchant_keys": len(merchants) - len(merchant_ids),
        "duplicate_bank_keys": len(banks) - len(bank_ids),
        "invalid_identifiers": 0, "missing_timestamps": 0, "invalid_timestamps": 0,
        "orphan_merchants": 0, "orphan_banks": 0, "invalid_amounts": 0,
        "invalid_currency": 0, "invalid_methods": 0, "invalid_outcomes": 0,
        "invalid_dimension_values": 0,
    }
    for row in merchants:
        counts["invalid_dimension_values"] += int(
            not re.fullmatch(r"M(?:0[1-9]|1[0-9]|20)", row["merchant_id"])
            or not row["merchant_name"].strip()
            or row["category"] not in {"retail", "grocery", "dining", "services"}
            or row["region"] not in {"North", "South", "East", "West"})
    for row in banks:
        counts["invalid_dimension_values"] += int(
            not re.fullmatch(r"BANK_[A-E]", row["bank_id"]) or not row["bank_name"].strip())
    for row in payments:
        counts["invalid_identifiers"] += int(not re.fullmatch(r"[AB][0-9]{6}", row["attempt_id"]))
        counts["orphan_merchants"] += int(row["merchant_id"] not in merchant_ids)
        counts["orphan_banks"] += int(row["payer_bank_id"] not in bank_ids)
        amount = row["amount_paise"]
        counts["invalid_amounts"] += int(not re.fullmatch(r"[1-9][0-9]*", amount))
        counts["invalid_currency"] += int(row["currency"] != "INR")
        counts["invalid_methods"] += int(row["payment_method"] not in {"CARD", "UPI"})
        counts["invalid_outcomes"] += int(not (
            (row["status"] == "SUCCESS" and row["failure_reason"] == "")
            or (row["status"] == "FAILED" and row["failure_reason"] in VALID_REASONS)))
        stamp = row["attempted_at"]
        if not stamp:
            counts["missing_timestamps"] += 1
        else:
            try:
                if not re.fullmatch(r"2026-10-\d{2}T\d{2}:\d{2}:\d{2}\+05:30", stamp):
                    raise ValueError("timestamp format")
                parsed = datetime.fromisoformat(stamp)
                if not date(2026, 10, 1) <= parsed.date() <= date(2026, 10, 28):
                    raise ValueError("timestamp range")
            except ValueError:
                counts["invalid_timestamps"] += 1
    return counts


def reference_metrics(tables):
    if any(quality(tables).values()):
        raise ValueError("Analysis blocked: input quality checks failed")
    with closing(sqlite3.connect(":memory:")) as connection, connection:
        connection.row_factory = sqlite3.Row
        for table, fields in SCHEMAS.items():
            connection.execute(f"CREATE TABLE {table} ({', '.join(field + ' TEXT' for field in fields)})")
            connection.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' for _ in fields)})",
                                   ([row[field] for field in fields] for row in tables[table]))
        parts = re.split(r"^-- query: (\w+)\s*$", SQL_PATH.read_text(encoding="utf-8"), flags=re.MULTILINE)
        return {parts[i]: [dict(row) for row in connection.execute(parts[i + 1])]
                for i in range(1, len(parts), 2)}


def analyze(folder):
    tables = load_tables(folder)
    issues = quality(tables)
    payload = {"analysis_status": "blocked" if any(issues.values()) else "allowed", "quality": issues}
    if payload["analysis_status"] == "allowed":
        payload["metrics"] = reference_metrics(tables)
    return payload


def check_specification(scenario, tables, metrics):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    check(len(tables["payments"]) == 20000, "expected 20,000 attempts")
    check(len(tables["merchants"]) == 20 and len(tables["banks"]) == 5, "dimension cardinalities")
    check({row["bank_id"] for row in tables["banks"]} == {f"BANK_{x}" for x in "ABCDE"}, "bank ID coverage")
    expected_merchants = {f"M{i:02}": (["retail", "grocery", "dining", "services"][(i - 1) % 4],
                                      ["North", "South", "East", "West"][(i - 1) // 5])
                          for i in range(1, 21)}
    check({row["merchant_id"]: (row["category"], row["region"]) for row in tables["merchants"]}
          == expected_merchants, "merchant category/region allocation")
    expected_successes = [9800, 9620] if scenario == "scenario_a" else [9640, 9160]
    check([(row["period"], row["attempts"], row["successes"]) for row in metrics["periods"]]
          == [("baseline", 10000, expected_successes[0]), ("comparison", 10000, expected_successes[1])],
          "period counts and success rates")
    check(len(metrics["bank_method"]) == 20, "bank/method/period coverage")
    for row in metrics["bank_method"]:
        comparison = row["period"] == "comparison"
        if scenario == "scenario_a":
            n = 1000
            successes = 800 if comparison and row["payer_bank_id"] == "BANK_B" and row["payment_method"] == "UPI" else 980
        else:
            n = 1600 if (row["payment_method"] == "CARD") != comparison else 400
            successes = n * (98 if row["payment_method"] == "CARD" else 90) // 100
        check((row["attempts"], row["successes"]) == (n, successes), f"bank/method allocation: {row}")
    check(len(metrics["merchant_allocations"]) == 400, "merchant/cell coverage")
    for row in metrics["merchant_allocations"]:
        comparison = row["period"] == "comparison"
        if scenario == "scenario_a":
            successes = 40 if comparison and row["payer_bank_id"] == "BANK_B" and row["payment_method"] == "UPI" else 49
            check((row["attempts"], row["successes"]) == (50, successes), f"merchant allocation: {row}")
        else:
            count = 80 if (row["payment_method"] == "CARD") != comparison else 20
            check(row["attempts"] == count, f"merchant allocation: {row}")
    expected_daily = [{"local_date": (date(2026, 10, 1) + timedelta(days=i)).isoformat(),
                       "attempts": 715 if i % 14 < 4 else 714} for i in range(28)]
    check(metrics["daily"] == expected_daily, "period-wide daily quotas")
    check(metrics["joins"] == [{"payment_count": 20000, "merchant_join_count": 20000,
                                "bank_join_count": 20000, "combined_join_count": 20000}], "joins preserve counts")
    if scenario == "scenario_a":
        check(len(metrics["failure_reasons"]) == 80, "failure reason cell coverage")
        for row in metrics["failure_reasons"]:
            affected = (row["period"], row["payer_bank_id"], row["payment_method"], row["failure_reason"]) == (
                "comparison", "BANK_B", "UPI", "BANK_TIMEOUT")
            check(row["failures"] == (185 if affected else 5), f"failure reason allocation: {row}")
        for row in metrics["bank_method_change"]:
            affected = (row["payer_bank_id"], row["payment_method"]) == ("BANK_B", "UPI")
            check(row["additional_failures"] == (180 if affected else 0), "additional failures outside Bank B/UPI")
    else:
        check(round(sum(row["mix_effect_pp"] for row in metrics["method_decomposition"]), 6) == -4.8,
              "method mix contribution must equal -4.8 percentage points")
        check(all(row["within_method_effect_pp"] == 0 for row in metrics["method_decomposition"]),
              "within-method success rate changed")
    return errors


def check_dirty(clean, dirty, manifest):
    errors = []
    issues = quality(dirty)
    expected_issues = dict.fromkeys(issues, 0)
    expected_issues.update(duplicate_occurrences=20, missing_timestamps=10, orphan_merchants=10)
    if issues != expected_issues:
        errors.append(f"dirty defect counts: {issues}")
    groups = [manifest[key] for key in ("duplicate_attempt_ids", "missing_timestamp_attempt_ids", "orphan_merchant_attempt_ids")]
    defect_ids = set().union(*groups)
    if [len(group) for group in groups] != [20, 10, 10] or len(defect_ids) != 40:
        errors.append("defect IDs are not three disjoint groups of 20/10/10")
    source = {row["attempt_id"]: row for row in clean["payments"]}
    if not defect_ids <= set(source):
        errors.append("defect manifest references missing original IDs")
        return issues, errors
    if manifest.get("additional_duplicate_occurrences") != 20:
        errors.append("defect manifest duplicate count")
    if manifest.get("source") != "scenario_a" or manifest.get("target") != "scenario_a_dirty":
        errors.append("defect manifest scenario names")
    expected_rows = [row.copy() for row in clean["payments"]]
    for row in expected_rows:
        if row["attempt_id"] in groups[1]:
            row["attempted_at"] = ""
        if row["attempt_id"] in groups[2]:
            row["merchant_id"] = manifest["orphan_merchant_value"]
    expected_rows.extend(source[attempt].copy() for attempt in groups[0])
    row_key = lambda row: tuple(row[field] for field in SCHEMAS["payments"])
    if Counter(map(row_key, dirty["payments"])) != Counter(map(row_key, expected_rows)):
        errors.append("dirty rows differ from the exact declared corruption of clean A")
    if len(dirty["payments"]) != 20020:
        errors.append("dirty row count is not 20,020")
    if any(dirty[table] != clean[table] for table in ("merchants", "banks")):
        errors.append("dirty dimensions differ from clean A")
    return issues, errors


def check_manifest(root, manifest):
    errors = []
    required = {f"data/synthetic/phase1/{scenario}/{table}.csv"
                for scenario in ("scenario_a", "scenario_b", "scenario_a_dirty") for table in SCHEMAS}
    if set(manifest["files"]) != required:
        errors.append("manifest file coverage differs from nine required CSVs")
    if (manifest.get("seed"), manifest.get("profile_id"), manifest.get("schema_version"), manifest.get("generator_version")) != (
            42, "synthetic-payments-phase1-v1", "1.0.0", "1.0.0"):
        errors.append("manifest configuration is not the fixed Phase 1 seed-42 profile")
    for name in sorted(required):
        path = root / name
        if name not in manifest["files"] or not path.is_file():
            errors.append(f"missing manifest/dataset entry: {name}")
            continue
        if sha256(path) != manifest["files"][name]["sha256"]:
            errors.append(f"content hash mismatch: {name}")
        with path.open(encoding="utf-8", newline="") as stream:
            count = sum(1 for _ in csv.reader(stream)) - 1
        if count != manifest["files"][name]["rows"]:
            errors.append(f"manifest row count mismatch: {name}")
    if sha256(root / "evaluation/phase1/defect_manifest.json") != manifest.get("defect_manifest_sha256"):
        errors.append("defect manifest hash mismatch")
    return errors


def reproducibility(root, seed):
    with tempfile.TemporaryDirectory() as folder:
        paths = [Path(folder) / "run1", Path(folder) / "run2"]
        for output in paths:
            subprocess.run([sys.executable, str(ROOT / "scripts/generate_phase1.py"),
                            "--output-root", str(output), "--seed", str(seed)], check=True, capture_output=True)
        names = sorted(path.relative_to(paths[0]).as_posix() for path in paths[0].rglob("*") if path.is_file())
        compared = {name: {"run1": sha256(paths[0] / name), "run2": sha256(paths[1] / name),
                           "delivered": sha256(root / name)} for name in names}
        return {"status": "checked", "identical": all(len(set(item.values())) == 1 for item in compared.values()),
                "files": compared}


def validate(root, write_expected=False, check_reproducibility=False):
    evaluation = root / "evaluation/phase1"
    report = {"dataset_gate": "failed", "analyst_gate": "pending", "errors": [], "scenarios": {},
              "reproducibility": {"status": "not_run"}}
    answers = {"profile_id": "synthetic-payments-phase1-v1", "reference_sql_sha256": sha256(SQL_PATH),
               "scenarios": {}}
    try:
        manifest = json.loads((evaluation / "generation_manifest.json").read_text(encoding="utf-8"))
        report["errors"].extend(check_manifest(root, manifest))
        loaded = {}
        for scenario in ("scenario_a", "scenario_b", "scenario_a_dirty"):
            tables = load_tables(root / "data/synthetic/phase1" / scenario)
            loaded[scenario] = tables
            issues = quality(tables)
            report["scenarios"][scenario] = {"rows": len(tables["payments"]), "quality": issues,
                                              "analysis_status": "blocked" if any(issues.values()) else "allowed"}
            if scenario == "scenario_a_dirty":
                continue
            if any(issues.values()):
                report["errors"].append(f"{scenario}: clean quality checks failed")
                continue
            metrics = reference_metrics(tables)
            errors = check_specification(scenario, tables, metrics)
            report["errors"].extend(f"{scenario}: {error}" for error in errors)
            answers["scenarios"][scenario] = metrics
            report["scenarios"][scenario]["periods"] = metrics["periods"]
            report["scenarios"][scenario]["specification_checks"] = "passed" if not errors else "failed"
        defects = json.loads((evaluation / "defect_manifest.json").read_text(encoding="utf-8"))
        _, errors = check_dirty(loaded["scenario_a"], loaded["scenario_a_dirty"], defects)
        report["errors"].extend(errors)
        report["scenarios"]["scenario_a_dirty"]["expected_defects_verified"] = not errors
        if check_reproducibility:
            report["reproducibility"] = reproducibility(root, manifest["seed"])
            if not report["reproducibility"]["identical"]:
                report["errors"].append("regenerated dataset or deterministic manifest hashes differ")
        expected_path = evaluation / "expected_answers.json"
        if write_expected:
            if not report["errors"]:
                save_json(expected_path, answers)
        elif not expected_path.is_file():
            report["errors"].append("expected_answers.json missing; run once with --write-expected")
        elif json.loads(expected_path.read_text(encoding="utf-8")) != answers:
            report["errors"].append("independent SQL results differ from saved expected answers")
        if not report["errors"]:
            report["dataset_gate"] = "passed"
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.CalledProcessError) as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    save_json(evaluation / "validation_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write-expected", action="store_true", help="write SQL answers only after specification checks pass")
    parser.add_argument("--check-reproducibility", action="store_true", help="compare two fresh runs and delivered artifacts")
    parser.add_argument("--analyze", type=Path, help="quality-gated metrics for one scenario folder; dirty data exits 1")
    args = parser.parse_args()
    if args.analyze:
        try:
            payload = analyze(args.analyze)
        except (OSError, ValueError, sqlite3.Error) as error:
            payload = {"analysis_status": "blocked", "error": str(error)}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return int(payload["analysis_status"] == "blocked")
    report = validate(args.root.resolve(), args.write_expected, args.check_reproducibility)
    print(json.dumps({"dataset_gate": report["dataset_gate"], "errors": report["errors"],
                      "report": str(args.root.resolve() / "evaluation/phase1/validation_report.json")}, indent=2))
    return int(report["dataset_gate"] != "passed")


if __name__ == "__main__":
    sys.exit(main())
