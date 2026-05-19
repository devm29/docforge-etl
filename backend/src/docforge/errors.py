from __future__ import annotations


class DocforgeError(Exception):
    code = "internal_error"
    status_code = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DocforgeError):
    code = "not_found"
    status_code = 404


class UnauthorizedError(DocforgeError):
    code = "unauthorized"
    status_code = 401


class ConflictError(DocforgeError):
    code = "conflict"
    status_code = 409


class InvalidRequestError(DocforgeError):
    code = "invalid_request"
    status_code = 422


class PipelineError(DocforgeError):
    """Raised from inside a stage. Subclasses decide whether a retry can help."""

    retryable = True


class TransientError(PipelineError):
    code = "transient_error"
    retryable = True


class PermanentError(PipelineError):
    code = "permanent_error"
    retryable = False


class UnsupportedFormatError(PermanentError):
    code = "unsupported_format"


class ParseError(PermanentError):
    code = "parse_error"


class SourceUnavailableError(TransientError):
    code = "source_unavailable"


class ProviderUnavailableError(TransientError):
    code = "provider_unavailable"


class ExtractionRefusedError(PermanentError):
    code = "extraction_refused"


class ExtractionProviderError(PermanentError):
    code = "extraction_provider_error"


def is_retryable(exc: BaseException) -> bool:
    """Pipeline errors decide for themselves; other domain errors are deterministic, so never retry
    them; anything else (database, network, Redis) is assumed to be transient."""
    if isinstance(exc, PipelineError):
        return exc.retryable
    return not isinstance(exc, DocforgeError)
