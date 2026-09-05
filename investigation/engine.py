import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from correlation.models import Incident
from investigation.client import (
    ChatMessage,
    LLMProvider,
    MessageRole,
)
from investigation.db import InvestigationDatabaseManager
from investigation.fallback import DeterministicFallbackEngine
from investigation.models import (
    EvidenceItem,
    EvidenceType,
    InvestigationReport,
    InvestigationStatus,
    InvestigationStep,
    ToolName,
)
from investigation.tools import InvestigationToolbox

logger = logging.getLogger("uvicorn.error")


SYSTEM_PROMPT = """You are LogMind SRE Investigator, an automated site reliability agent.
Your objective is to diagnose the root cause of an ongoing distributed systems incident.

GUIDELINES:
1. Form hypotheses and verify them using the provided tools.
2. Search relevant logs and examine distributed traces to confirm causal ordering.
3. Every finding in your final diagnosis MUST be supported by concrete evidence IDs (log IDs, trace IDs, or runbook IDs). Do not speculate without evidence.
4. When your investigation is complete, return your final diagnosis as a JSON object with the following schema:
{
  "summary": "Concise summary of the incident",
  "suspected_root_cause": "Detailed explanation of what failed first and why",
  "confidence_score": 0.95,
  "recommended_actions": ["Action 1", "Action 2"],
  "evidence": [
    {
      "evidence_type": "LOG",
      "reference_id": "exact_log_or_trace_or_runbook_id",
      "service": "affected_service_name",
      "excerpt": "relevant error message or trace excerpt"
    }
  ]
}
"""


class InvestigationEngine:
    def __init__(
        self,
        llm_client: LLMProvider,
        fallback_engine: DeterministicFallbackEngine,
        db_manager: InvestigationDatabaseManager | None = None,
        es_service: Any | None = None,
        corr_db_manager: Any | None = None,
        runbook_service: Any | None = None,
    ):
        self.llm = llm_client
        self.fallback = fallback_engine
        self.db = db_manager
        self.es = es_service
        self.corr_db = corr_db_manager
        self.runbooks = runbook_service
    def _build_initial_messages(self, incident: Incident) -> list[ChatMessage]:
        timeline_str = "\n".join(
            f"- [{e.timestamp.isoformat()}] {e.service}: {e.event_type.value} - {e.message}"
            for e in incident.events
        )
        context_prompt = f"""INCIDENT TO INVESTIGATE:
ID: {incident.incident_id}
Title: {incident.title}
Trigger Service: {incident.trigger_service}
Trigger Signature: {incident.trigger_signature or 'N/A'}
Affected Services: {', '.join(incident.affected_services)}
Started At: {incident.started_at.isoformat()}

CORRELATED TIMELINE EVENTS:
{timeline_str or 'None recorded'}

Investigate the incident now. Use available tools to identify the root cause and confirm evidence."""

        return [
            ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.USER, content=context_prompt),
        ]

    async def run_investigation_loop(
        self,
        incident: Incident,
        toolbox: InvestigationToolbox,
        max_steps: int = 5,
    ) -> InvestigationReport:
        started_at = datetime.now(UTC)
        messages = self._build_initial_messages(incident)
        tool_defs = toolbox.get_tool_definitions()
        steps: list[InvestigationStep] = []

        try:
            for _ in range(1, max_steps + 1):
                resp = await self.llm.chat_completion(messages, tools=tool_defs)

                if resp.tool_calls:
                    # Assistant message containing tool calls
                    messages.append(
                        ChatMessage(
                            role=MessageRole.ASSISTANT,
                            content=resp.content,
                            tool_calls=resp.tool_calls,
                        )
                    )

                    for call in resp.tool_calls:
                        t0 = time.perf_counter()
                        output = await toolbox.execute_tool_by_name(
                            name=call.function.name,
                            arguments_json=call.function.arguments,
                        )
                        duration_ms = int((time.perf_counter() - t0) * 1000)

                        try:
                            t_name = ToolName(call.function.name)
                        except ValueError:
                            t_name = ToolName.SEARCH_LOGS

                        try:
                            parsed_input = json.loads(call.function.arguments) if call.function.arguments else {}
                        except (json.JSONDecodeError, TypeError):
                            parsed_input = {}

                        steps.append(
                            InvestigationStep(
                                step_number=len(steps) + 1,
                                tool_name=t_name,
                                tool_input=parsed_input if isinstance(parsed_input, dict) else {},
                                tool_output=output,
                                duration_ms=duration_ms,
                            )
                        )

                        # Append tool response
                        messages.append(
                            ChatMessage(
                                role=MessageRole.TOOL,
                                name=call.function.name,
                                tool_call_id=call.id,
                                content=json.dumps(output),
                            )
                        )
                else:
                    # Final response received
                    completed_at = datetime.now(UTC)
                    report = self._parse_final_content(
                        incident=incident,
                        content=resp.content or "",
                        steps=steps,
                        started_at=started_at,
                        completed_at=completed_at,
                    )
                    if self.db:
                        await self.db.save_report(report)
                    return report

            # If budget exhausted, force final diagnosis with tools disabled
            messages.append(
                ChatMessage(
                    role=MessageRole.USER,
                    content="Tool budget exhausted. Provide your final root cause diagnosis and evidence citations in the required JSON format now.",
                )
            )
            final_resp = await self.llm.chat_completion(messages, tools=None)
            completed_at = datetime.now(UTC)
            report = self._parse_final_content(
                incident=incident,
                content=final_resp.content or "",
                steps=steps,
                started_at=started_at,
                completed_at=completed_at,
            )
            if self.db:
                await self.db.save_report(report)
            return report

        except Exception as exc:  # noqa: BLE001
            logger.warning("Investigation error for incident %s: %s (falling back)", incident.incident_id, exc)
            fallback_report = self.fallback.generate_report(incident, error_reason=str(exc))
            fallback_report.steps = steps
            if self.db:
                await self.db.save_report(fallback_report)
            return fallback_report

    def _parse_final_content(
        self,
        incident: Incident,
        content: str,
        steps: list[InvestigationStep],
        started_at: datetime,
        completed_at: datetime,
    ) -> InvestigationReport:
        try:
            # Extract JSON block if wrapped in markdown
            text = content.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed: Any = json.loads(text)
            if not isinstance(parsed, dict):
                raise TypeError("Expected JSON object")

            summary = str(parsed.get("summary", f"Investigation for {incident.title}"))
            root_cause = str(parsed.get("suspected_root_cause", "Root cause identified."))
            confidence = float(parsed.get("confidence_score", 0.85))
            actions = [str(a) for a in parsed.get("recommended_actions", [])]

            evidence_items: list[EvidenceItem] = []
            for ev in parsed.get("evidence", []):
                if isinstance(ev, dict):
                    try:
                        ev_type = EvidenceType(str(ev.get("evidence_type", "LOG")))
                    except ValueError:
                        ev_type = EvidenceType.LOG
                    evidence_items.append(
                        EvidenceItem(
                            evidence_type=ev_type,
                            reference_id=str(ev.get("reference_id", "ref-unknown")),
                            service=str(ev.get("service")) if ev.get("service") else None,
                            excerpt=str(ev.get("excerpt", "")),
                        )
                    )

            return InvestigationReport(
                incident_id=incident.incident_id,
                status=InvestigationStatus.COMPLETED,
                summary=summary,
                suspected_root_cause=root_cause,
                confidence_score=confidence,
                affected_services=incident.affected_services,
                evidence=evidence_items,
                recommended_actions=actions,
                steps=steps,
                started_at=started_at,
                completed_at=completed_at,
                is_fallback=False,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            # If parsing JSON fails, construct a completed report using raw text
            return InvestigationReport(
                incident_id=incident.incident_id,
                status=InvestigationStatus.COMPLETED,
                summary=f"Investigation for {incident.title}",
                suspected_root_cause=content[:300] or "Diagnosis completed by LLM.",
                confidence_score=0.80,
                affected_services=incident.affected_services,
                evidence=[],
                recommended_actions=["Review raw investigation output"],
                steps=steps,
                started_at=started_at,
                completed_at=completed_at,
                is_fallback=False,
            )

    async def investigate_incident(
        self, incident: Incident, toolbox: InvestigationToolbox | None = None
    ) -> InvestigationReport:
        if toolbox is None:
            toolbox = InvestigationToolbox(
                es_service=self.es,
                db_manager=self.corr_db,
                tenant_id=incident.tenant_id,
                runbook_service=self.runbooks,
            )
        return await self.run_investigation_loop(incident, toolbox=toolbox)
