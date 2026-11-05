"""
GhostTrace Sample Benchmark Runner.
Generates predictions for all 32 sample cases into sample_predictions.csv
and evaluates them against dataset/sample_output.csv with comprehensive diagnostics.
"""
import os
import sys
import csv
import json

# Ensure repo root is on sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from code.evidence_indexer import EvidenceIndexer
from code.identity_resolver import IdentityResolver
from code.refined_auditor import RefinedAuditor
from code.evaluation.evaluator import evaluate_predictions

print("=" * 60)
print("  GHOSTTRACE SAMPLE BENCHMARK & EVALUATION RUNNER")
print("=" * 60)

print("\n1. Initializing RefinedAuditor and Multimodal Evidence Index...")
indexer = EvidenceIndexer()
resolver = IdentityResolver()
auditor = RefinedAuditor(indexer, resolver)

pred_file = "sample_predictions.csv"
input_file = os.path.join(ROOT, "dataset/sample_deletion_requests.csv")
ground_truth_file = os.path.join(ROOT, "dataset/sample_output.csv")
report_file = os.path.join(ROOT, "evaluation_report.json")

print(f"\n2. Generating predictions from '{input_file}' -> '{pred_file}'...")
cases_written = 0

with open(input_file, mode="r", encoding="utf-8") as in_f, \
     open(pred_file, mode="w", newline="", encoding="utf-8") as out_f:

    reader = csv.DictReader(in_f)
    writer = csv.writer(out_f)
    # Strict required schema
    writer.writerow(["case_id", "deletion_status", "steps_json"])

    for row in reader:
        status, steps = auditor.audit_case(
            case_id=row["case_id"],
            email=row["email"],
            requested_at=row["requested_at"],
            reported_status=row["reported_status"],
            reported_at=row["reported_at"],
            audit_at=row["audit_at"],
            request_text=row["request_text"]
        )
        writer.writerow([row["case_id"], status, json.dumps(steps, separators=(',', ':'))])
        cases_written += 1

# Validation of output prediction file
if not os.path.exists(pred_file) or os.path.getsize(pred_file) == 0:
    raise RuntimeError(f"FATAL: Prediction file '{pred_file}' is missing or empty!")

if cases_written != 32:
    print(f"⚠️ Warning: Expected 32 cases written, but wrote {cases_written}.")
else:
    print(f"✓ Successfully wrote {cases_written} predictions into '{pred_file}'. File size: {os.path.getsize(pred_file)} bytes.")

print(f"\n3. Evaluating predictions against '{ground_truth_file}'...")
results = evaluate_predictions(
    ground_truth_path=ground_truth_file,
    predictions_path=pred_file,
    report_output_path=report_file,
    verbose=True
)

print("\n" + "=" * 60)
print("  EVALUATION BENCHMARK METRICS")
print("=" * 60)
print(f"Status Accuracy:   {results['status_accuracy_pct']:.2f}% ({results['status_matches']}/{results['total_cases']} cases)")
print(f"Sequence Accuracy: {results['sequence_accuracy_pct']:.2f}% ({results['step_exact_matches']}/{results['total_cases']} cases)")
print(f"Field Accuracy:    {results['field_accuracy_pct']:.2f}%")
print("=" * 60)

# Print case comparisons summary
print("\nPER-CASE AUDIT SUMMARY (32 Cases):")
for cid, det in results["case_details"].items():
    status_str = "MATCH" if det.get("status_match") else "DIFF "
    seq_str = "MATCH" if det.get("seq_match") else "DIFF "
    print(f"Case {cid:<8}: status={status_str} | seq={seq_str} | GT steps={det.get('gt_steps'):>2} | Pred steps={det.get('pred_steps'):>2}")

# Print failed cases diagnostics
failed = results.get("failed_cases_diagnostics", [])
if failed:
    print("\n" + "=" * 60)
    print(f"  DETAILED FAILURE DIAGNOSTICS ({len(failed)} Cases with Sequence/Field Mismatches)")
    print("=" * 60)
    for d in failed:
        print(f"\n▶ Case: {d['case_id']}")
        status_note = "MATCH" if d.get('status_match') else f"MISMATCH (Expected: {d['expected_status']} vs Predicted: {d['predicted_status']})"
        seq_note = "MATCH" if d.get('sequence_match') else f"MISMATCH (Expected steps: {d['expected_step_count']} vs Predicted steps: {d['predicted_step_count']})"
        print(f"  Status:          {status_note}")
        print(f"  Sequence:        {seq_note}")
        print(f"  First Mismatch:  Step {d['first_mismatching_step']} (Mismatching fields: {d['mismatching_fields']})")
        if d['expected_step_content']:
            print(f"  Expected Step:   {json.dumps(d['expected_step_content'])}")
        if d['predicted_step_content']:
            print(f"  Predicted Step:  {json.dumps(d['predicted_step_content'])}")
        if d['missing_steps']:
            print(f"  Missing Steps ({len(d['missing_steps'])}):")
            for ms in d['missing_steps']:
                print(f"    - {json.dumps(ms)}")
        if d['extra_steps']:
            print(f"  Extra Steps ({len(d['extra_steps'])}):")
            for es in d['extra_steps']:
                print(f"    - {json.dumps(es)}")
        print("-" * 60)

print(f"\n✓ Detailed JSON evaluation report generated at: {report_file}")
