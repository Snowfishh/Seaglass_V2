"""Tenant-scoped tamper-evident audit records, with externally supplied keys."""

from .engine import AuditError, AuditWriter
from .protected import ProtectedAuditStore

__all__ = ["AuditError", "AuditWriter", "ProtectedAuditStore"]
