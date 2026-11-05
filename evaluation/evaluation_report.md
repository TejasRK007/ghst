# Ghostinel Evaluation Report

## Scope and method

The prediction engine reads participant-facing files under `dataset/`, resolves current and historical identities, indexes the supplied evidence, applies the deletion policy, and writes the 518-case root `output.csv`. Sample quality is measured by generating predictions for `sample_deletion_requests.csv` and comparing them with the supplied public reference `sample_output.csv`. The reference is used only by the evaluator, not as an input to prediction generation.

## Latest results

| Measure | Result |
| --- | ---: |
| Public sample status accuracy | 100.00% (32/32) |
| Public sample exact sequence accuracy | 34.38% (11/32) |
| Public sample aligned-field accuracy | 83.64% (813/972) |
| Ground-truth steps / predicted steps | 193 / 166 |
| Full output rows | 518 |
| Full output status counts | 140 COMPLETE, 368 INCOMPLETE, 10 NOT_APPLICABLE |

The field metric compares six fields (`phase`, `operation`, `system_id`, `resource_id`, `state`, and `evidence_id`) at positions where both sequences have a step. It does not count missing or extra steps in that percentage; exact sequence accuracy does penalize those. Treat exact sequence accuracy as the stricter completeness measure. All 32 sample statuses match, but 21 sample step sequences differ. This sample score does not establish accuracy on the other 486 cases or on hidden evaluation data.

The mismatch report currently shows operation (36), system (42), resource (42), state (34), phase (3), and evidence ID (2) mismatches among aligned positions. Length differences account for additional missing or extra steps. The main remaining gaps are incomplete resource linkage for account/tombstone verification and mismatched step inclusion/order. Do not infer a resource from a user ID suffix or treat an activity claim as proof of current state.

## Additional regression cases

Four synthetic regression cases are implemented and runnable with `python3 -m unittest evaluation.test_custom_cases -v`. They test individual audit behaviors; they are not extra full-dataset ground-truth cases and their pass rate must not be presented as overall accuracy.

1. An active data flow must produce an evidence-cited finding, a disable action, and an uncited future verification.
2. When the same resource appears in multiple snapshots, the latest state at or before `audit_at` determines the result.
3. Evidence captured after `audit_at` must not be selected.
4. A request that explicitly asks to keep the account active must be `NOT_APPLICABLE` with an empty step list.

Latest local result: **4/4 regression cases passed**.

## Changes and limitations

- Resource state selection now chooses the latest case-matched snapshot at or before the audit cutoff, rather than depending on index traversal order.
- The output validator checks exact CSV headers, case coverage and natural numeric case order, step field schema, consecutive numbering, allowed operation/state pairs, phase order, and valid citations.
- The full output contract validation passed for all 518 rows.
- Exact sequence accuracy remains low (34.38%) on the 32 public sample cases. The auditor is not yet proven correct for every case; review evidence citations and unresolved resources before relying on an individual result.

## Reproduce

```bash
python3 -m unittest evaluation.test_custom_cases -v
python3 code/benchmark_samples.py
python3 code/main.py
```

`evaluation_report.json` contains the latest machine-readable sample comparison. Rerun the benchmark after changing the auditor and regenerate this report from that run before packaging.
