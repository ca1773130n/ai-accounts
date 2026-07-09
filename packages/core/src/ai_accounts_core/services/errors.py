class ServiceError(Exception):
    code: str = "service_error"


class BackendNotFound(ServiceError):
    code = "backend_not_found"


class BackendAlreadyExists(ServiceError):
    code = "backend_already_exists"


class BackendKindUnknown(ServiceError):
    code = "backend_kind_unknown"


class BackendNotReady(ServiceError):
    code = "backend_not_ready"


class BackendValidationFailed(ServiceError):
    code = "backend_validation_failed"


class CredentialMissing(ServiceError):
    code = "credential_missing"


class CredentialUnreadable(ServiceError):
    """Stored credential exists but cannot be decrypted — almost always a vault
    key mismatch (server started with a different AI_ACCOUNTS_VAULT_KEY than
    the one that encrypted the credential)."""

    code = "credential_unreadable"


class LoginFlowUnsupported(ServiceError):
    code = "login_flow_unsupported"
