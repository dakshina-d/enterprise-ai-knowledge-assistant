"""Sanitized LLM and grounding failures."""


class LLMError(RuntimeError):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


class LLMHTTPStatusError(LLMProviderError):
    def __init__(self, status_code: int, category: str = "request_rejected") -> None:
        self.status_code = status_code
        self.category = category
        super().__init__("Ollama request returned a non-success status")


class LLMDependencyUnavailableError(LLMProviderError):
    pass


class LLMTimeoutError(LLMProviderError):
    pass


class LLMInvalidResponseError(LLMProviderError):
    def __init__(self, message: str, category: str = "invalid_response") -> None:
        self.category = category
        super().__init__(message)


class LLMRefusalError(LLMError):
    pass


class CitationValidationError(LLMError):
    pass
