"""Security boundaries, authentication/authorization providers, and credential sanitization."""

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from engine.service.errors import (
    AuthenticationRequiredError,
    AuthorizationForbiddenError,
    PayloadTooLargeError,
    ServiceError,
)

logger = logging.getLogger("pool_engine.security")


@dataclass(frozen=True)
class AuthContext:
    """Authentication and identity context for an API invocation."""
    authenticated: bool
    subject_id: Optional[str] = None
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    auth_type: str = "none"  # "firebase", "api_key", "noop", etc.
    email: Optional[str] = None
    claims: Mapping[str, Any] = field(default_factory=dict)


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
    Does not invent synthetic identities. Prohibited in production by default.
    """

    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> AuthContext:
        return AuthContext(authenticated=False, subject_id=None, auth_type="noop")

    def authorize(self, context: AuthContext, action: str, resource: str) -> bool:
        return True


class ApiKeyAuthProvider(AuthProvider):
    """
    Lightweight API-key authenticator checking `X-API-Key` or `Authorization: Bearer <key>`.
    Maps valid keys to subject IDs and authorized roles for server-to-server integrations.
    """

    def __init__(self, key_registry: Mapping[str, tuple[str, tuple[str, ...]]]) -> None:
        """
        key_registry maps API key string -> (subject_id, tuple of roles).
        Example: {"sec-admin-123": ("admin-svc", ("admin", "dispatch_operator"))}
        """
        self._registry = dict(key_registry)

    def is_registered_key(self, token: str) -> bool:
        """Checks if a given token string exists in the key registry."""
        return bool(token and token in self._registry)

    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> AuthContext:
        token = headers.get("x-api-key")
        if not token:
            auth_header = headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()

        if token and token in self._registry:
            subject_id, roles = self._registry[token]
            return AuthContext(
                authenticated=True,
                subject_id=subject_id,
                roles=roles,
                auth_type="api_key",
            )

        return AuthContext(authenticated=False, subject_id=None)

    def authorize(self, context: AuthContext, action: str, resource: str) -> bool:
        if not context.authenticated:
            return False
        if "admin" in context.roles:
            return True
        return action in context.roles


class FirebaseAuthProvider(AuthProvider):
    """
    Cryptographic Firebase Authentication ID token verifier.
    Validates token signature, issuer, audience/project ID, expiry, and revocation.
    Extracts authenticated Firebase UID and verified custom claims.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        check_revoked: bool = False,
        verifier: Optional[Callable[[str], dict[str, Any]]] = None,
    ) -> None:
        self._project_id = project_id
        self._credentials_path = credentials_path
        self._check_revoked = check_revoked
        self._custom_verifier = verifier
        self._app: Any = None

    def _get_app(self) -> Any:
        if self._app is not None:
            return self._app
        try:
            import firebase_admin  # type: ignore[import-untyped]
            try:
                self._app = firebase_admin.get_app()
                return self._app
            except ValueError:
                pass

            cred = None
            if self._credentials_path and os.path.isfile(self._credentials_path):
                from firebase_admin import credentials as fb_creds
                cred = fb_creds.Certificate(self._credentials_path)

            options: dict[str, Any] = {}
            if self._project_id:
                options["projectId"] = self._project_id

            self._app = firebase_admin.initialize_app(cred, options=options or None)
            return self._app
        except Exception as e:
            logger.error("Failed to initialize Firebase Admin SDK: %s", e)
            raise

    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> AuthContext:
        auth_header = headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return AuthContext(authenticated=False, subject_id=None)

        token = auth_header[7:].strip()
        if not token:
            return AuthContext(authenticated=False, subject_id=None)

        decoded: Optional[dict[str, Any]] = None
        try:
            if self._custom_verifier is not None:
                decoded = self._custom_verifier(token)
            else:
                from firebase_admin import auth as fb_auth
                app = self._get_app()
                decoded = fb_auth.verify_id_token(
                    token,
                    app=app,
                    check_revoked=self._check_revoked,
                )
        except Exception as exc:
            logger.debug("Firebase ID token verification rejected token: %s", exc)
            return AuthContext(authenticated=False, subject_id=None)

        if not isinstance(decoded, dict):
            return AuthContext(authenticated=False, subject_id=None)

        # Validate project ID and audience if configured
        if self._project_id:
            aud = decoded.get("aud")
            fb_claim = decoded.get("firebase", {})
            tenant = fb_claim.get("tenant") if isinstance(fb_claim, dict) else None
            if aud != self._project_id and tenant != self._project_id:
                logger.warning(
                    "Token audience '%s' does not match configured project ID '%s'",
                    aud,
                    self._project_id,
                )
                return AuthContext(authenticated=False, subject_id=None)

            iss = decoded.get("iss")
            expected_iss = f"https://securetoken.google.com/{self._project_id}"
            if iss != expected_iss:
                logger.warning(
                    "Token issuer '%s' does not match expected issuer '%s'",
                    iss,
                    expected_iss,
                )
                return AuthContext(authenticated=False, subject_id=None)

        uid = decoded.get("uid") or decoded.get("sub")
        if not uid or not isinstance(uid, str):
            return AuthContext(authenticated=False, subject_id=None)

        # Verified roles: only from server-set custom claims, never client-supplied headers
        roles_list: list[str] = []
        if decoded.get("admin") is True or decoded.get("role") == "admin":
            roles_list.append("admin")
        if decoded.get("dispatch_operator") is True or decoded.get("role") == "dispatch_operator":
            roles_list.append("dispatch_operator")
        if isinstance(decoded.get("roles"), (list, tuple)):
            for r in decoded["roles"]:
                if isinstance(r, str) and r not in roles_list:
                    roles_list.append(r)

        return AuthContext(
            authenticated=True,
            subject_id=str(uid),
            roles=tuple(roles_list),
            auth_type="firebase",
            email=decoded.get("email") if isinstance(decoded.get("email"), str) else None,
            claims=decoded,
        )

    def authorize(self, context: AuthContext, action: str, resource: str) -> bool:
        if not context.authenticated:
            return False
        if "admin" in context.roles:
            return True
        # End users cannot invoke automated dispatch
        if action == "dispatch" or resource == "/v1/dispatch":
            return "dispatch_operator" in context.roles or "dispatch" in context.roles
        # Standard user-level read/write permissions
        return True


class CompositeAuthProvider(AuthProvider):
    """
    Evaluates API-key and Firebase ID token authenticators in an explicit, tested strategy.
    Prioritizes X-API-Key or known server-to-server API keys, then verifies Firebase ID tokens.
    """

    def __init__(
        self,
        api_key_provider: Optional[ApiKeyAuthProvider] = None,
        firebase_provider: Optional[FirebaseAuthProvider] = None,
    ) -> None:
        self.api_key_provider = api_key_provider
        self.firebase_provider = firebase_provider

    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> AuthContext:
        # 1. Explicit X-API-Key header prioritizes API key auth
        if "x-api-key" in headers and self.api_key_provider is not None:
            ctx = self.api_key_provider.authenticate(scope, headers)
            if ctx.authenticated:
                return ctx

        # 2. Authorization: Bearer <token>
        auth_header = headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
            # If token is recognized in API key registry, authenticate as API key
            if self.api_key_provider is not None and self.api_key_provider.is_registered_key(token):
                ctx = self.api_key_provider.authenticate(scope, headers)
                if ctx.authenticated:
                    return ctx

            # Otherwise, evaluate as Firebase ID token
            if self.firebase_provider is not None:
                ctx = self.firebase_provider.authenticate(scope, headers)
                if ctx.authenticated:
                    return ctx

        return AuthContext(authenticated=False, subject_id=None)

    def authorize(self, context: AuthContext, action: str, resource: str) -> bool:
        if not context.authenticated:
            return False
        if context.auth_type == "api_key" and self.api_key_provider is not None:
            return self.api_key_provider.authorize(context, action, resource)
        if context.auth_type == "firebase" and self.firebase_provider is not None:
            return self.firebase_provider.authorize(context, action, resource)
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


def build_auth_provider_from_env(
    env: Optional[Mapping[str, str]] = None,
    config: Optional[Any] = None,
    verifier: Optional[Callable[[str], dict[str, Any]]] = None,
) -> AuthProvider:
    """
    Constructs an AuthProvider from environment variables or provided configuration.
    Inspects API_KEYS and FIREBASE_PROJECT_ID.
    Refuses NoOpAuthProvider in production environments unless explicitly overridden.
    """
    source = os.environ if env is None else env
    environment = (
        getattr(config, "environment", None)
        or source.get("ENVIRONMENT", "development")
    ).lower()
    is_prod = environment == "production"
    allow_unauth = (
        getattr(config, "allow_unauthenticated_in_production", False)
        or source.get("ALLOW_UNAUTHENTICATED_IN_PRODUCTION", "").lower() in ("true", "1", "yes")
    )

    # 1. API Key provider parsing
    api_key_provider: Optional[ApiKeyAuthProvider] = None
    raw_keys = source.get("API_KEYS", "").strip()
    if raw_keys:
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
            except Exception:
                pass

        if not registry:
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
            api_key_provider = ApiKeyAuthProvider(registry)

    # 2. Firebase provider parsing
    firebase_provider: Optional[FirebaseAuthProvider] = None
    fb_project = (
        getattr(config, "firebase_project_id", None)
        or source.get("FIREBASE_PROJECT_ID")
        or source.get("GCLOUD_PROJECT")
        or source.get("GOOGLE_CLOUD_PROJECT")
    )
    fb_creds = (
        getattr(config, "firebase_credentials_path", None)
        or source.get("FIREBASE_CREDENTIALS_PATH")
        or source.get("GOOGLE_APPLICATION_CREDENTIALS")
    )
    fb_check_revoked = (
        getattr(config, "firebase_check_revoked", False)
        or source.get("FIREBASE_CHECK_REVOKED", "").lower() in ("true", "1", "yes")
    )

    if fb_project or fb_creds or verifier is not None:
        firebase_provider = FirebaseAuthProvider(
            project_id=fb_project,
            credentials_path=fb_creds,
            check_revoked=fb_check_revoked,
            verifier=verifier,
        )

    # Strategy resolution
    if api_key_provider is not None and firebase_provider is not None:
        return CompositeAuthProvider(
            api_key_provider=api_key_provider,
            firebase_provider=firebase_provider,
        )
    elif firebase_provider is not None:
        return firebase_provider
    elif api_key_provider is not None:
        return api_key_provider

    if is_prod and not allow_unauth:
        raise ValueError(
            "Production environment requires a configured authentication provider (Firebase or API keys). "
            "NoOpAuthProvider is prohibited in production unless allow_unauthenticated_in_production=True."
        )

    return NoOpAuthProvider()
