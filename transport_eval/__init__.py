"""Green-mobility measure evaluation for staged corridor pilots.

The package is deliberately standard-library only.  It separates the frozen
evidence a decision was based on from later operational input, and it reports
observed change, comparison-supported change, and unexplained residual as three
distinct quantities.
"""

from .errors import EvaluationError, InputError, IntegrityError, ValidationError
from .estimation import Evaluation, Effect, Limitation, evaluate
from .loading import input_digests, load_workspace
from .model import StudyInputs
from .reporting import render_report
from .workspace import EvidenceSnapshot, StudyWorkspace, ledger_summary

__all__ = [
    "Effect",
    "Evaluation",
    "EvaluationError",
    "EvidenceSnapshot",
    "InputError",
    "IntegrityError",
    "Limitation",
    "StudyInputs",
    "StudyWorkspace",
    "ValidationError",
    "evaluate",
    "input_digests",
    "ledger_summary",
    "load_workspace",
    "render_report",
]

__version__ = "0.1.0"
