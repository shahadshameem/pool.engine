"""Security boundaries, authentication/authorization providers, and credential sanitization."""

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from engine.service.errors import (
    AuthenticationRequiredError,
    AuthorizationForbiddenError,
    PayloadTooLargeError,
    ServiceError,
)


@dataclass(frozen=True)
class AuthContext:
    """Authentication and identity context for an API invocation."""
    authenticated: bool
    subject_id: Optional[str] = None
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()


class AuthProvider(ABC):
    """Provider-independent interface for API authentication and authorization."""

    @abstractmethod
    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> AuthContext:
        """Inspects request scope and headers to establish identity and credentials."""
        pass

    @abstractmethod
    def authorize(self, context: AuthContext, action: str, resource: str) -> bool:
        """Evaluates whether the caller context has permission to execute action on resource."""
        pass


class NoOpAuthProvider(AuthProvider):
    """
    Default authentication provider for environments where external API gateways
    or service meshes handle identity, or authentication is not enabled.
    Does not invent synthetic identities.
    """

    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> AuthContext:
        return AuthContext(authenticated=False, subject_id=None)

    def authorize(self, context: AuthContext, action: str, resource: str) -> bool:
        return True


class ApiKeyAuthProvider(AuthProvider):
    """
    Lightweight API-key authenticator checking `X-API-Key` or `Authorization: Bearer <key>`.
    Maps valid keys to subject IDs and authorized roles.
    """

    def __init__(self, key_registry: Mapping[str, tuple[str, tuple[str, ...]]]) -> None:
        """
        key_registry maps API key string -> (subject_id, tuple of roles).
        Example: {"sec-admin-123": ("admin-svc", ("admin", "dispatch_operator"))}
        """
        self._registry = dict(key_registry)

    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> AuthContext:
        token = headers.get("x-api-key")
        if not token:
            auth_header = headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()

        if token and token in self._registry:
            subject_id, roles = self._registry[token]
            return AuthContext(authenticated=True, subject_id=subject_id, roles=roles)

        return AuthContext(authenticated=False, subject_id=None)

    def authorize(self, context: AuthContext, action: str, resource: str) -> bool:
        if not context.authenticated:
            return False
        if "admin" in context.roles:
            return True
        return action in context.roles


def sanitize_sensitive_strings(text: str) -> str:
    """
    Redacts credentials and passwords from connection strings and URLs.
    Example: postgresql://postgres:secret123@localhost:5432/db -> postgresql://postgres:***@localhost:5432/db
    """
    if not text:
        return text
    # Mask password in URL / DSN patterns: ://user:password@host
    return re.sub(r"://([^:@/\s]+):([^\s/]+)@([a-zA-Z0-9_\-\.]+)", r"://\1:***@\3", text)


def build_auth_provider_from_env(env: Optional[Mapping[str, str]] = None) -> AuthProvider:
    """
    Constructs an AuthProvider from environment variables or provided mapping.
    Inspects API_KEYS formatted as JSON or comma-separated tokens (token:role).
    Returns NoOpAuthProvider if API_KEYS is unset or empty.
    """
    source = os.environ if env is None else env
    raw_keys = source.get("API_KEYS", "").strip()
    if not raw_keys:
        return NoOpAuthProvider()

    registry: dict[str, tuple[str, tuple[str, ...]]] = {}
    if raw_keys.startswith("{"):
        try:
            parsed = json.loads(raw_keys)
            if isinstance(parsed, dict):
                for key_token, val in parsed.items():
                    if isinstance(val, (list, tuple)) and len(val) >= 2:
                        subj = str(val[0])
                        roles = tuple(str(r) for r in val[1])
                        registry[str(key_token)] = (subj, roles)
                    elif isinstance(val, str):
                        registry[str(key_token)] = (str(val), ("admin",))
                if registry:
                    return ApiKeyAuthProvider(registry)
        except Exception:
            pass

    for entry in raw_keys.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            token, role = entry.split(":", 1)
            token = token.strip()
            role = role.strip()
            registry[token] = (token, (role,))
        else:
            registry[entry] = (entry, ("admin",))

    if registry:
        return ApiKeyAuthProvider(registry)
    return NoOpAuthProvider()
