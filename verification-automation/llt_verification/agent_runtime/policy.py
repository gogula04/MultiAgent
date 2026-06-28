"""Verification policy helpers for LLT runs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Tuple


def _env_truthy(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class VerificationPolicy:
    """Policy gate for requirement-only verification."""

    requirement_only_default: bool = True
    implementation_reads_approved: bool = False
    tenant_id: str = "default"
    user_role: str = "engineer"
    allowed_evidence_sources: Tuple[str, ...] = (
        "requirement_text",
        "requirement_documents",
        "data_dictionary_csv",
        "data_dictionary_yaml",
        "uut_dictionary_csv",
        "uut_dictionary_yaml",
        "verification_docs",
        "approved_traceability_artifacts",
    )
    implementation_read_approval_env: str = "LLT_IMPLEMENTATION_READ_APPROVED"
    auto_learning_approval_env: str = "LLT_AUTO_LEARNING_APPROVED"
    tenant_id_env: str = "LLT_TENANT_ID"
    user_role_env: str = "LLT_USER_ROLE"
    audit_enabled: bool = True
    run_traceability_enabled: bool = True
    auto_learning_approved: bool = False
    tenant_isolation_enabled: bool = True
    allowed_roles: Tuple[str, ...] = ("viewer", "engineer", "approver", "admin")
    extra_metadata: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(
        cls,
        implementation_reads_approved: bool | None = None,
        auto_learning_approved: bool | None = None,
        tenant_id: str | None = None,
        user_role: str | None = None,
    ) -> "VerificationPolicy":
        approved = _env_truthy("LLT_IMPLEMENTATION_READ_APPROVED")
        learning_approved = _env_truthy("LLT_AUTO_LEARNING_APPROVED")
        env_tenant_id = os.getenv("LLT_TENANT_ID", "default").strip() or "default"
        env_user_role = os.getenv("LLT_USER_ROLE", "engineer").strip().lower() or "engineer"
        if implementation_reads_approved is not None:
            approved = implementation_reads_approved
        if auto_learning_approved is not None:
            learning_approved = auto_learning_approved
        if tenant_id is not None:
            env_tenant_id = tenant_id
        if user_role is not None:
            env_user_role = user_role.lower()
        return cls(
            implementation_reads_approved=approved,
            auto_learning_approved=learning_approved,
            tenant_id=env_tenant_id,
            user_role=env_user_role,
        )

    @property
    def requirement_only_mode(self) -> bool:
        return self.requirement_only_default and not self.implementation_reads_approved

    def implementation_access_allowed(self) -> bool:
        return self.implementation_reads_approved

    def auto_learning_allowed(self) -> bool:
        return self.auto_learning_approved and self.audit_enabled

    def normalized_tenant_id(self) -> str:
        value = self.tenant_id.strip().lower()
        return value if value else "default"

    def normalized_user_role(self) -> str:
        value = self.user_role.strip().lower()
        return value if value else "engineer"

    def role_index(self, role: str | None = None) -> int:
        target = (role or self.normalized_user_role()).strip().lower()
        try:
            return self.allowed_roles.index(target)
        except ValueError:
            return 0

    def has_role(self, required_role: str) -> bool:
        return self.role_index() >= self.role_index(required_role)

    def can_submit_jobs(self) -> bool:
        return self.has_role("engineer")

    def can_approve_jobs(self) -> bool:
        return self.has_role("approver")

    def can_administer(self) -> bool:
        return self.has_role("admin")

    def tenant_scope_path(self) -> str:
        return self.normalized_tenant_id() if self.tenant_isolation_enabled else "shared"

    def require_implementation_approval(self, action: str) -> None:
        if not self.implementation_access_allowed():
            raise PermissionError(
                f"Implementation-code access is blocked by policy for {action}. "
                f"Set {self.implementation_read_approval_env}=1 only when exception approval is granted."
            )

    def manifest(self) -> Dict[str, object]:
        return {
            "requirement_only_default": self.requirement_only_default,
            "implementation_reads_approved": self.implementation_reads_approved,
            "requirement_only_mode": self.requirement_only_mode,
            "allowed_evidence_sources": list(self.allowed_evidence_sources),
            "implementation_read_approval_env": self.implementation_read_approval_env,
            "auto_learning_approval_env": self.auto_learning_approval_env,
            "tenant_id_env": self.tenant_id_env,
            "user_role_env": self.user_role_env,
            "audit_enabled": self.audit_enabled,
            "run_traceability_enabled": self.run_traceability_enabled,
            "auto_learning_approved": self.auto_learning_approved,
            "auto_learning_enabled": self.auto_learning_allowed(),
            "tenant_id": self.tenant_id,
            "normalized_tenant_id": self.normalized_tenant_id(),
            "user_role": self.user_role,
            "normalized_user_role": self.normalized_user_role(),
            "tenant_isolation_enabled": self.tenant_isolation_enabled,
            "allowed_roles": list(self.allowed_roles),
            "can_submit_jobs": self.can_submit_jobs(),
            "can_approve_jobs": self.can_approve_jobs(),
            "can_administer": self.can_administer(),
            "extra_metadata": dict(self.extra_metadata),
        }
