"""Typed contracts for the Neuro game API boundary."""

from .actions import ActionCommand, ActionDefinition, ExecutionResult
from .context import ContextEnvelope
from .errors import ContractErrorCode, ContractViolation
from .evidence import EvidenceRecord, EvidenceType
from .messages import IncomingMessage, NeuroMessageBuilder, parse_incoming_message
from .schemas import SchemaValidationError, validate_action_arguments
from .session import NeuroSessionIdentity
from .mission_projection import (
    MissionContextProjector,
    ProjectionError,
    PublicMissionContext,
    PublicObjective,
    PublicUnit,
    StaleContextError,
    ThreatSummary,
    project_observation,
)
from .simulator_transport import (
    SimulatorBackend,
    SimulatorExecutionResult,
    SimulatorSessionBackend,
    SimulatorTransport,
)

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
    "MissionContextProjector",
    "ProjectionError",
    "PublicMissionContext",
    "PublicObjective",
    "PublicUnit",
    "SimulatorBackend",
    "SimulatorExecutionResult",
    "SimulatorSessionBackend",
    "SimulatorTransport",
    "SchemaValidationError",
    "StaleContextError",
    "ThreatSummary",
    "parse_incoming_message",
    "project_observation",
    "validate_action_arguments",
]
