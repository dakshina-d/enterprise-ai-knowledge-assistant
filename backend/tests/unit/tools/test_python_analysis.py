"""Security, authorization, taxonomy, and deterministic analysis tests."""

import ast
import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.tools.python_analysis.datasets import load_authorized_incidents
from enterprise_ai.tools.python_analysis.engine import execute_analysis
from enterprise_ai.tools.python_analysis.exceptions import (
    AnalysisAuthorizationError,
    AnalysisLimitError,
    AnalysisValidationError,
)
from enterprise_ai.tools.python_analysis.models import (
    AnalysisFilters,
    AnalysisOperation,
    AnalysisRequest,
)
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool, plan_analysis
from enterprise_ai.tools.python_analysis.taxonomy import ROOT_CAUSE_CATEGORIES, classify_root_cause


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("exhausted JDBC connection pool", "connection_pool_exhaustion"),
        ("message queue backlog", "message_queue_backlog"),
        ("certificate rotation failure", "certificate_lifecycle_failure"),
        ("retry storm amplified traffic", "retry_storm"),
        ("unclassified novel condition", "other"),
        (None, "unknown"),
    ],
)
def test_taxonomy_is_deterministic(text: str | None, category: str) -> None:
    assert classify_root_cause(text) == category
    assert category in ROOT_CAUSE_CATEGORIES


def test_planner_is_typed_and_deterministic() -> None:
    query = "Identify recurring root causes in payment incidents during the last year."
    first = plan_analysis(query)
    assert first == plan_analysis(query)
    assert first.operation is AnalysisOperation.RECURRING_ROOT_CAUSES
    assert first.filters.departments == ("payments",)
    with pytest.raises(AnalysisValidationError):
        plan_analysis("Run arbitrary code")


def test_viewer_denied_before_dataset_construction() -> None:
    tool = PythonAnalysisTool(RetrievalSettings())
    with pytest.raises(AnalysisAuthorizationError):
        tool.require_authorized(assessment_principal(UserRole.VIEWER))


@pytest.mark.asyncio
async def test_authorized_real_dataset_is_role_filtered_and_deterministic() -> None:
    analyst = assessment_principal(UserRole.ANALYST)
    administrator = assessment_principal(UserRole.ADMINISTRATOR)
    analyst_rows, analyst_excluded = load_authorized_incidents(analyst)
    administrator_rows, administrator_excluded = load_authorized_incidents(administrator)
    assert len(analyst_rows) == 12
    assert len(administrator_rows) == 16
    assert analyst_excluded == 4 and administrator_excluded == 0
    assert all(row.access_level.value != "restricted" for row in analyst_rows)
    request = AnalysisRequest(
        operation=AnalysisOperation.RECURRING_ROOT_CAUSES,
        filters=AnalysisFilters(departments=("payments",)),
    )
    first = execute_analysis(
        request,
        analyst_rows,
        request_id=uuid4(),
        trace_id=uuid4(),
        maximum_groups=100,
        maximum_distinct=500,
    )
    second = execute_analysis(
        request,
        analyst_rows,
        request_id=first.request_id,
        trace_id=first.trace_id,
        maximum_groups=100,
        maximum_distinct=500,
    )
    assert first == second
    assert first.items


@pytest.mark.asyncio
async def test_tool_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = PythonAnalysisTool(RetrievalSettings(python_analysis_timeout_seconds=10))

    async def blocked(*args: object, **kwargs: object) -> object:
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "to_thread", blocked)
    task = asyncio.create_task(
        tool.execute(
            assessment_principal(UserRole.ANALYST),
            AnalysisRequest(operation=AnalysisOperation.COUNT_RECORDS),
            request_id=uuid4(),
            trace_id=uuid4(),
        )
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_tool_timeout_and_filter_bounds_fail_without_a_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounded = PythonAnalysisTool(
        RetrievalSettings(
            python_analysis_timeout_seconds=0.01,
            python_analysis_max_filter_values=1,
        )
    )
    with pytest.raises(AnalysisLimitError):
        await bounded.execute(
            assessment_principal(UserRole.ANALYST),
            AnalysisRequest(
                operation=AnalysisOperation.COUNT_RECORDS,
                filters=AnalysisFilters(departments=("payments", "operations")),
            ),
            request_id=uuid4(),
            trace_id=uuid4(),
        )

    async def blocked(*args: object, **kwargs: object) -> object:
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "to_thread", blocked)
    with pytest.raises(TimeoutError):
        await bounded.execute(
            assessment_principal(UserRole.ANALYST),
            AnalysisRequest(operation=AnalysisOperation.COUNT_RECORDS),
            request_id=uuid4(),
            trace_id=uuid4(),
        )


def test_package_contains_no_arbitrary_execution_primitives() -> None:
    root = Path("backend/src/enterprise_ai/tools/python_analysis")
    prohibited = {"eval", "exec", "compile", "__import__"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not names.intersection(prohibited)
        assert not {"subprocess", "socket"}.intersection(imports)
