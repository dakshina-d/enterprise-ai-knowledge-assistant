"""Typed, safely printable dense-retrieval failures."""


class RetrievalError(Exception):
    """Base exception whose messages never contain provider payloads or secrets."""


class RetrievalConfigurationError(RetrievalError):
    pass


class RetrievalValidationError(RetrievalError):
    pass


class RetrievalAuthenticationError(RetrievalError):
    pass


class RetrievalAuthorizationError(RetrievalError):
    pass


class RetrievalTimeoutError(RetrievalError):
    pass


class RetrievalTransientError(RetrievalError):
    pass


class RetrievalDependencyError(RetrievalError):
    pass


class RetrievalDataIntegrityError(RetrievalError):
    pass
