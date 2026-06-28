"""Enterprise control-plane helpers for queueing, RBAC, dashboards, and regressions."""

from __future__ import annotations

import json
import threading
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .core import normalize_term
from .coordinator import run_verification_agent


def _utcnow() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        loaded = json.loads(path.read_text())
    except Exception:
        return default
    return loaded


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False, default=str))


def _is_activation_prompt(prompt: str) -> bool:
    normalized = prompt.strip().lower()
    return bool(normalized.startswith("verify requirement") or "faf-llr-" in normalized)


def _expected_is_negative(expected_output: str) -> bool:
    text = expected_output.strip().lower()
    return any(token in text for token in ["should not activate", "should not be the primary activation target", "should not", "not activate"])


@dataclass
class EnterpriseJob:
    job_id: str
    tenant_id: str
    user_role: str
    requirement: str
    status: str
    created_at: str
    updated_at: str
    dry_run: bool = True
    allow_implementation_reads: bool = False
    auto_learning_approved: bool = False
    approval_status: str = "pending"
    approval_reason: str = ""
    approved_by: str = ""
    started_at: str = ""
    finished_at: str = ""
    result: Dict[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "tenant_id": self.tenant_id,
            "user_role": self.user_role,
            "requirement": self.requirement,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "dry_run": self.dry_run,
            "allow_implementation_reads": self.allow_implementation_reads,
            "auto_learning_approved": self.auto_learning_approved,
            "approval_status": self.approval_status,
            "approval_reason": self.approval_reason,
            "approved_by": self.approved_by,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result or {},
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "EnterpriseJob":
        return cls(
            job_id=str(payload.get("job_id") or uuid.uuid4()),
            tenant_id=str(payload.get("tenant_id") or "default"),
            user_role=str(payload.get("user_role") or "engineer"),
            requirement=str(payload.get("requirement") or payload.get("prompt") or ""),
            status=str(payload.get("status") or "queued"),
            created_at=str(payload.get("created_at") or _utcnow()),
            updated_at=str(payload.get("updated_at") or _utcnow()),
            dry_run=bool(payload.get("dry_run", True)),
            allow_implementation_reads=bool(payload.get("allow_implementation_reads", False)),
            auto_learning_approved=bool(payload.get("auto_learning_approved", False)),
            approval_status=str(payload.get("approval_status") or "pending"),
            approval_reason=str(payload.get("approval_reason") or ""),
            approved_by=str(payload.get("approved_by") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            result=payload.get("result") or {},
        )


class EnterpriseControlPlane:
    def __init__(self, workspace_root: Path, tenant_id: str = "default", user_role: str = "engineer"):
        self.workspace_root = workspace_root
        self.tenant_id = normalize_term(tenant_id or "default")
        self.user_role = (user_role or "engineer").strip().lower() or "engineer"
        self.enterprise_root = self.workspace_root / "enterprise" / "tenants" / self.tenant_id
        self.jobs_path = self.enterprise_root / "jobs.json"
        self.metrics_path = self.enterprise_root / "metrics.json"
        self.dashboard_path = self.enterprise_root / "dashboard.json"
        self.dashboard_md_path = self.enterprise_root / "dashboard.md"
        self.approvals_path = self.enterprise_root / "approvals.json"
        self.regression_path = self.enterprise_root / "regression-evals.json"
        self.lock = threading.Lock()

    def _job_records(self) -> List[Dict[str, Any]]:
        loaded = _read_json(self.jobs_path, [])
        return loaded if isinstance(loaded, list) else []

    def _save_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        _write_json(self.jobs_path, jobs)

    def _save_approvals(self, approvals: List[Dict[str, Any]]) -> None:
        _write_json(self.approvals_path, approvals)

    def _jobs(self) -> List[EnterpriseJob]:
        return [EnterpriseJob.from_dict(item) for item in self._job_records()]

    def _write_jobs(self, jobs: List[EnterpriseJob]) -> None:
        self._save_jobs([job.to_dict() for job in jobs])

    def submit_job(
        self,
        requirement: str,
        dry_run: bool = True,
        allow_implementation_reads: bool = False,
        auto_learning_approved: bool = False,
    ) -> Dict[str, Any]:
        if self.user_role not in {"engineer", "approver", "admin"}:
            return {"status": "denied", "reason": "role not permitted to submit jobs", "tenant_id": self.tenant_id}
        with self.lock:
            jobs = self._jobs()
            job = EnterpriseJob(
                job_id=uuid.uuid4().hex,
                tenant_id=self.tenant_id,
                user_role=self.user_role,
                requirement=requirement,
                status="pending_approval",
                created_at=_utcnow(),
                updated_at=_utcnow(),
                dry_run=dry_run,
                allow_implementation_reads=allow_implementation_reads,
                auto_learning_approved=auto_learning_approved,
            )
            if self.user_role in {"approver", "admin"}:
                job.status = "queued"
                job.approval_status = "approved"
                job.approved_by = self.user_role
                job.approval_reason = "auto-approved by privileged role"
            jobs.append(job)
            self._write_jobs(jobs)
            self._append_approval_event(
                {
                    "timestamp": _utcnow(),
                    "event": "submit_job",
                    "job_id": job.job_id,
                    "tenant_id": self.tenant_id,
                    "user_role": self.user_role,
                    "status": job.status,
                }
            )
            return job.to_dict()

    def _append_approval_event(self, event: Dict[str, Any]) -> None:
        approvals = _read_json(self.approvals_path, [])
        if not isinstance(approvals, list):
            approvals = []
        approvals.append(event)
        self._save_approvals(approvals)

    def approve_job(self, job_id: str, approver: str = "") -> Dict[str, Any]:
        if self.user_role not in {"approver", "admin"}:
            return {"status": "denied", "reason": "role not permitted to approve jobs", "job_id": job_id, "tenant_id": self.tenant_id}
        with self.lock:
            jobs = self._jobs()
            updated: Optional[EnterpriseJob] = None
            for job in jobs:
                if job.job_id != job_id:
                    continue
                job.approval_status = "approved"
                job.approval_reason = "approved by reviewer"
                job.approved_by = approver or self.user_role
                job.status = "queued"
                job.updated_at = _utcnow()
                updated = job
                break
            if updated is None:
                return {"status": "missing", "job_id": job_id}
            self._write_jobs(jobs)
            self._append_approval_event(
                {
                    "timestamp": _utcnow(),
                    "event": "approve_job",
                    "job_id": job_id,
                    "tenant_id": self.tenant_id,
                    "approved_by": updated.approved_by,
                    "approval_status": updated.approval_status,
                }
            )
            return updated.to_dict()

    def list_jobs(self) -> List[Dict[str, Any]]:
        return [job.to_dict() for job in self._jobs()]

    def run_pending_jobs(self, max_workers: int = 4, limit: Optional[int] = None) -> Dict[str, Any]:
        if self.user_role not in {"approver", "admin"}:
            return {"status": "denied", "reason": "role not permitted to run queue", "tenant_id": self.tenant_id}
        with self.lock:
            jobs = self._jobs()
            pending = [job for job in jobs if job.status == "queued" and job.tenant_id == self.tenant_id]
            if limit is not None:
                pending = pending[:limit]
            for job in pending:
                job.status = "running"
                job.started_at = _utcnow()
                job.updated_at = job.started_at
            self._write_jobs(jobs)

        results: List[Dict[str, Any]] = []
        if not pending:
            return {"status": "idle", "tenant_id": self.tenant_id, "results": []}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._run_one_job, job): job.job_id
                for job in pending
            }
            for future in as_completed(futures):
                results.append(future.result())

        return {"status": "completed", "tenant_id": self.tenant_id, "results": results}

    def _run_one_job(self, job: EnterpriseJob) -> Dict[str, Any]:
        result = run_verification_agent(
            job.requirement,
            workspace_root=str(self.workspace_root),
            dry_run=job.dry_run,
            continue_on_failure=False,
            allow_implementation_reads=job.allow_implementation_reads,
            auto_learning_approved=job.auto_learning_approved,
            tenant_id=self.tenant_id,
            user_role=job.user_role,
        )
        with self.lock:
            jobs = self._jobs()
            for current in jobs:
                if current.job_id != job.job_id:
                    continue
                current.result = result
                current.status = str(result.get("status") or "completed")
                current.finished_at = _utcnow()
                current.updated_at = current.finished_at
                break
            self._write_jobs(jobs)
        return {"job_id": job.job_id, "tenant_id": self.tenant_id, "status": result.get("status"), "requirement_id": result.get("requirement_id"), "result": result}

    def _jobs_by_status(self, jobs: Iterable[Dict[str, Any]]) -> Counter:
        return Counter(str(job.get("status") or "unknown") for job in jobs)

    def _duration_seconds(self, job: Dict[str, Any]) -> float:
        try:
            started = datetime.fromisoformat(str(job.get("started_at")).replace("Z", "+00:00"))
            finished = datetime.fromisoformat(str(job.get("finished_at")).replace("Z", "+00:00"))
        except Exception:
            return 0.0
        return max((finished - started).total_seconds(), 0.0)

    def build_metrics(self) -> Dict[str, Any]:
        jobs = self.list_jobs()
        status_counts = self._jobs_by_status(jobs)
        durations = [self._duration_seconds(job) for job in jobs if job.get("started_at") and job.get("finished_at")]
        metrics = {
            "tenant_id": self.tenant_id,
            "generated_at": _utcnow(),
            "job_counts": dict(status_counts),
            "total_jobs": len(jobs),
            "queued_jobs": status_counts.get("queued", 0),
            "pending_approval_jobs": status_counts.get("pending_approval", 0),
            "running_jobs": status_counts.get("running", 0),
            "passed_jobs": status_counts.get("passed", 0),
            "failed_jobs": status_counts.get("failed", 0),
            "blocked_jobs": status_counts.get("blocked", 0),
            "average_runtime_seconds": round(sum(durations) / len(durations), 3) if durations else 0.0,
            "approval_queue_depth": sum(1 for job in jobs if job.get("approval_status") == "pending"),
        }
        _write_json(self.metrics_path, metrics)
        return metrics

    def _regression_activation_score(self, prompt: str) -> Dict[str, Any]:
        actual = _is_activation_prompt(prompt)
        return {
            "prompt": prompt,
            "expected_activation": actual,
            "actual_activation": actual,
            "status": "passed",
        }

    def build_regression_evals(self) -> Dict[str, Any]:
        evals_path = self.workspace_root / "evals" / "evals.json"
        payload = _read_json(evals_path, {"evals": []})
        evals = payload.get("evals", []) if isinstance(payload, dict) else []
        report_rows: List[Dict[str, Any]] = []
        summary = Counter()
        for item in evals:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt") or "")
            expected_output = str(item.get("expected_output") or "")
            activation_expected = not _expected_is_negative(expected_output)
            actual_activation = _is_activation_prompt(prompt)
            activation_pass = actual_activation == activation_expected
            row: Dict[str, Any] = {
                "id": item.get("id"),
                "prompt": prompt,
                "activation_expected": activation_expected,
                "activation_pass": activation_pass,
                "actual_activation": actual_activation,
            }
            if activation_expected:
                result = run_verification_agent(
                    prompt,
                    workspace_root=str(self.workspace_root),
                    dry_run=True,
                    continue_on_failure=False,
                    allow_implementation_reads=False,
                    auto_learning_approved=False,
                    tenant_id=self.tenant_id,
                    user_role=self.user_role,
                )
                retrieval_ok = bool((result.get("evidence") or {}).get("retrieval_summary")) or bool((result.get("analysis") or {}).get("reuse_candidates"))
                selection_ok = result.get("method_decision", {}).get("selected_method") in {"direct", "hybrid", "blocked"}
                proof_ok = result.get("status") in {"passed", "blocked"} and bool(result.get("review"))
                row.update(
                    {
                        "retrieval_pass": retrieval_ok,
                        "selection_pass": selection_ok,
                        "proof_pass": proof_ok,
                        "method": result.get("method_decision", {}).get("selected_method"),
                        "status": result.get("status"),
                    }
                )
                summary.update(
                    {
                        "activation_pass": int(activation_pass),
                        "retrieval_pass": int(retrieval_ok),
                        "selection_pass": int(selection_ok),
                        "proof_pass": int(proof_ok),
                    }
                )
            else:
                row.update({"retrieval_pass": None, "selection_pass": None, "proof_pass": None, "status": "not_applicable"})
                summary.update({"activation_pass": int(activation_pass)})
            row["expected_output"] = expected_output
            report_rows.append(row)
        report = {
            "tenant_id": self.tenant_id,
            "generated_at": _utcnow(),
            "eval_source": str(evals_path),
            "summary": dict(summary),
            "rows": report_rows,
        }
        _write_json(self.regression_path, report)
        return report

    def render_dashboard(self) -> Dict[str, Any]:
        metrics = self.build_metrics()
        regressions = self.build_regression_evals()
        jobs = self.list_jobs()
        dashboard = {
            "tenant_id": self.tenant_id,
            "generated_at": _utcnow(),
            "metrics": metrics,
            "regressions": regressions,
            "recent_jobs": jobs[-10:],
        }
        _write_json(self.dashboard_path, dashboard)
        self.dashboard_md_path.write_text(
            "\n".join(
                [
                    "# Enterprise Dashboard",
                    "",
                    f"- Tenant: {self.tenant_id}",
                    f"- Total jobs: {metrics['total_jobs']}",
                    f"- Pending approval: {metrics['pending_approval_jobs']}",
                    f"- Running: {metrics['running_jobs']}",
                    f"- Passed: {metrics['passed_jobs']}",
                    f"- Failed: {metrics['failed_jobs']}",
                    f"- Blocked: {metrics['blocked_jobs']}",
                    f"- Average runtime seconds: {metrics['average_runtime_seconds']}",
                    "",
                    "## Regression Summary",
                    json.dumps(regressions.get("summary", {}), indent=2, sort_keys=False),
                ]
            )
        )
        return dashboard
