import logging
import os

import jwt
from jwt import PyJWKClient, PyJWTError
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

_tenant_id = os.environ.get("AZURE_TENANT_ID", "")
_audience = os.environ.get("API_AUDIENCE", "")
_debug_log_claims = os.environ.get("DEBUG_LOG_CLAIMS", "").lower() in ("1", "true", "yes")

# Initialised once; PyJWKClient fetches keys lazily and caches them.
_jwks_client = PyJWKClient(
    f"https://login.microsoftonline.com/{_tenant_id}/discovery/v2.0/keys",
    cache_keys=True,
)

# Managed-identity tokens may carry either issuer depending on the token version.
_valid_issuers = frozenset({
    f"https://login.microsoftonline.com/{_tenant_id}/v2.0",
    f"https://sts.windows.net/{_tenant_id}/",
})


def require_role(role: str):
    """Return a FastAPI dependency that validates an Entra ID bearer token and checks `role`."""

    async def _dependency(authorization: str | None = Header(default=None)) -> dict:
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("auth_failed reason=missing_or_malformed_header")
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        token = authorization.removeprefix("Bearer ")

        try:
            signing_key = _jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=_audience,
                # Issuer validated manually below to accept both v2.0 and v1.0 URLs.
                options={
                    "verify_iss": False,
                    "require": ["exp", "iss", "aud"],
                },
            )
        except PyJWTError as exc:
            logger.warning("auth_failed reason=%s", exc)
            raise HTTPException(status_code=401, detail=str(exc))

        iss = claims.get("iss", "")
        if iss not in _valid_issuers:
            logger.warning("auth_failed reason=invalid_issuer iss=%s", iss)
            raise HTTPException(status_code=401, detail=f"Invalid issuer: {iss}")

        if role not in claims.get("roles", []):
            logger.warning(
                "auth_failed reason=missing_role appid=%s required_role=%s",
                claims.get("appid", "unknown"),
                role,
            )
            raise HTTPException(status_code=403, detail=f"Required role '{role}' not present")

        logger.info("auth_success appid=%s", claims.get("appid", "unknown"))

        if _debug_log_claims:
            logger.info("auth_debug_claims claims=%s", claims)

        return claims

    return _dependency
