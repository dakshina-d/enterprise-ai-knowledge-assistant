"""Provider-independent dense retrieval services."""

from enterprise_ai.retrieval.dense_retriever import DenseEvidence, DenseRetrievalService
from enterprise_ai.retrieval.filters import DenseQueryFilters

__all__ = ["DenseEvidence", "DenseQueryFilters", "DenseRetrievalService"]
