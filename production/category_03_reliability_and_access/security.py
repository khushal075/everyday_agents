"""
Check tenant scope and permission before accessing a job or tool.
"""

from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class Principal:
    """
    A authenticated caller and its trusted permissions.
    """
    subject_id: str
    tenant_id: str
    permissions: frozenset[str]

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.tenant_id.strip():
            raise ValueError("Caller and tenant identifiers are required")


class AccessDenied(PermissionError):
    """
    The caller lacks access to the requested operation.
    """


class AccessPolicy:
    """
    Require tenant ownership and specific permissions.
    """
    def require(
        self,
        principal: Principal,
        *,
        resource_tenant_id: str,
        permission: str,
    ) -> None:
        """
        Return normally when access is allowed, otherwise raise.
        """
        if not resource_tenant_id.strip() or not permission.strip():
            raise ValueError("Resource tenant and Permission are required")

        if principal.tenant_id != resource_tenant_id:
            raise AccessDenied("The resource belongs to another tenant")

        if permission not in principal.permissions:
            raise AccessDenied(f"The permission: {permission} does not exist.")


class AuthenticationFailed(PermissionError):
    """The supplied API credential is missing or unknown."""


class CredentialResolver:
    """Resolve server-configured API keys into trusted identities."""

    def __init__(self, credentials: Mapping[str, Principal]) -> None:
        if any(not key for key in credentials):
            raise ValueError("API keys must not be empty.")
        self.credentials = dict(credentials)

    def authenticate(self, api_key: str | None) -> Principal:
        """Return the identity configured for this API key."""
        principal = self.credentials.get(api_key or "")
        if principal is None:
            raise AuthenticationFailed("A valid API key is required.")
        return principal
