"""A real LangGraph tool loop with explicit fixture and Responses API providers.

Domain records persist each observable step. A process interruption marks the
run interrupted on startup; a new run can reuse the case, not an opaque model
continuation. Approvals and operation receipts remain durable independently.
"""

import json
import time
from typing import Any, TypedDict

from langgraph.graph import StateGraph, START, END

from .knowledge import search
from .models import Diagnosis
from .provider import OpenAIProvider, ProviderError

MAX_TOOLS = 20
MAX_MODELS = 10
MAX_SECONDS = 180


class WorkflowStopped(RuntimeError):
    pass


class ToolDenied(RuntimeError):
    pass


class State(TypedDict):
    messages: list[dict]
    calls: list[dict]
    diagnosis: dict | None
    turn: int


class ToolGateway:
    def __init__(self, domain, run_id):
        self.domain = domain
        self.run_id = run_id
        self.case_id = domain.get_run(run_id)["case_id"]
        self.seen: set[str] = set()
        self.reads: set[str] = set()
        self.results: dict[str, Any] = {}

    def call(self, name: str, arguments: dict) -> dict:
        if name not in {"read_export_evidence", "lookup_receipt", "search_runbooks", "read_connector_source", "finish_investigation"}:
            raise ToolDenied("The requested tool is not available to the investigator.")
        if name == "finish_investigation":
            diagnosis = Diagnosis.model_validate(arguments).model_dump()
            if not {"read_export_evidence", "lookup_receipt"} <= self.reads:
                raise ToolDenied("Read export evidence and the original receipt before finishing.")
            if not set(diagnosis["evidence_ids"]) <= self.seen:
                raise ToolDenied("The diagnosis cites evidence that this run did not read.")
            if any(len(value) > 600 for value in diagnosis["hypotheses"]):
                raise ToolDenied("A hypothesis exceeded its permitted size.")
            return diagnosis
        if name == "search_runbooks":
            if set(arguments) != {"query"} or not isinstance(arguments["query"], str) or not 1 <= len(arguments["query"]) <= 300:
                raise ToolDenied("Runbook search requires one bounded query.")
            result = {"articles": search(arguments["query"])}
        else:
            if arguments:
                raise ToolDenied("This tool is scoped by the server and accepts no target arguments.")
            case = self.domain.get_case(self.case_id)
            if name == "read_export_evidence":
                target = {key: case["target"][key] for key in ("system", "fictional", "transport", "order_id", "job_id", "revision", "job_revision", "order_status", "job_status", "error_code", "available", "authorized", "supplier_blocked", "payload_hash", "idempotency_key", "local_receipt")}
                observation = self.domain.add_evidence(self.case_id, "snapshot", "Current scoped export observation", json.dumps(target, sort_keys=True), "simulator://application/current-export")
                evidence = [item for item in case["evidence"] if item["kind"] != "receipt"][-8:] + [observation]
                self.seen.update(item["id"] for item in evidence)
                result = {"target": target, "evidence": evidence, "environment": "embedded fictional simulator; no network ERP call"}
            elif name == "lookup_receipt":
                target = case["target"]
                receipt = {"exists": target["receipt_present"], "reference": target["external_receipt"], "payload_hash": target["payload_hash"],
                           "order_id": case["order_id"], "job_id": case["job_id"], "idempotency_key": target["idempotency_key"]}
                observation = self.domain.add_evidence(self.case_id, "receipt", "ERP receipt lookup", json.dumps(receipt, sort_keys=True), "simulator://erp/receipt-lookup")
                self.seen.add(observation["id"])
                result = {"receipt": receipt, "evidence": [observation]}
            else:
                from .repair import source_context
                context = source_context()
                observation = self.domain.add_evidence(self.case_id, "source", "Bounded transform contract", json.dumps(context, sort_keys=True), "fixture://decimal_mapping.expr")
                self.seen.add(observation["id"])
                result = {"source": context, "evidence": [observation]}
        self.reads.add(name)
        self.results[name] = result
        return result


def fixture_diagnosis(gateway: ToolGateway) -> dict:
    """A transparent deterministic runbook baseline, never labelled model reasoning."""
    export = gateway.results["read_export_evidence"]
    lookup = gateway.results["lookup_receipt"]
    target = export["target"]
    code = target["error_code"]
    evidence = [export["evidence"][-1]["id"], lookup["evidence"][0]["id"]]
    if lookup["receipt"]["exists"] and target["local_receipt"] == lookup["receipt"]["reference"]:
        cause, action = "no_active_failure", "none"
        summary = "The application and fictional ERP agree on the original export receipt. No recovery is needed."
        recommendation = "Keep the existing receipt and close the case after verification."
    elif lookup["receipt"]["exists"]:
        cause, action = "lost_acknowledgement", "reconcile_receipt"
        summary = "The fictional ERP already holds a receipt for the exact original request, but the application has not recorded it."
        recommendation = "Review reconciliation of this existing receipt. Do not create another ERP order."
    elif not target["authorized"]:
        cause, action = "connector_authorization_denied", "escalate"
        summary = "The observed connector identity is not authorized to export. A retry cannot grant permission."
        recommendation = "Ask an authorized administrator to inspect the integration identity. Leave the order unchanged."
    elif target["supplier_blocked"]:
        cause, action = "business_rule_rejection", "escalate"
        summary = "The supplier is blocked by the fictional business policy. Repeating the same request does not satisfy that policy."
        recommendation = "Request business review; retain the original immutable request."
    elif code == "MAPPING_ERROR":
        cause, action = "decimal_mapping_defect", "prepare_patch"
        summary = "The observed decimal amount differs from the connector's cent-precision contract. A bounded transform reproduction is appropriate."
        recommendation = "Prepare a restricted expression patch and run protected verification. Exporting it will not change the queued payload."
    elif code == "TRANSIENT_503" and target["available"]:
        cause, action = "transient_transport_failure", "retry_export"
        summary = "The temporary gateway outage has ended and no receipt exists for the original export."
        recommendation = "Review a targeted retry using the unchanged payload and original idempotency key; verify a single receipt."
    else:
        cause, action = "insufficient_evidence", "escalate"
        summary = "Available evidence cannot establish a safe recovery or reliable root cause."
        recommendation = "Collect missing integration telemetry and reconcile acceptance before changing business state."
    return {"summary": summary, "cause": cause, "evidence_ids": evidence,
            "hypotheses": ["The root cause remains unconfirmed until additional telemetry is available."] if cause == "insufficient_evidence" else [],
            "recommendation": recommendation, "action": action}


def investigate(domain, run_id: str, *, provider=None, clock=time.monotonic, max_tools=MAX_TOOLS, max_models=MAX_MODELS, max_seconds=MAX_SECONDS):
    run = domain.get_run(run_id)
    gateway = ToolGateway(domain, run_id)
    live = run["mode"] == "openai"
    owned_provider = None
    started = clock()
    tool_calls = 0
    model_calls = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def check():
        if domain.run_cancelled(run_id):
            raise WorkflowStopped("Cancelled by the operator.")
        if clock() - started > max_seconds:
            raise WorkflowStopped("Investigation time budget exhausted.")

    def agent_node(state: State):
        nonlocal model_calls
        check()
        if live:
            if model_calls >= max_models:
                raise WorkflowStopped("Model-call budget exhausted.")
            model_calls += 1
            domain.update_run(run_id, model_calls=model_calls)
            result = provider.next(state["messages"])
            for key in usage:
                count = result.get("usage", {}).get(key, 0)
                if type(count) is int and count >= 0:
                    usage[key] += count
            domain.update_run(run_id, usage=usage)
            return {"messages": state["messages"] + result["output"], "calls": result["calls"], "turn": state["turn"] + 1}
        turn = state["turn"]
        if turn == 0:
            name, args = "read_export_evidence", {}
        elif turn == 1:
            name, args = "lookup_receipt", {}
        elif turn == 2:
            name, args = "search_runbooks", {"query": "export " + gateway.results["read_export_evidence"]["target"]["error_code"]}
        elif turn == 3 and gateway.results["read_export_evidence"]["target"]["error_code"] == "MAPPING_ERROR":
            name, args = "read_connector_source", {}
        else:
            name, args = "finish_investigation", fixture_diagnosis(gateway)
        call = {"type": "function_call", "call_id": f"fixture-{turn}", "name": name, "arguments": json.dumps(args)}
        return {"calls": [call], "turn": turn + 1}

    def tool_node(state: State):
        nonlocal tool_calls
        messages = list(state["messages"])
        diagnosis = None
        for call in state["calls"]:
            check()
            if diagnosis is not None:
                raise ToolDenied("No tool calls may follow the final diagnosis in a response.")
            if tool_calls >= max_tools:
                raise WorkflowStopped("Tool-call budget exhausted.")
            tool_calls += 1
            domain.update_run(run_id, tool_calls=tool_calls)
            name = call["name"]
            args = json.loads(call["arguments"])
            result = gateway.call(name, args)
            title = {"read_export_evidence": "Read scoped export evidence", "lookup_receipt": "Look up original ERP receipt",
                     "search_runbooks": "Search versioned runbooks", "read_connector_source": "Inspect transform contract",
                     "finish_investigation": "Submit evidence-backed diagnosis"}[name]
            domain.add_run_event(run_id, "tool", title, json.dumps({"tool": name, "arguments": args, "result": result}, ensure_ascii=False)[:8000])
            if name == "finish_investigation":
                diagnosis = result
            messages.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result, ensure_ascii=False)[:16000]})
        return {"messages": messages, "diagnosis": diagnosis}

    def finish_node(state: State):
        check()
        domain.record_diagnosis(run["case_id"], run_id, state["diagnosis"])
        domain.update_run(run_id, status="completed")
        return {}

    try:
        check()
        domain.update_run(run_id, status="running")
        domain.add_run_event(run_id, "started", "Investigation started", "OpenAI model-backed tool loop" if live else "Deterministic fixture policy; no AI inference or model spending")
        if live and provider is None:
            owned_provider = OpenAIProvider()
            provider = owned_provider
        graph = StateGraph(State)
        graph.add_node("investigator", agent_node)
        graph.add_node("tools", tool_node)
        graph.add_node("record", finish_node)
        graph.add_edge(START, "investigator")
        graph.add_edge("investigator", "tools")
        graph.add_conditional_edges("tools", lambda state: "record" if state.get("diagnosis") else "investigator", ["record", "investigator"])
        graph.add_edge("record", END)
        graph.compile().invoke({"messages": [{"role": "user", "content": "Investigate the selected fictional integration case. Read the available evidence and propose a supported next action."}], "calls": [], "diagnosis": None, "turn": 0}, {"recursion_limit": 50})
    except Exception as exc:
        cancelled = domain.run_cancelled(run_id)
        # Never persist arbitrary provider exception text: it may contain request credentials.
        message = str(exc) if isinstance(exc, (WorkflowStopped, ToolDenied, ProviderError)) else "Investigation failed validation or encountered an internal error. No action was authorized."
        domain.add_run_event(run_id, "cancelled" if cancelled else "error", "Investigation cancelled" if cancelled else "Investigation stopped", message)
        current = domain.get_run(run_id)
        if current["status"] in {"queued", "running", "cancel_requested"}:
            domain.update_run(run_id, status="cancelled" if cancelled else "failed", error=message)
    finally:
        if owned_provider:
            owned_provider.close()
    return domain.get_run(run_id)
