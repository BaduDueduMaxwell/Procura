import sqlite3
from pathlib import Path
from typing import Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.config import Settings
from app.domain.models import IntakeLine
from app.intake.validators import match_catalogue, normalize_line, validate_lines


class IntakeGraphState(TypedDict, total=False):
    intake_id: str
    lines: list[dict[str, Any]]
    status: str
    graph_path: list[str]
    finding_count: int


def _catalogue_tool(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return catalogue suggestions without changing the buyer's medicine value."""
    return [match_catalogue(IntakeLine.model_validate(line)).model_dump(mode="json") for line in lines]


def _validation_tool(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the deterministic intake checklist for every procurement row."""
    typed = [IntakeLine.model_validate(line) for line in lines]
    return [line.model_dump(mode="json") for line in validate_lines(typed)]


catalogue_match_tool = StructuredTool.from_function(_catalogue_tool, name="match_repository_catalogue")
intake_validation_tool = StructuredTool.from_function(_validation_tool, name="validate_procurement_rows")


class CheckpointerFactory:
    def __init__(self, settings: Settings):
        self.context = None
        self.connection = None
        self.saver: Any
        if settings.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
            self.context = PostgresSaver.from_conn_string(url)
            self.saver = self.context.__enter__()
            self.saver.setup()
        else:
            path = Path(settings.langgraph_checkpoint_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, check_same_thread=False)
            self.saver = SqliteSaver(self.connection)

    def close(self) -> None:
        if self.context:
            self.context.__exit__(None, None, None)
        if self.connection:
            self.connection.close()


def _append(state: IntakeGraphState, name: str) -> list[str]:
    return [*state.get("graph_path", []), name]


def ingest_input(state: IntakeGraphState) -> IntakeGraphState:
    return {"graph_path": _append(state, "ingest_input")}


def normalize_products(state: IntakeGraphState) -> IntakeGraphState:
    lines = [normalize_line(IntakeLine.model_validate(line)).model_dump(mode="json") for line in state["lines"]]
    return {"lines": lines, "graph_path": _append(state, "normalize_products")}


def match_repository_catalogue(state: IntakeGraphState) -> IntakeGraphState:
    lines = catalogue_match_tool.invoke({"lines": state["lines"]})
    return {"lines": lines, "graph_path": _append(state, "match_catalogue")}


def validate_rows(state: IntakeGraphState) -> IntakeGraphState:
    lines = intake_validation_tool.invoke({"lines": state["lines"]})
    findings = sum(len(line.get("findings", [])) for line in lines)
    return {"lines": lines, "finding_count": findings, "graph_path": _append(state, "validate_rows")}


def classify_findings(state: IntakeGraphState) -> IntakeGraphState:
    statuses = {line["status"] for line in state["lines"]}
    if "critical_review_required" in statuses:
        status = "critical_review_required"
    elif "suggestion_available" in statuses:
        status = "suggestion_available"
    elif "needs_correction" in statuses:
        status = "needs_correction"
    else:
        status = "ready"
    return {"status": status, "graph_path": _append(state, "classify_findings")}


def route_findings(state: IntakeGraphState) -> str:
    if state["status"] == "ready":
        return "ready"
    if state["status"] == "critical_review_required":
        return "critical"
    return "buyer"


def buyer_correction_interrupt(state: IntakeGraphState) -> IntakeGraphState:
    correction = interrupt({
        "intake_id": state["intake_id"],
        "status": state["status"],
        "finding_count": state.get("finding_count", 0),
        "message": "Buyer correction is required before submission.",
    })
    return {"lines": correction["lines"], "graph_path": _append(state, "buyer_correction_resume")}


def ready_for_submission(state: IntakeGraphState) -> IntakeGraphState:
    return {"status": "ready", "graph_path": _append(state, "ready_for_submission")}


def critical_review(state: IntakeGraphState) -> IntakeGraphState:
    return {"status": "critical_review_required", "graph_path": _append(state, "critical_review_required")}


class IntakeWorkflow:
    def __init__(self, settings: Settings):
        self.checkpoints = CheckpointerFactory(settings)
        builder = StateGraph(IntakeGraphState)
        builder.add_node("ingest_input", ingest_input)
        builder.add_node("normalize_products", normalize_products)
        builder.add_node("match_catalogue", match_repository_catalogue)
        builder.add_node("validate_rows", validate_rows)
        builder.add_node("classify_findings", classify_findings)
        builder.add_node("buyer_correction", buyer_correction_interrupt)
        builder.add_node("ready_for_submission", ready_for_submission)
        builder.add_node("critical_review", critical_review)
        builder.add_edge(START, "ingest_input")
        builder.add_edge("ingest_input", "normalize_products")
        builder.add_edge("normalize_products", "match_catalogue")
        builder.add_edge("match_catalogue", "validate_rows")
        builder.add_edge("validate_rows", "classify_findings")
        builder.add_conditional_edges("classify_findings", route_findings, {
            "ready": "ready_for_submission", "critical": "critical_review", "buyer": "buyer_correction",
        })
        builder.add_edge("buyer_correction", "normalize_products")
        builder.add_edge("ready_for_submission", END)
        builder.add_edge("critical_review", END)
        # LangGraph's compiled generic cannot preserve our TypedDict through its
        # dynamically assembled topology, so contain that untyped boundary here.
        self.graph: Any = builder.compile(checkpointer=self.checkpoints.saver)

    @staticmethod
    def config(intake_id: str) -> RunnableConfig:
        return RunnableConfig(configurable={"thread_id": intake_id})

    def start(self, intake_id: str, lines: list[IntakeLine]) -> IntakeGraphState:
        initial: IntakeGraphState = {
            "intake_id": intake_id,
            "lines": [line.model_dump(mode="json") for line in lines],
            "status": "processing",
            "graph_path": [],
            "finding_count": 0,
        }
        self.graph.invoke(initial, self.config(intake_id))
        return cast(IntakeGraphState, dict(self.graph.get_state(self.config(intake_id)).values))

    def resume(self, intake_id: str, lines: list[IntakeLine]) -> IntakeGraphState:
        snapshot = self.graph.get_state(self.config(intake_id))
        if snapshot.next and "buyer_correction" in snapshot.next:
            command: Command[Any] = Command(resume={"lines": [line.model_dump(mode="json") for line in lines]})
            self.graph.invoke(command, self.config(intake_id))
        else:
            restarted: IntakeGraphState = {
                "intake_id": intake_id,
                "lines": [line.model_dump(mode="json") for line in lines],
                "status": "processing",
                "graph_path": list(snapshot.values.get("graph_path", [])),
            }
            self.graph.invoke(restarted, self.config(intake_id))
        return cast(IntakeGraphState, dict(self.graph.get_state(self.config(intake_id)).values))

    def close(self) -> None:
        self.checkpoints.close()
