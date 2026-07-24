"""Attribution-safe weighted dense-sparse fusion."""

from typing import Any

from enterprise_ai.retrieval.dense_retriever import DenseEvidence
from enterprise_ai.retrieval.exceptions import RetrievalDataIntegrityError
from enterprise_ai.retrieval.hybrid.models import HybridEvidence
from enterprise_ai.retrieval.hybrid.normalization import normalize_scores
from enterprise_ai.retrieval.sparse.retriever import SparseEvidence

ATTRIBUTION_FIELDS = (
    "chunk_id",
    "evidence_id",
    "document_id",
    "title",
    "source_file",
    "section_path",
    "source_line_start",
    "source_line_end",
    "chunk_content_hash",
    "build_fingerprint",
    "access_level",
    "allowed_roles",
)


def fuse(
    dense: tuple[DenseEvidence, ...],
    sparse: tuple[SparseEvidence, ...],
    *,
    dense_weight: float,
    sparse_weight: float,
    top_k: int,
) -> tuple[HybridEvidence, ...]:
    total_weight = dense_weight + sparse_weight
    if total_weight <= 0:
        raise ValueError("hybrid weights are invalid")
    dense_weight, sparse_weight = dense_weight / total_weight, sparse_weight / total_weight
    dense_by_id = {str(item.chunk_id): item for item in dense}
    sparse_by_id = {str(item.chunk_id): item for item in sparse}
    normalized_dense = normalize_scores(
        {key: item.dense_score for key, item in dense_by_id.items()}
    )
    normalized_sparse = normalize_scores(
        {key: item.sparse_score for key, item in sparse_by_id.items()}
    )
    dense_ranks = {str(item.chunk_id): rank for rank, item in enumerate(dense, 1)}
    sparse_ranks = {str(item.chunk_id): rank for rank, item in enumerate(sparse, 1)}
    rows: list[HybridEvidence] = []
    for chunk_id in sorted(set(dense_by_id) | set(sparse_by_id)):
        dense_item, sparse_item = dense_by_id.get(chunk_id), sparse_by_id.get(chunk_id)
        if dense_item and sparse_item:
            if any(
                getattr(dense_item, field) != getattr(sparse_item, field)
                for field in ATTRIBUTION_FIELDS
            ):
                raise RetrievalDataIntegrityError("dense and sparse attribution disagree")
        evidence = dense_item or _as_dense(sparse_item)
        if evidence is None:
            continue
        dense_normalized = normalized_dense.get(chunk_id, 0.0)
        sparse_normalized = normalized_sparse.get(chunk_id, 0.0)
        rows.append(
            HybridEvidence(
                evidence=evidence,
                raw_dense_score=dense_item.dense_score if dense_item else None,
                raw_sparse_score=sparse_item.sparse_score if sparse_item else None,
                normalized_dense_score=dense_normalized,
                normalized_sparse_score=sparse_normalized,
                hybrid_score=dense_normalized * dense_weight + sparse_normalized * sparse_weight,
                dense_rank=dense_ranks.get(chunk_id),
                sparse_rank=sparse_ranks.get(chunk_id),
                final_rank=1,
                retrieval_modes=frozenset(
                    mode
                    for mode, present in (("dense", dense_item), ("sparse", sparse_item))
                    if present
                ),
            )
        )
    rows.sort(
        key=lambda item: (
            -item.hybrid_score,
            -item.normalized_dense_score,
            -item.normalized_sparse_score,
            -(item.raw_dense_score if item.raw_dense_score is not None else float("-inf")),
            -(item.raw_sparse_score if item.raw_sparse_score is not None else float("-inf")),
            str(item.evidence.chunk_id),
        )
    )
    return tuple(
        item.model_copy(update={"final_rank": rank}) for rank, item in enumerate(rows[:top_k], 1)
    )


def _as_dense(item: SparseEvidence | None) -> DenseEvidence | None:
    if item is None:
        return None
    values: dict[str, Any] = item.model_dump()
    values.pop("sparse_score")
    values.pop("sparse_build_fingerprint")
    values.pop("salient_query_terms")
    values.pop("matched_query_terms")
    values.pop("salient_term_coverage")
    values["record_id"] = str(item.chunk_id)
    values["dense_score"] = 0.0
    return DenseEvidence.model_validate(values)
