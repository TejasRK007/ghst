"""
Ghostinel - AI Deletion Audit Agent
Main Pipeline Entry Point.

Evaluates all deletion requests from dataset/deletion_requests.csv, audits multimodal evidence,
and produces the official root-level output.csv.
"""
import os
import sys
import csv
import json
import argparse
from typing import List, Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.identity_resolver import IdentityResolver
from code.evidence_indexer import EvidenceIndexer
from code.refined_auditor import RefinedAuditor
from code.models import DeletionStatus


def run_pipeline(dataset_dir: str = "dataset", output_path: str = "output.csv"):
    print(f"==================================================")
    print(f"Ghostinel Deletion Audit Pipeline Starting")
    print(f"Dataset Directory: {dataset_dir}")
    print(f"Output File:       {output_path}")
    print(f"==================================================")

    # 1. Initialize core components
    print("\n[1/4] Loading Identity Resolver (identities & historical audit log)...")
    resolver = IdentityResolver(
        identities_csv=os.path.join(dataset_dir, "user_identities.csv"),
        audit_log_csv=os.path.join(dataset_dir, "user_audit_log.csv")
    )
    print(f"  Loaded {len(resolver.users_by_id)} users and {len(resolver.hash_to_user_id)} email hashes.")

    print("\n[2/4] Initializing Master Evidence Indexer across all 94 evidence files...")
    indexer = EvidenceIndexer(dataset_dir=dataset_dir, resolver=resolver)
    print(f"  Indexed {len(indexer.all_observations)} total observations across evidence files.")

    print("\n[3/4] Initializing Refined Auditor and Loading Worker Activities...")
    auditor = RefinedAuditor(indexer=indexer, resolver=resolver, dataset_dir=dataset_dir)
    print(f"  Loaded {len(auditor.worker_activities)} deletion worker activities.")

    # 2. Read deletion requests
    requests_file = os.path.join(dataset_dir, "deletion_requests.csv")
    if not os.path.exists(requests_file):
        raise FileNotFoundError(f"Deletion requests file not found: {requests_file}")

    with open(requests_file, mode="r", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))

    print(f"\n[4/4] Auditing {len(cases)} Deletion Requests...")
    results: List[Dict[str, str]] = []
    status_counts = {
        DeletionStatus.COMPLETE.value: 0,
        DeletionStatus.INCOMPLETE.value: 0,
        DeletionStatus.NOT_APPLICABLE.value: 0,
    }

    for idx, c in enumerate(cases):
        case_id = c["case_id"]
        email = c["email"]
        requested_at = c["requested_at"]
        reported_status = c["reported_status"]
        reported_at = c["reported_at"]
        audit_at = c["audit_at"]
        request_text = c["request_text"]

        status, steps = auditor.audit_case(
            case_id=case_id,
            email=email,
            requested_at=requested_at,
            reported_status=reported_status,
            reported_at=reported_at,
            audit_at=audit_at,
            request_text=request_text
        )

        status_counts[status] = status_counts.get(status, 0) + 1
        steps_json = json.dumps(steps, separators=(",", ":"))

        results.append({
            "case_id": case_id,
            "deletion_status": status,
            "steps_json": steps_json
        })

        if (idx + 1) % 50 == 0 or (idx + 1) == len(cases):
            print(f"  Processed {idx + 1}/{len(cases)} cases...")

    # Case IDs carry a numeric suffix (case_33, case_34, ...); sort by that
    # suffix so the CSV and dashboard use the same natural ascending order.
    results.sort(key=lambda row: case_id_sort_key(row["case_id"]))

    # 4. Write to output.csv
    with open(output_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["case_id", "deletion_status", "steps_json"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"\n==================================================")
    print(f"Pipeline Execution Completed Successfully!")
    print(f"Generated: {output_path}")
    print(f"Total Rows: {len(results)}")
    print(f"Status Distribution:")
    for stat, count in sorted(status_counts.items()):
        pct = (count / len(results)) * 100
        print(f"  {stat:16s}: {count:3d} ({pct:.2f}%)")
    print(f"==================================================")

    # 5. Output Verification
    valid_evidence_ids = set(indexer.evidence_files)
    activity_path = os.path.join(dataset_dir, "system_activity.csv")
    if os.path.isfile(activity_path):
        with open(activity_path, encoding="utf-8") as activity_file:
            valid_evidence_ids.update(
                row.get("activity_id", "")
                for row in csv.DictReader(activity_file)
                if row.get("activity_id")
            )
    for identity in resolver.users_by_id.values():
        valid_evidence_ids.update(identity.audit_ids)
    verify_output(
        output_path,
        expected_count=len(cases),
        expected_case_ids={case["case_id"] for case in cases},
        valid_evidence_ids=valid_evidence_ids,
    )


def verify_output(
    output_path: str,
    expected_count: int = 518,
    expected_case_ids: set[str] | None = None,
    valid_evidence_ids: set[str] | None = None,
):
    print("\nVerifying Output Contract Compliance...")
    assert os.path.exists(output_path), f"Output file does not exist: {output_path}"
    
    with open(output_path, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) == expected_count, f"Expected {expected_count} rows, found {len(reader)}"
    expected_headers = ["case_id", "deletion_status", "steps_json"]
    assert list(reader[0].keys()) == expected_headers, f"Expected columns {expected_headers}, got {list(reader[0].keys())}"

    seen_cids = set()
    case_ids = [row["case_id"] for row in reader]
    assert case_ids == sorted(case_ids, key=case_id_sort_key), "Rows must be sorted by case_id ascending"
    if expected_case_ids is not None:
        assert set(case_ids) == expected_case_ids, "Output case IDs do not match deletion_requests.csv"

    required_step_fields = {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
    phase_order = {"FINDING": 1, "REMEDIATION": 2, "VERIFICATION": 3}
    from code.models import OPERATION_DEFAULT_STATE, OPERATION_ORDER

    for row in reader:
        cid = row["case_id"]
        stat = row["deletion_status"]
        s_json = row["steps_json"]
        
        assert cid not in seen_cids, f"Duplicate case_id: {cid}"
        seen_cids.add(cid)
        assert stat in ["COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"], f"Invalid status: {stat}"

        parsed_steps = json.loads(s_json)
        assert isinstance(parsed_steps, list), f"steps_json is not an array for {cid}"

        if stat == "NOT_APPLICABLE":
            assert len(parsed_steps) == 0, f"NOT_APPLICABLE case {cid} must have empty steps array"
        else:
            assert len(parsed_steps) > 0, f"{stat} case {cid} must have non-empty steps array"
            phases = []
            sort_keys = []
            for step_no, step in enumerate(parsed_steps, start=1):
                assert set(step) == required_step_fields, f"Invalid step fields in {cid}: {step}"
                assert step["step_no"] == step_no, f"Non-consecutive step_no in {cid}: {step}"
                assert step["phase"] in phase_order, f"Invalid phase in {cid}: {step}"
                assert step["operation"] in OPERATION_DEFAULT_STATE, f"Invalid operation in {cid}: {step}"
                assert step["state"] == OPERATION_DEFAULT_STATE[step["operation"]], f"Invalid state for operation in {cid}: {step}"
                if step.get("evidence_id") and valid_evidence_ids is not None:
                    assert step["evidence_id"] in valid_evidence_ids, f"Unknown evidence reference in {cid}: {step['evidence_id']}"
                phases.append(step["phase"])
                sort_keys.append((phase_order[step["phase"]], OPERATION_ORDER[step["operation"]], step["system_id"], step["resource_id"]))
                if stat == "COMPLETE":
                    assert step["phase"] == "VERIFICATION", f"COMPLETE case {cid} must have only VERIFICATION steps"
                    assert step["evidence_id"] != "", f"COMPLETE case {cid} step must cite non-empty evidence_id"
                elif step["phase"] == "FINDING":
                    assert step["evidence_id"] != "", f"INCOMPLETE finding in {cid} must cite evidence"
                else:
                    assert step["evidence_id"] == "", f"Future step in {cid} must not cite evidence"
            assert phases == sorted(phases, key=phase_order.get), f"Phases out of order in {cid}: {phases}"
            assert sort_keys == sorted(sort_keys), f"Steps do not follow operation/system/resource order in {cid}"

    print("ALL CONTRACT CHECKS PASSED PERFECTLY!")


def case_id_sort_key(case_id: str):
    if case_id.startswith("case_"):
        suffix = case_id.removeprefix("case_")
        if suffix.isdigit():
            return (0, int(suffix))
    return (1, case_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ghostinel Deletion Audit Pipeline")
    parser.add_argument("--dataset", default="dataset", help="Path to dataset directory")
    parser.add_argument("--output", default="output.csv", help="Path to output CSV file")
    args = parser.parse_args()

    run_pipeline(dataset_dir=args.dataset, output_path=args.output)
