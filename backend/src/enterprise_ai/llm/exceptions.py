"""Sanitized LLM and grounding failures."""


class LLMError(RuntimeError):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMProviderError(LLMError):
    pass


class LLMRefusalError(LLMError):
    pass


class CitationValidationError(LLMError):
    pass
