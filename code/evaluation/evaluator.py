"""
Evaluator for Ghostinel Deletion Audit Agent.
Evaluates predictions against sample_output.csv or canonical ground truth.
Provides detailed mismatch diagnostics, failure reports, and JSON export.
"""
import os
import sys
import csv
import json
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any, Optional


def evaluate_predictions(
    ground_truth_path: str = "dataset/sample_output.csv",
    predictions_path: str = "sample_predictions.csv",
    report_output_path: Optional[str] = "evaluation_report.json",
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Evaluates predictions against ground truth dataset.

    Defaults:
      - ground_truth_path: dataset/sample_output.csv
      - predictions_path:  sample_predictions.csv
      - Never defaults both paths to the ground-truth file.
    """
    if verbose:
        print(f"Comparing Ground Truth: '{ground_truth_path}' vs Predictions: '{predictions_path}'")

    # Validate file presence
    if not os.path.exists(ground_truth_path):
        raise FileNotFoundError(f"Ground truth file not found at: {ground_truth_path}")
    if not os.path.exists(predictions_path):
        raise FileNotFoundError(f"Predictions file not found at: {predictions_path}")

    # Load and validate ground truth data
    with open(ground_truth_path, mode="r", encoding="utf-8") as f:
        gt_reader = csv.DictReader(f)
        gt_rows = {r["case_id"]: r for r in gt_reader if r.get("case_id")}

    if not gt_rows:
        raise ValueError(f"Ground truth file '{ground_truth_path}' contains zero data rows.")

    # Load and validate predictions data
    with open(predictions_path, mode="r", encoding="utf-8") as f:
        pred_reader = csv.DictReader(f)
        pred_rows = {r["case_id"]: r for r in pred_reader if r.get("case_id")}

    if not pred_rows:
        raise ValueError(f"Predictions file '{predictions_path}' contains zero data rows.")

    # Validate missing and extra case IDs
    gt_case_ids = set(gt_rows.keys())
    pred_case_ids = set(pred_rows.keys())
    missing_case_ids = sorted(list(gt_case_ids - pred_case_ids))
    extra_case_ids = sorted(list(pred_case_ids - gt_case_ids))

    comparable_case_ids = gt_case_ids & pred_case_ids
    if not comparable_case_ids:
        gt_examples = ", ".join(sorted(gt_case_ids)[:5])
        pred_examples = ", ".join(sorted(pred_case_ids)[:5])
        raise ValueError(
            "Cannot calculate accuracy because the files have no matching case_id values. "
            f"Ground truth has {len(gt_case_ids)} cases (for example: {gt_examples}); "
            f"predictions has {len(pred_case_ids)} cases (for example: {pred_examples}). "
            "The sample reference covers case_01–case_32, while this output.csv covers a "
            "different set of requests. Compare sample_predictions.csv with the sample "
            "reference, and validate output.csv against its source evidence and CSV contract."
        )

    if missing_case_ids and verbose:
        print(f"⚠️  Missing Case IDs in predictions ({len(missing_case_ids)}): {missing_case_ids}")
    if extra_case_ids and verbose:
        print(f"⚠️  Extra Case IDs in predictions ({len(extra_case_ids)}): {extra_case_ids}")

    total_cases = len(gt_rows)
    status_matches = 0
    step_exact_matches = 0
    total_gt_steps = 0
    total_pred_steps = 0
    matched_steps = 0
    field_matches = 0
    total_fields = 0

    field_mismatch_counts = {
        "phase": 0,
        "operation": 0,
        "system_id": 0,
        "resource_id": 0,
        "state": 0,
        "evidence_id": 0
    }

    case_details = {}
    failed_cases_diagnostics = []
    sequence_mismatches = []
    missing_and_extra_steps_cases = []

    fields_to_compare = ["phase", "operation", "system_id", "resource_id", "state", "evidence_id"]

    for cid, gt in sorted(gt_rows.items()):
        if cid not in pred_rows:
            case_details[cid] = {
                "status_match": False,
                "seq_match": False,
                "error": "Missing prediction in prediction file"
            }
            gt_steps_raw = json.loads(gt.get("steps_json", "[]"))
            failed_cases_diagnostics.append({
                "case_id": cid,
                "status_match": False,
                "sequence_match": False,
                "expected_status": gt.get("deletion_status"),
                "predicted_status": None,
                "expected_step_count": len(gt_steps_raw),
                "predicted_step_count": 0,
                "first_mismatching_step": 1,
                "mismatching_fields": ["case_id"],
                "expected_step_content": gt_steps_raw[0] if gt_steps_raw else None,
                "predicted_step_content": None,
                "missing_steps": gt_steps_raw,
                "extra_steps": []
            })
            continue

        pred = pred_rows[cid]
        s_match = (gt["deletion_status"] == pred["deletion_status"])
        if s_match:
            status_matches += 1

        try:
            gt_steps = json.loads(gt["steps_json"])
            pred_steps = json.loads(pred["steps_json"])
        except Exception as e:
            case_details[cid] = {
                "status_match": s_match,
                "seq_match": False,
                "error": f"JSON decode error: {e}"
            }
            continue

        total_gt_steps += len(gt_steps)
        total_pred_steps += len(pred_steps)
        seq_match = True

        first_mismatch_step = None
        mismatching_field_names = []
        expected_step_content = None
        predicted_step_content = None

        if len(gt_steps) == len(pred_steps):
            for i in range(len(gt_steps)):
                g = gt_steps[i]
                p = pred_steps[i]
                step_match = True
                step_diffs = []
                for fld in fields_to_compare:
                    total_fields += 1
                    if g.get(fld, "") == p.get(fld, ""):
                        field_matches += 1
                    else:
                        step_match = False
                        seq_match = False
                        step_diffs.append(fld)
                        field_mismatch_counts[fld] += 1

                if not step_match and first_mismatch_step is None:
                    first_mismatch_step = i + 1
                    mismatching_field_names = step_diffs
                    expected_step_content = g
                    predicted_step_content = p

                if step_match:
                    matched_steps += 1
            if seq_match:
                step_exact_matches += 1
        else:
            seq_match = False
            # Still count partial field matches for common steps
            min_len = min(len(gt_steps), len(pred_steps))
            for i in range(min_len):
                g = gt_steps[i]
                p = pred_steps[i]
                step_diffs = []
                for fld in fields_to_compare:
                    total_fields += 1
                    if g.get(fld, "") == p.get(fld, ""):
                        field_matches += 1
                    else:
                        step_diffs.append(fld)
                        field_mismatch_counts[fld] += 1
                if step_diffs and first_mismatch_step is None:
                    first_mismatch_step = i + 1
                    mismatching_field_names = step_diffs
                    expected_step_content = g
                    predicted_step_content = p

            if first_mismatch_step is None:
                first_mismatch_step = min_len + 1
                if len(gt_steps) > len(pred_steps):
                    mismatching_field_names = ["MISSING_STEP"]
                    expected_step_content = gt_steps[min_len]
                    predicted_step_content = None
                else:
                    mismatching_field_names = ["EXTRA_STEP"]
                    expected_step_content = None
                    predicted_step_content = pred_steps[min_len]

        missing_steps = gt_steps[len(pred_steps):] if len(gt_steps) > len(pred_steps) else []
        extra_steps = pred_steps[len(gt_steps):] if len(pred_steps) > len(gt_steps) else []

        case_details[cid] = {
            "status_match": s_match,
            "seq_match": seq_match,
            "gt_steps": len(gt_steps),
            "pred_steps": len(pred_steps),
        }

        if missing_steps or extra_steps:
            missing_and_extra_steps_cases.append({
                "case_id": cid,
                "missing_steps_count": len(missing_steps),
                "extra_steps_count": len(extra_steps),
                "missing_steps": missing_steps,
                "extra_steps": extra_steps
            })

        if not seq_match:
            sequence_mismatches.append({
                "case_id": cid,
                "expected_status": gt["deletion_status"],
                "predicted_status": pred["deletion_status"],
                "expected_step_count": len(gt_steps),
                "predicted_step_count": len(pred_steps),
                "first_mismatching_step": first_mismatch_step,
                "mismatching_fields": mismatching_field_names,
                "expected_step_content": expected_step_content,
                "predicted_step_content": predicted_step_content,
                "missing_steps": missing_steps,
                "extra_steps": extra_steps
            })

        if (not s_match) or (not seq_match):
            failed_cases_diagnostics.append({
                "case_id": cid,
                "status_match": s_match,
                "sequence_match": seq_match,
                "expected_status": gt["deletion_status"],
                "predicted_status": pred["deletion_status"],
                "expected_step_count": len(gt_steps),
                "predicted_step_count": len(pred_steps),
                "first_mismatching_step": first_mismatch_step,
                "mismatching_fields": mismatching_field_names,
                "expected_step_content": expected_step_content,
                "predicted_step_content": predicted_step_content,
                "missing_steps": missing_steps,
                "extra_steps": extra_steps
            })

    status_acc = (status_matches / total_cases) * 100 if total_cases else 0
    seq_acc = (step_exact_matches / total_cases) * 100 if total_cases else 0
    field_acc = (field_matches / total_fields) * 100 if total_fields else 0

    results = {
        "summary": {
            "total_cases": total_cases,
            "status_accuracy_pct": status_acc,
            "sequence_accuracy_pct": seq_acc,
            "field_accuracy_pct": field_acc,
            "status_matches": status_matches,
            "sequence_matches": step_exact_matches,
            "total_gt_steps": total_gt_steps,
            "total_pred_steps": total_pred_steps,
            "field_matches": field_matches,
            "total_fields": total_fields,
            "ground_truth_path": ground_truth_path,
            "predictions_path": predictions_path,
            "evaluated_at": datetime.now(timezone.utc).isoformat()
        },
        "dataset_validation": {
            "missing_case_ids": missing_case_ids,
            "extra_case_ids": extra_case_ids,
            "ground_truth_total_rows": len(gt_rows),
            "predictions_total_rows": len(pred_rows)
        },
        "field_level_mismatches_summary": {
            **field_mismatch_counts,
            "total_fields_evaluated": total_fields,
            "field_matches": field_matches
        },
        "per_case_comparisons": case_details,
        "sequence_mismatches": sequence_mismatches,
        "missing_and_extra_steps": missing_and_extra_steps_cases,
        "failed_cases_diagnostics": failed_cases_diagnostics,
        # Backward compatibility aliases
        "total_cases": total_cases,
        "status_accuracy_pct": status_acc,
        "sequence_accuracy_pct": seq_acc,
        "field_accuracy_pct": field_acc,
        "status_matches": status_matches,
        "step_exact_matches": step_exact_matches,
        "case_details": case_details
    }

    # Generate evaluation_report.json
    if report_output_path:
        with open(report_output_path, mode="w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        if verbose:
            print(f"Detailed evaluation report written to: {report_output_path}")

    return results


if __name__ == "__main__":
    gt = sys.argv[1] if len(sys.argv) > 1 else "dataset/sample_output.csv"
    pred = sys.argv[2] if len(sys.argv) > 2 else "sample_predictions.csv"
    report_file = sys.argv[3] if len(sys.argv) > 3 else "evaluation_report.json"

    try:
        res = evaluate_predictions(gt, pred, report_file, verbose=True)
    except ValueError as exc:
        print(f"Evaluation unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print("\n" + "=" * 50)
    print(f"Status Accuracy:   {res['status_accuracy_pct']:.2f}% ({res['status_matches']}/{res['total_cases']})")
    print(f"Sequence Accuracy: {res['sequence_accuracy_pct']:.2f}% ({res['step_exact_matches']}/{res['total_cases']})")
    print(f"Field Accuracy:    {res['field_accuracy_pct']:.2f}%")
    print("=" * 50)

    # Print failed case diagnostics
    failed = res.get("failed_cases_diagnostics", [])
    if failed:
        print(f"\nDETAILED FAILURE DIAGNOSTICS ({len(failed)} Cases with Mismatches):")
        print("-" * 50)
        for d in failed:
            print(f"Case: {d['case_id']}")
            print(f"  Status:          Expected={d['expected_status']} | Predicted={d['predicted_status']}")
            print(f"  Step Count:      Expected={d['expected_step_count']} | Predicted={d['predicted_step_count']}")
            print(f"  First Mismatch:  Step {d['first_mismatching_step']} (Fields: {d['mismatching_fields']})")
            if d['expected_step_content']:
                print(f"  Expected Step:   {json.dumps(d['expected_step_content'])}")
            if d['predicted_step_content']:
                print(f"  Predicted Step:  {json.dumps(d['predicted_step_content'])}")
            if d['missing_steps']:
                print(f"  Missing Steps:   {len(d['missing_steps'])} steps")
            if d['extra_steps']:
                print(f"  Extra Steps:     {len(d['extra_steps'])} steps")
            print("-" * 50)
