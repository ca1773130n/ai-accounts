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


class LoginFlowUnsupported(ServiceError):
    code = "login_flow_unsupported"
