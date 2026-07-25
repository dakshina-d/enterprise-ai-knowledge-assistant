"""Authorized service boundary and deterministic request planner."""

import asyncio
from datetime import date
from uuid import UUID

from enterprise_ai.models.identity import AuthenticatedPrincipal, ToolPermission
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.tools.python_analysis.datasets import load_authorized_incidents
from enterprise_ai.tools.python_analysis.engine import execute_analysis
from enterprise_ai.tools.python_analysis.exceptions import (
    AnalysisAuthorizationError,
    AnalysisLimitError,
    AnalysisValidationError,
)
from enterprise_ai.tools.python_analysis.intent import has_explicit_aggregate_intent
from enterprise_ai.tools.python_analysis.models import (
    AnalysisFilters,
    AnalysisOperation,
    AnalysisRequest,
    AnalysisResult,
)


def plan_analysis(query: str) -> AnalysisRequest:
    value = query.casefold()
    if not has_explicit_aggregate_intent(query):
        raise AnalysisValidationError("structured analysis requires explicit aggregate intent")
    filters = AnalysisFilters(
        departments=("payments",) if "payment" in value else (),
        start_date=date(2025, 7, 1) if "last year" in value else None,
        end_date=date(2026, 6, 30) if "last year" in value else None,
    )
    if "recurring" in value or "root cause" in value:
        operation = AnalysisOperation.RECURRING_ROOT_CAUSES
    elif "severity" in value:
        operation = AnalysisOperation.SEVERITY_DISTRIBUTION
    elif "per month" in value or "monthly" in value:
        operation = AnalysisOperation.DATE_HISTOGRAM
    elif "duration" in value:
        operation = AnalysisOperation.DURATION_STATISTICS
    elif "how many" in value or "count" in value:
        operation = AnalysisOperation.COUNT_RECORDS
    elif "status" in value:
        operation = AnalysisOperation.STATUS_DISTRIBUTION
    else:
        raise AnalysisValidationError("structured analysis operation is unsupported")
    return AnalysisRequest(operation=operation, filters=filters)


class PythonAnalysisTool:
    def __init__(self, settings: RetrievalSettings) -> None:
        self.settings = settings
        self.authorization = AuthorizationService()

    def require_authorized(self, principal: AuthenticatedPrincipal) -> None:
        if not self.settings.python_analysis_enabled or not self.authorization.has_permission(
            principal, ToolPermission.PYTHON_ANALYSIS
        ):
            raise AnalysisAuthorizationError("Python analysis is not permitted")

    async def execute(
        self,
        principal: AuthenticatedPrincipal,
        request: AnalysisRequest,
        *,
        request_id: UUID,
        trace_id: UUID,
    ) -> AnalysisResult:
        self.require_authorized(principal)
        if any(
            len(value) > self.settings.python_analysis_max_filter_values
            for value in (
                request.filters.document_ids,
                request.filters.departments,
                request.filters.statuses,
                request.filters.severities,
                request.filters.root_cause_categories,
            )
        ):
            raise AnalysisLimitError("analysis filter limit exceeded")
        async with asyncio.timeout(self.settings.python_analysis_timeout_seconds):
            rows, excluded = await asyncio.to_thread(load_authorized_incidents, principal)
            self.require_authorized(principal)
            if len(rows) > self.settings.python_analysis_max_rows:
                raise AnalysisLimitError("authorized analysis row limit exceeded")
            result = await asyncio.to_thread(
                execute_analysis,
                request,
                rows,
                request_id=request_id,
                trace_id=trace_id,
                maximum_groups=self.settings.python_analysis_max_groups,
                maximum_distinct=self.settings.python_analysis_max_distinct_values,
            )
        return result.model_copy(
            update={"row_count_excluded": result.row_count_excluded + excluded}
        )
