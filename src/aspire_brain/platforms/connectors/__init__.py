"""Explicit read-only platform adapters; the normal application remains offline."""

from .core import ConnectorError, ConnectorSession, IdentityBinding, SourceRef


def connector_for(session: ConnectorSession):
    """Registry for explicitly constructed sessions, never automatic live activation."""
    from .adapters import ConfluenceConnector, DriveConnector, JiraConnector, SlackConnector

    registry = {"confluence": ConfluenceConnector, "jira": JiraConnector,
                "slack": SlackConnector, "drive": DriveConnector}
    if not isinstance(session, ConnectorSession) or session.platform not in registry:
        raise ConnectorError("invalid_configuration")
    return registry[session.platform](session)


__all__ = ["ConnectorError", "ConnectorSession", "IdentityBinding", "SourceRef", "connector_for"]
