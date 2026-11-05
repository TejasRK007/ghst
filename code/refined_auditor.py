"""
Refined Auditor for Ghostinel.
Accurately maps cases to their audit-time evidence snapshots and extracts exact user resources.
"""
import os
import sys
import glob
import json
import csv
import re
from datetime import datetime
from typing import Dict, List, Set, Optional, Tuple, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.models import (
    AuditStep, DeletionStatus, Phase,
    PHASE_ORDER, OPERATION_ORDER
)
from code.identity_resolver import IdentityResolver, UserIdentity
from code.evidence_indexer import EvidenceIndexer, Observation


class RefinedAuditor:
    def __init__(self, indexer: EvidenceIndexer, resolver: IdentityResolver, dataset_dir: str = "dataset"):
        self.indexer = indexer
        self.resolver = resolver
        self.dataset_dir = dataset_dir
        self.evidence_files = indexer.evidence_files
        self.worker_activities: List[Dict[str, str]] = []
        self._load_worker_activities()

    def _load_worker_activities(self):
        act_path = os.path.join(self.dataset_dir, "system_activity.csv")
        with open(act_path, mode="r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["source_system"] == "deletion_worker":
                    self.worker_activities.append(r)

    def _unique_account_worker_target(self, case_id: str, reported_at: str) -> Optional[str]:
        """Return an account resource only for a unique, close workflow-time match.

        Activity results are not proof of state. This uses the activity solely to
        identify a candidate target for a future verification. If another request
        or worker event is comparably close, the association is ambiguous and is
        discarded.
        """
        try:
            reported_dt = datetime.fromisoformat(reported_at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

        window_seconds = 300
        nearby_requests = []
        for filename in ("deletion_requests.csv", "sample_deletion_requests.csv"):
            path = os.path.join(self.dataset_dir, filename)
            if not os.path.isfile(path):
                continue
            with open(path, mode="r", encoding="utf-8") as source:
                for row in csv.DictReader(source):
                    try:
                        request_time = datetime.fromisoformat(row["reported_at"].replace("Z", "+00:00"))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if abs((request_time - reported_dt).total_seconds()) <= window_seconds:
                        nearby_requests.append(row["case_id"])
        if nearby_requests != [case_id]:
            return None

        candidates = []
        for activity in self.worker_activities:
            if activity.get("event_type") != "DELETE_RECORD" or activity.get("target_system") != "account_service":
                continue
            try:
                event_time = datetime.fromisoformat(activity["event_time"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                continue
            distance = abs((event_time - reported_dt).total_seconds())
            if distance <= window_seconds:
                candidates.append((distance, activity.get("resource_id", "")))
        candidates = [(distance, resource_id) for distance, resource_id in candidates if resource_id]
        candidates.sort()
        if not candidates:
            return None
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 60:
            return None

        # Do not assign one activity to multiple requests with nearby report times.
        best_distance, best_resource = candidates[0]
        for filename in ("deletion_requests.csv", "sample_deletion_requests.csv"):
            path = os.path.join(self.dataset_dir, filename)
            if not os.path.isfile(path):
                continue
            with open(path, mode="r", encoding="utf-8") as source:
                for row in csv.DictReader(source):
                    if row["case_id"] == case_id:
                        continue
                    try:
                        other_time = datetime.fromisoformat(row["reported_at"].replace("Z", "+00:00"))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if abs((other_time - reported_dt).total_seconds()) > window_seconds:
                        continue
                    if any(
                        a.get("resource_id") == best_resource
                        and a.get("event_type") == "DELETE_RECORD"
                        and a.get("target_system") == "account_service"
                        and abs((datetime.fromisoformat(a["event_time"].replace("Z", "+00:00")) - other_time).total_seconds()) <= window_seconds
                        for a in self.worker_activities
                    ):
                        return None
        return best_resource

    def is_not_applicable(self, text: str) -> bool:
        text_lower = text.lower()
        non_del_triggers = [
            "leave the account active", "keep the account as it is",
            "leave my profile", "download my account", "invoices for my records",
            "continue using the service", "leave the account as active"
        ]
        explicit_non_deletion = [
            "not asking for deletion", "not a request to erase", "not asking you to delete",
            "do not close the account", "don't close the account", "do not delete",
            "don't delete", "without removing any of my records", "still need the account",
            "still use it, so please", "information request, not", "only from marketing",
            "marketing lists only", "stop the promotional emails", "correct it without removing",
            "resetting the login", "need help resetting", "not asking for erasure",
        ]
        if any(trigger in text_lower for trigger in explicit_non_deletion):
            return True
        return any(trigger in text_lower for trigger in non_del_triggers)

    def find_evidence_for_case(self, email: str, uid: Optional[str], audit_at_str: str, user_tokens: Optional[Set[str]] = None) -> List[str]:
        if user_tokens is None:
            user = self.resolver.resolve_by_email(email)
            user_tokens = self.resolver.get_all_identifiers(user) if user else {email}
            if uid:
                user_tokens.add(uid)

        audit_dt = datetime.fromisoformat(audit_at_str.replace("Z", ""))
        user_ev_ids: Dict[str, datetime] = {}
        for o in self.indexer.all_observations:
            is_match = False
            if o.email and o.email.lower() in [t.lower() for t in user_tokens if "@" in t]:
                is_match = True
            elif o.user_id and o.user_id in user_tokens:
                is_match = True
            elif o.name and o.name.lower() in [t.lower() for t in user_tokens if not "@" in t]:
                is_match = True

            if is_match:
                eid = o.evidence_id
                if eid:
                    cap_str = self.evidence_files.get(eid, {}).get("captured_at") or next(
                        (obs.captured_at for obs in self.indexer.all_observations if obs.evidence_id == eid),
                        "",
                    )
                    if not cap_str:
                        continue
                    cap_dt = datetime.fromisoformat(cap_str.replace("Z", ""))
                    if cap_dt <= audit_dt:
                        user_ev_ids[eid] = cap_dt

        # Return every matching, timely evidence file in chronological order.
        # The caller lets newer snapshots replace earlier observations of a resource.
        return sorted(user_ev_ids, key=lambda eid: user_ev_ids[eid])

    def audit_case(self, case_id: str, email: str, requested_at: str, reported_status: str, reported_at: str, audit_at: str, request_text: str) -> Tuple[str, List[Dict[str, Any]]]:
        if self.is_not_applicable(request_text):
            return DeletionStatus.NOT_APPLICABLE.value, []

        user = self.resolver.resolve_by_email(email)
        uid = user.user_id if user else None
        user_tokens = self.resolver.get_all_identifiers(user) if user else {email}

        # 1. Authoritative evidence files
        evidence_ids = self.find_evidence_for_case(email, uid, audit_at, user_tokens)
        
        # 2. Collect direct observations from authoritative evidence
        case_obs: Dict[str, Observation] = {}
        for eid in evidence_ids:
            for o in self.indexer.all_observations:
                if o.evidence_id == eid:
                    is_match = False
                    if o.email and o.email.lower() in [t.lower() for t in user_tokens if "@" in t]:
                        is_match = True
                    elif o.user_id and o.user_id in user_tokens:
                        is_match = True
                    elif o.name and o.name.lower() in [t.lower() for t in user_tokens if not "@" in t]:
                        is_match = True
                    
                    if is_match:
                        case_obs[f"{o.system_id}::{o.resource_id}"] = o

        # 3. Security Audit Record:
        # Check if user has an audit_record in case_obs
        has_audit_rec = any("audit_record" in rid for rid in case_obs)
        if not has_audit_rec:
            # Look in all observations for user's audit_record
            for o in self.indexer.all_observations:
                if o.category == "SECURITY_AUDIT_LOG" or "audit_record" in o.resource_id:
                    cap = self.evidence_files.get(o.evidence_id, {}).get("captured_at", "")
                    cap_dt = datetime.fromisoformat(cap.replace("Z", "")) if cap else None
                    if cap_dt and cap_dt <= datetime.fromisoformat(audit_at.replace("Z", "")) and ((o.user_id and o.user_id in user_tokens) or (o.email and o.email.lower() in {str(t).lower() for t in user_tokens if "@" in str(t)})):
                        case_obs[f"{o.system_id}::{o.resource_id}"] = o
                        has_audit_rec = True

        # 4. Generate Audit Steps from participant-visible observations only.
        raw_steps: List[AuditStep] = []
        has_findings = False

        for _, obs in sorted(case_obs.items()):
            res_id = obs.resource_id
            sys_id = obs.system_id
            cat = obs.category
            stat = obs.status
            ev_id = obs.evidence_id

            if cat in ["USER_PROFILE", "SEARCH_INDEX_ENTRY", "USER_EXPORT", "SUPPORT_ATTACHMENT", "MARKETING_PROFILE"] or "account" in res_id or "search" in res_id or "export" in res_id:
                if stat == "PRESENT":
                    has_findings = True
                    raw_steps.append(AuditStep(0, Phase.FINDING.value, sys_id, res_id, "REPORT_REMAINING_RECORD", "PRESENT", ev_id))
                    raw_steps.append(AuditStep(0, Phase.REMEDIATION.value, sys_id, res_id, "DELETE_RECORD", "ABSENT", ""))
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
                else:
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ev_id))

            elif cat == "ANALYTICS_PROFILE" or "analytics" in res_id:
                if stat == "PRESENT" or "contact_lookup_completed" in obs.raw_info:
                    has_findings = True
                    raw_steps.append(AuditStep(0, Phase.FINDING.value, sys_id, res_id, "REPORT_REMAINING_RECORD", "PRESENT", ev_id))
                    raw_steps.append(AuditStep(0, Phase.REMEDIATION.value, sys_id, res_id, "DELETE_RECORD", "ABSENT", ""))
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
                elif stat == "IDENTIFIABLE":
                    has_findings = True
                    raw_steps.append(AuditStep(0, Phase.FINDING.value, sys_id, res_id, "REPORT_EXPOSED_PII", "PRESENT", ev_id))
                    raw_steps.append(AuditStep(0, Phase.REMEDIATION.value, sys_id, res_id, "ANONYMIZE_RECORD", "ANONYMIZED", ""))
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", ""))
                else:
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", ev_id))

            elif cat == "SUPPORT_REPLICA":
                # Contact record remaining in support database replica
                if stat == "PRESENT":
                    has_findings = True
                    raw_steps.append(AuditStep(0, Phase.FINDING.value, sys_id, res_id, "REPORT_REMAINING_RECORD", "PRESENT", ev_id))
                    raw_steps.append(AuditStep(0, Phase.REMEDIATION.value, sys_id, res_id, "DELETE_RECORD", "ABSENT", ""))
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""))
                else:
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_ABSENT", "ABSENT", ev_id))

            elif cat in ["SUPPORT_MESSAGE", "ACCOUNT_TOMBSTONE"] or "support" in res_id or "tombstone" in res_id:
                if stat in ["IDENTIFIABLE", "PRESENT"]:
                    has_findings = True
                    raw_steps.append(AuditStep(0, Phase.FINDING.value, sys_id, res_id, "REPORT_EXPOSED_PII", "PRESENT", ev_id))
                    raw_steps.append(AuditStep(0, Phase.REMEDIATION.value, sys_id, res_id, "REDACT_RECORD", "REDACTED", ""))
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_REDACTED", "REDACTED", ""))
                else:
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_REDACTED", "REDACTED", ev_id))

            elif cat == "DATA_FLOW" or "data_flow" in res_id:
                if stat == "ACTIVE":
                    has_findings = True
                    raw_steps.append(AuditStep(0, Phase.FINDING.value, sys_id, res_id, "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", ev_id))
                    raw_steps.append(AuditStep(0, Phase.REMEDIATION.value, sys_id, res_id, "DISABLE_DATA_FLOW", "DISABLED", ""))
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ""))
                else:
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ev_id))

            elif cat == "BACKUP_ARCHIVE" or "backup" in res_id:
                if stat in ["RESTORE_RISK", "ACTIVE", "PRESENT"]:
                    has_findings = True
                    raw_steps.append(AuditStep(0, Phase.FINDING.value, sys_id, res_id, "REPORT_RESTORE_RISK", "ACTIVE", ev_id))
                    raw_steps.append(AuditStep(0, Phase.REMEDIATION.value, sys_id, res_id, "BLOCK_RESTORE", "BLOCKED", ""))
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RESTORE_BLOCKED", "BLOCKED", ""))
                else:
                    raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RESTORE_BLOCKED", "BLOCKED", ev_id))

            elif cat in ["SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"] or "audit_record" in res_id:
                raw_steps.append(AuditStep(0, Phase.VERIFICATION.value, sys_id, res_id, "VERIFY_RECORD_PRESENT", "PRESENT", ev_id))

        final_status = DeletionStatus.INCOMPLETE.value if has_findings else DeletionStatus.COMPLETE.value

        # A live search document can retain the primary account resource it was
        # built from. When that document is a finding, include an explicit
        # post-remediation check for the linked account resource as well. The
        # document establishes the relationship only; it does not establish the
        # account's current state, so this remains an uncited future check.
        if final_status == DeletionStatus.INCOMPLETE.value:
            existing_checks = {
                (step.system_id, step.resource_id)
                for step in raw_steps
                if step.phase == Phase.VERIFICATION.value
            }
            linked_accounts: Set[str] = set()
            for obs in case_obs.values():
                if obs.category != "SEARCH_INDEX_ENTRY" or obs.status != "PRESENT":
                    continue
                linked_accounts.update(re.findall(r"\baccount_[0-9]+\b", obs.raw_info or ""))
            worker_target = self._unique_account_worker_target(case_id, reported_at)
            if worker_target:
                linked_accounts.add(worker_target)
            for resource_id in sorted(linked_accounts):
                if ("account_service", resource_id) not in existing_checks:
                    raw_steps.append(AuditStep(
                        0, Phase.VERIFICATION.value, "account_service", resource_id,
                        "VERIFY_RECORD_ABSENT", "ABSENT", ""
                    ))

        if final_status == DeletionStatus.COMPLETE.value:
            selected_steps = [s for s in raw_steps if s.phase == Phase.VERIFICATION.value]
        else:
            selected_steps = []
            for s in raw_steps:
                if s.phase in [Phase.REMEDIATION.value, Phase.VERIFICATION.value]:
                    s.evidence_id = ""
                selected_steps.append(s)

        # Strict sorting
        def sort_key(s: AuditStep):
            p_order = PHASE_ORDER.get(Phase(s.phase), 99)
            op_order = OPERATION_ORDER.get(s.operation, 99)
            return (p_order, op_order, s.system_id, s.resource_id)

        selected_steps.sort(key=sort_key)

        for i, s in enumerate(selected_steps):
            s.step_no = i + 1

        steps_dicts = [s.to_dict() for s in selected_steps]
        return final_status, steps_dicts
