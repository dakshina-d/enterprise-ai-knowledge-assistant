"""Offline restricted-analysis CLI."""

import argparse
import asyncio
from datetime import date
from uuid import uuid4

from enterprise_ai.models.identity import UserRole
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.evaluation import assessment_principal
from enterprise_ai.tools.python_analysis.exceptions import AnalysisError
from enterprise_ai.tools.python_analysis.models import (
    AnalysisFilters,
    AnalysisOperation,
    AnalysisRequest,
)
from enterprise_ai.tools.python_analysis.service import PythonAnalysisTool


async def run() -> None:
    parser = argparse.ArgumentParser(description="Run one allowlisted structured Python analysis")
    parser.add_argument("command", choices=["analyze"])
    parser.add_argument("--role", choices=[role.value for role in UserRole], required=True)
    parser.add_argument(
        "--operation", choices=[item.value for item in AnalysisOperation], required=True
    )
    parser.add_argument("--department", action="append", default=[])
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    arguments = parser.parse_args()
    request = AnalysisRequest(
        operation=AnalysisOperation(arguments.operation),
        filters=AnalysisFilters(
            departments=tuple(arguments.department),
            start_date=arguments.start_date,
            end_date=arguments.end_date,
        ),
    )
    try:
        result = await PythonAnalysisTool(RetrievalSettings()).execute(
            assessment_principal(UserRole(arguments.role)),
            request,
            request_id=uuid4(),
            trace_id=uuid4(),
        )
    except AnalysisError:
        print(
            '{"status":"denied_or_failed",'
            '"message":"Analysis was not permitted or could not run safely."}'
        )
    else:
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(run())
