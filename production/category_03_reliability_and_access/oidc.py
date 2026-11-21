"""
- Verify bearer access tokens using a configured issuer, audience, and JWKS URL.
- Accept RS256 signatures and require identity and expiry claims.
- Map verified tenant and permission claims into the existing Principal.
"""

import os
from urllib.parse import urlparse

import jwt

from production.category_03_reliability_and_access.security import AuthenticationFailed, Principal

PERMISSIONS = frozenset({"submit_feedback", "read_job", "approve_action", "cancel_job"})


class IdentityProviderUnavailable(RuntimeError):
    """The configured signing-key service could not be reached."""


def validate_endpoint(url: str, allow_local_http: bool = False) -> None:
    """
    - Require HTTPS for configured identity and notification endpoints.
    - Permit explicit HTTP loopback endpoints for local integration tests.
    """
    parsed = urlparse(url)
    local_http = (
        allow_local_http and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )
    if (
        not parsed.hostname or parsed.username is not None
        or parsed.password is not None or parsed.fragment
        or (parsed.scheme != "https" and not local_http)
    ):
        raise ValueError("Use an HTTPS endpoint, or explicitly allow local HTTP.")


class OIDCAuthenticator:
    """
    - Fetch signing keys only from the server-configured JWKS endpoint.
    - Verify the token before reading its tenant and permissions.
    - Cache signing-key sets using PyJWT's JWKS client.
    """

    def __init__(
        self, issuer: str, audience: str, jwks_url: str, *,
        tenant_claim: str = "tenant_id", permissions_claim: str = "scope",
        allow_local_http: bool = False,
    ) -> None:
        """
        - Configure an exact issuer and API-specific audience.
        - Require explicit tenant and permission claim names.
        """
        validate_endpoint(issuer, allow_local_http)
        validate_endpoint(jwks_url, allow_local_http)
        if not audience.strip() or not tenant_claim.strip() or not permissions_claim.strip():
            raise ValueError("Audience and claim names are required.")
        self.issuer = issuer
        self.audience = audience
        self.tenant_claim = tenant_claim
        self.permissions_claim = permissions_claim
        self.jwks = jwt.PyJWKClient(jwks_url, timeout=5, lifespan=300)

    @classmethod
    def from_environment(cls) -> "OIDCAuthenticator | None":
        """
        - Enable OIDC when its three required settings are configured.
        - Reject a partial configuration at startup.
        """
        values = [
            os.environ.get("FEEDBACK_OIDC_ISSUER", ""),
            os.environ.get("FEEDBACK_OIDC_AUDIENCE", ""),
            os.environ.get("FEEDBACK_OIDC_JWKS_URL", ""),
        ]
        if not any(values):
            return None
        if not all(values):
            raise ValueError("Set OIDC issuer, API audience, and JWKS URL together.")
        return cls(
            *values,
            tenant_claim=os.environ.get("FEEDBACK_OIDC_TENANT_CLAIM", "tenant_id"),
            permissions_claim=os.environ.get("FEEDBACK_OIDC_PERMISSIONS_CLAIM", "scope"),
            allow_local_http=os.environ.get("FEEDBACK_OIDC_ALLOW_LOCAL_HTTP") == "1",
        )

    def authenticate(self, token: str) -> Principal:
        """
        - Reject unexpected algorithms before signing-key lookup.
        - Validate signature, issuer, audience, expiry, issue time, and subject.
        - Grant only recognized permissions from verified claims.
        """
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise AuthenticationFailed("Unsupported token signature algorithm.")
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=["RS256"],
                audience=self.audience, issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWKClientConnectionError as error:
            raise IdentityProviderUnavailable("Signing keys are unavailable.") from error
        except (jwt.PyJWTError, ValueError, TypeError) as error:
            raise AuthenticationFailed("The bearer token is invalid.") from error

        tenant = claims.get(self.tenant_claim)
        subject = claims.get("sub")
        permissions = claims.get(self.permissions_claim, "")
        if isinstance(permissions, str):
            permissions = permissions.split()
        if (
            not isinstance(tenant, str) or not tenant.strip()
            or not isinstance(subject, str) or not subject.strip()
            or not isinstance(permissions, list)
            or any(not isinstance(permission, str) for permission in permissions)
        ):
            raise AuthenticationFailed("Required identity claims are invalid.")
        return Principal(subject, tenant, frozenset(permissions) & PERMISSIONS)
