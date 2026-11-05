"""Synthetic regression cases for identity, point-in-time state, and intent."""

import csv
import tempfile
import unittest
from pathlib import Path

from code.models import Observation, UserIdentity
from code.refined_auditor import RefinedAuditor


class StubResolver:
    def __init__(self):
        self.user = UserIdentity(
            user_id="user_test_1",
            name="Test User",
            email="current@example.test",
            phone="+10000000000",
            email_hash="hash-current",
            updated_at="2026-01-01T00:00:00Z",
        )
        self.user.historical_emails.add("old@example.test")

    def resolve_by_email(self, email):
        if email.lower() in {self.user.email.lower(), "old@example.test"}:
            return self.user
        return None

    def resolve_by_id(self, user_id):
        return self.user if user_id == self.user.user_id else None

    def get_all_identifiers(self, user):
        return {
            user.user_id, user.name, user.email, user.phone, user.email_hash,
            *user.historical_emails,
        }


class StubIndexer:
    def __init__(self, observations):
        self.all_observations = observations
        self.evidence_files = {
            observation.evidence_id: {
                "captured_at": observation.captured_at,
                "file_path": f"evidence/{observation.evidence_id}.json",
            }
            for observation in observations
        }


class CustomEvaluationCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        activity_path = Path(self.temp_dir.name) / "system_activity.csv"
        with activity_path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow([
                "source_system", "target_system", "event_type", "event_time",
                "resource_id", "details",
            ])
        self.resolver = StubResolver()

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_auditor(self, observations):
        return RefinedAuditor(
            indexer=StubIndexer(observations),
            resolver=self.resolver,
            dataset_dir=self.temp_dir.name,
        )

    def observation(self, evidence_id, captured_at, system_id, resource_id, category, status):
        return Observation(
            evidence_id=evidence_id,
            file_path=f"evidence/{evidence_id}.json",
            captured_at=captured_at,
            system_id=system_id,
            resource_id=resource_id,
            user_id=self.resolver.user.user_id,
            email=self.resolver.user.email,
            name=self.resolver.user.name,
            status=status,
            category=category,
        )

    def run_case(self, auditor, request_text="Please delete my account.", audit_at="2026-01-10T00:00:00Z"):
        return auditor.audit_case(
            case_id="custom_case",
            email=self.resolver.user.email,
            requested_at="2026-01-01T00:00:00Z",
            reported_status="COMPLETE",
            reported_at="2026-01-02T00:00:00Z",
            audit_at=audit_at,
            request_text=request_text,
        )

    def test_active_data_flow_produces_finding_remediation_and_future_check(self):
        evidence = self.observation(
            "evidence_flow", "2026-01-03T00:00:00Z", "integration_service",
            "data_flow_1", "DATA_FLOW", "ACTIVE",
        )
        status, steps = self.run_case(self.make_auditor([evidence]))
        self.assertEqual(status, "INCOMPLETE")
        self.assertEqual(
            [step["operation"] for step in steps],
            ["REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"],
        )
        self.assertEqual(steps[0]["evidence_id"], "evidence_flow")
        self.assertEqual([step["step_no"] for step in steps], [1, 2, 3])

    def test_latest_pre_cutoff_snapshot_controls_resource_state(self):
        earlier = self.observation(
            "evidence_old", "2026-01-02T00:00:00Z", "account_service",
            "account_1", "USER_PROFILE", "PRESENT",
        )
        latest = self.observation(
            "evidence_latest", "2026-01-05T00:00:00Z", "account_service",
            "account_1", "USER_PROFILE", "ABSENT",
        )
        status, steps = self.run_case(self.make_auditor([earlier, latest]))
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["operation"], "VERIFY_RECORD_ABSENT")
        self.assertEqual(steps[0]["evidence_id"], "evidence_latest")

    def test_evidence_after_audit_cutoff_is_excluded(self):
        future = self.observation(
            "evidence_future", "2026-01-11T00:00:00Z", "account_service",
            "account_2", "USER_PROFILE", "PRESENT",
        )
        auditor = self.make_auditor([future])
        evidence_ids = auditor.find_evidence_for_case(
            self.resolver.user.email,
            self.resolver.user.user_id,
            "2026-01-10T00:00:00Z",
            self.resolver.get_all_identifiers(self.resolver.user),
        )
        self.assertEqual(evidence_ids, [])

    def test_non_deletion_request_is_not_applicable(self):
        status, steps = self.run_case(
            self.make_auditor([]),
            request_text="Please update my phone but leave the account active.",
        )
        self.assertEqual(status, "NOT_APPLICABLE")
        self.assertEqual(steps, [])


if __name__ == "__main__":
    unittest.main()
