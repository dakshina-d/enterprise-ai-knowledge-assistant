"""Shared offline fixtures for authenticated chat API integration tests."""

from collections.abc import AsyncIterator, Callable
from typing import cast

from enterprise_ai.core.config import Settings
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.graph.schemas import GraphInput, GraphOutput, GraphStreamItem
from enterprise_ai.models.common import ProcessingStatus
from enterprise_ai.models.events import AgentEvent, AgentEventStatus, AgentEventType
from enterprise_ai.models.graph import Intent, PublicAgentStatus, Route
from enterprise_ai.security.password import PasswordService
from fastapi import FastAPI
from pydantic import SecretStr

SECRET = "chat-api-integration-secret-with-at-least-48-characters"
PASSWORD = "Analyst-Chat-Test-Password"


class FakeGraphRuntime:
    def __init__(self) -> None:
        self.inputs: list[GraphInput] = []
        self.stream_inputs: list[GraphInput] = []
        self.closed = 0
        self.failure: Exception | None = None

    def output(self, graph_input: GraphInput) -> GraphOutput:
        return GraphOutput(
            graph_version="1.2",
            request_id=graph_input.request_id,
            trace_id=graph_input.trace_id,
            session_id=graph_input.session_id,
            completion_status=ProcessingStatus.COMPLETED,
            selected_route=Route.DIRECT_RESPONSE,
            intent=Intent.CONVERSATIONAL,
            response_text="Safe fictional response.",
            agent_status=PublicAgentStatus(
                request_id=graph_input.request_id,
                status=ProcessingStatus.COMPLETED,
                node="finalize_execution",
                public_message="Graph execution completed.",
                route=Route.DIRECT_RESPONSE,
            ),
        )

    async def ainvoke(self, graph_input: GraphInput) -> GraphOutput:
        self.inputs.append(graph_input)
        if self.failure is not None:
            raise self.failure
        return self.output(graph_input)

    async def astream(self, graph_input: GraphInput) -> AsyncIterator[GraphStreamItem]:
        self.stream_inputs.append(graph_input)
        if self.failure is not None:
            raise self.failure
        yield GraphStreamItem(
            event=AgentEvent(
                event_type=AgentEventType.REQUEST_ACCEPTED,
                sequence_number=0,
                request_id=graph_input.request_id,
                session_id=graph_input.session_id,
                trace_id=graph_input.trace_id,
                status=AgentEventStatus.ACCEPTED,
                public_message="Request accepted.",
            )
        )
        yield GraphStreamItem(
            event=AgentEvent(
                event_type=AgentEventType.RESPONSE_COMPLETED,
                sequence_number=1,
                request_id=graph_input.request_id,
                session_id=graph_input.session_id,
                trace_id=graph_input.trace_id,
                status=AgentEventStatus.COMPLETED,
                public_message="Response completed.",
            )
        )
        yield GraphStreamItem(output=self.output(graph_input))

    async def aclose(self) -> None:
        self.closed += 1


def chat_settings(**overrides: object) -> Settings:
    password_hash = PasswordService().hash_password(PASSWORD)
    values: dict[str, object] = {
        "app_env": "test",
        "auth_enabled": True,
        "auth_token_secret": SECRET,
        "demo_viewer_password_hash": password_hash,
        "demo_analyst_password_hash": password_hash,
        "demo_admin_password_hash": password_hash,
        "rate_limit_enabled": False,
    }
    values.update(overrides)
    return Settings(
        **values,
    )


def runtime_factory(runtime: FakeGraphRuntime) -> Callable[[object], GraphRuntime]:
    def factory(_settings: object) -> GraphRuntime:
        return cast(GraphRuntime, runtime)

    return factory


def authorization_header(client: object, username: str = "demo-analyst") -> dict[str, str]:
    app = cast(FastAPI, client).app
    profile = app.state.authentication_service.authenticate(username, SecretStr(PASSWORD))
    token = app.state.token_service.issue_token(
        profile,
        app.state.authorization_service.permissions_for_role(profile.role),
    )
    return {"Authorization": f"Bearer {token}"}
