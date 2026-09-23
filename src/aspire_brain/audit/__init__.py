"""Tenant-scoped tamper-evident audit records, with externally supplied keys."""

from .engine import AuditError, AuditWriter

__all__ = ["AuditError", "AuditWriter"]
