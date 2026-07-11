"""Sanitized restricted-analysis failures."""


class AnalysisError(RuntimeError):
    pass


class AnalysisAuthorizationError(AnalysisError):
    pass


class AnalysisValidationError(AnalysisError):
    pass


class AnalysisDatasetError(AnalysisError):
    pass


class AnalysisLimitError(AnalysisError):
    pass
