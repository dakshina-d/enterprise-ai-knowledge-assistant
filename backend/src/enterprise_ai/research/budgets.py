"""Concurrency-safe server-owned research budget ledger."""

import asyncio

from enterprise_ai.research.models import ResearchBudget, ResearchBudgetUsage


class BudgetLedger:
    def __init__(self, budget: ResearchBudget) -> None:
        self.budget = budget
        self._usage = ResearchBudgetUsage()
        self._lock = asyncio.Lock()

    async def consume(self, resource: str, amount: int = 1) -> bool:
        limits = {
            "tasks": self.budget.maximum_total_tasks,
            "retrieval_calls": self.budget.maximum_retrieval_calls,
            "analysis_calls": self.budget.maximum_analysis_calls,
            "llm_calls": self.budget.maximum_llm_calls,
            "evidence_items": self.budget.maximum_evidence_items,
            "evidence_characters": self.budget.maximum_evidence_characters,
        }
        if resource not in limits or amount < 0:
            raise ValueError("unknown research budget resource")
        async with self._lock:
            current = int(getattr(self._usage, resource))
            if current + amount > limits[resource]:
                self._usage = self._usage.model_copy(update={"exhausted": True})
                return False
            self._usage = self._usage.model_copy(update={resource: current + amount})
            return True

    async def usage(self) -> ResearchBudgetUsage:
        async with self._lock:
            return self._usage.model_copy(deep=True)
