import re
from typing import Any

import sentry_sdk
from langfuse import Langfuse


def sanitize(value: Any) -> Any:
    text = str(value)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(api[_-]?key|secret)[=: ]+[A-Za-z0-9._-]+", r"\1=[REDACTED]", text)
    text = re.sub(r"\+?\d[\d\s()-]{7,}\d", "[REDACTED_PHONE]", text)
    return text[:1000]


class Observability:
    def __init__(self, settings):
        self.langfuse_enabled = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
        self.sentry_enabled = bool(settings.sentry_dsn)
        self.langfuse = (
            Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                base_url=settings.langfuse_host,
                environment=settings.app_env,
            )
            if self.langfuse_enabled
            else None
        )
        if self.sentry_enabled:
            sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env, traces_sample_rate=0.2, send_default_pii=False)

    def capture(self, exc: Exception, **tags: str) -> None:
        if self.sentry_enabled:
            with sentry_sdk.push_scope() as scope:
                for key, value in tags.items(): scope.set_tag(key, sanitize(value))
                sentry_sdk.capture_exception(exc)

    def export_execution(self, *, trace_id: str, conversation_id: str, model: str, provider: str, token_input: int | None, token_output: int | None, tool_sequence: list[str], decision: str, review_required: bool, scores: dict[str, float]) -> bool:
        """Export bounded metadata only. Raw user and supplier text is excluded."""
        if not self.langfuse:
            return False
        try:
            with self.langfuse.start_as_current_observation(
                trace_context={"trace_id": trace_id.replace("-", "")},
                name="procura-agent",
                as_type="agent",
                input={"conversation_id": conversation_id, "synthetic": True},
                output={"decision": decision, "review_required": review_required},
                metadata={"local_trace_id": trace_id, "policy_version": "procura-policy-v1", "prompt_version": "procura-agent-v1", "model": model, "provider": provider, "token_input": token_input, "token_output": token_output},
                version="procura-policy-v1",
            ):
                for tool_name in tool_sequence:
                    with self.langfuse.start_as_current_observation(name=tool_name, as_type="tool", input={"synthetic": True}, output={"completed": True}, metadata={"local_trace_id": trace_id}):
                        pass
                for score_name, score_value in scores.items():
                    self.langfuse.score_current_trace(name=score_name, value=score_value)
            return True
        except Exception as exc:  # noqa: BLE001 - telemetry cannot break the workflow
            self.capture(exc, trace_id=trace_id, workflow_stage="langfuse_export", error_category="observability")
            return False
