"""Exception types shared by the evaluation package."""


class EvaluationError(Exception):
    """Base class for all evaluation errors."""


class InputError(EvaluationError):
    """Raised when an input source cannot be read or parsed."""


class ValidationError(EvaluationError):
    """Raised when input records violate a documented contract."""


class IntegrityError(EvaluationError):
    """Raised when a frozen evidence snapshot was modified."""
