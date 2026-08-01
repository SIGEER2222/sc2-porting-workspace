"""CMRE Neuro adapter contracts and runtime components."""

from .neuro.actions import ActionCommand, ActionDefinition, ExecutionResult
from .neuro.context import ContextEnvelope
from .neuro.errors import ContractErrorCode, ContractViolation
from .neuro.evidence import EvidenceRecord, EvidenceType
from .neuro.messages import IncomingMessage, NeuroMessageBuilder, parse_incoming_message
from .neuro.session import NeuroSessionIdentity

__all__ = [
    "ActionCommand",
    "ActionDefinition",
    "ContextEnvelope",
    "ContractErrorCode",
    "ContractViolation",
    "EvidenceRecord",
    "EvidenceType",
    "ExecutionResult",
    "IncomingMessage",
    "NeuroMessageBuilder",
    "NeuroSessionIdentity",
    "parse_incoming_message",
]
