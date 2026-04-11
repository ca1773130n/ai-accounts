"""Reusable test utilities for Protocol conformance.

Adapter authors (in-tree and third-party) import from here to verify
their implementations match the contract.
"""

from .fakes import FakeAuth, FakeBackend, FakeStorage, FakeVault
from .storage_conformance import run_storage_conformance

__all__ = [
    "FakeAuth",
    "FakeBackend",
    "FakeStorage",
    "FakeVault",
    "run_storage_conformance",
]
