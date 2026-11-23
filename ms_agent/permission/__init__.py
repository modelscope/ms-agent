"""Permission module — dual-layer permission control for tool calls.

Outer layer (PermissionEnforcer): user-intent based, configurable, overridable.
Inner layer (SafetyGuard): safety baseline, non-bypassable.
"""

from .ask_resolver import resolve_ask
from .config import (PermissionConfig, SafetyConfig,
                     normalize_permission_mode)
from .provider import (AgentDecisionProvider, LlmDecisionProvider,
                       ProviderDecision)
from .enforcer import PermissionDecision, PermissionEnforcer
from .handler import (AutoPermissionHandler, CLIPermissionHandler,
                      PermissionAction, PermissionHandler, PermissionResponse,
                      WebPermissionHandler)
from .memory import PermissionMemory
from .safety import SafetyGuard

__all__ = [
    'resolve_ask',
    'normalize_permission_mode',
    'PermissionConfig',
    'SafetyConfig',
    'AgentDecisionProvider',
    'LlmDecisionProvider',
    'ProviderDecision',
    'PermissionDecision',
    'PermissionEnforcer',
    'AutoPermissionHandler',
    'CLIPermissionHandler',
    'PermissionAction',
    'PermissionHandler',
    'PermissionResponse',
    'WebPermissionHandler',
    'PermissionMemory',
    'SafetyGuard',
]
