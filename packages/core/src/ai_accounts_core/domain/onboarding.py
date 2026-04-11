from enum import Enum

import msgspec


class OnboardingStep(str, Enum):
    WELCOME = "welcome"
    DETECT = "detect"
    PICK_BACKEND = "pick_backend"
    LOGIN = "login"
    VALIDATE = "validate"
    DONE = "done"


class OnboardingState(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    current_step: OnboardingStep
    selected_backend_kind: str | None = None
    created_backend_id: str | None = None
    error: str | None = None
