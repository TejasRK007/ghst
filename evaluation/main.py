"""
Ghostinel - Evaluation Entry Point.
Executes quantitative evaluation between predictions and ground-truth sample answers.
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from code.evaluation.evaluator import evaluate_predictions


def main():
    parser = argparse.ArgumentParser(description="Ghostinel Evaluation Runner")
    parser.add_argument("--ground-truth", default="dataset/sample_output.csv", help="Path to ground truth CSV (default: dataset/sample_output.csv)")
    parser.add_argument("--predictions", default="sample_predictions.csv", help="Path to predictions CSV (default: sample_predictions.csv)")
    parser.add_argument("--report", default="evaluation_report.json", help="Path to write detailed JSON report (default: evaluation_report.json)")
    args = parser.parse_args()

    metrics = evaluate_predictions(
        ground_truth_path=args.ground_truth,
        predictions_path=args.predictions,
        report_output_path=args.report,
        verbose=True
    )

    print("\n" + "=" * 50)
    print(f"Status Accuracy:   {metrics['status_accuracy_pct']:.2f}% ({metrics['status_matches']}/{metrics['total_cases']})")
    print(f"Sequence Accuracy: {metrics['sequence_accuracy_pct']:.2f}% ({metrics['step_exact_matches']}/{metrics['total_cases']})")
    print(f"Field Accuracy:    {metrics['field_accuracy_pct']:.2f}%")
    print("=" * 50)

    failed = metrics.get("failed_cases_diagnostics", [])
    if failed:
        print(f"\nDETAILED FAILURE DIAGNOSTICS ({len(failed)} Cases):")
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


if __name__ == "__main__":
    main()
