"""受限Agent复核协议解析；不负责网络、账户或交易。"""
from __future__ import annotations

import json
from typing import Any


MAX_AGENT_INPUT_BYTES = 64 * 1024
MAX_AGENT_OUTPUT_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 1200
MAX_LIST_ITEMS = 20
MAX_LIST_TEXT_LENGTH = 500
MAX_CITATIONS = 20
MAX_CITATION_LENGTH = 160
VERDICTS = {"SUPPORT", "CONDITIONAL", "WAIT", "REJECT"}
LIST_FIELDS = ("supporting_evidence", "opposing_evidence", "unknowns", "conditions", "limitations")


class AgentReviewError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def input_size(payload: dict[str, Any]) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AgentReviewError("INVALID_INPUT") from exc


def parse_response(content: Any, allowed_citation_ids: set[str]) -> dict[str, Any]:
    if not isinstance(content, str):
        raise AgentReviewError("INVALID_RESPONSE")
    if len(content.encode("utf-8", errors="replace")) > MAX_AGENT_OUTPUT_BYTES:
        raise AgentReviewError("OUTPUT_TOO_LARGE")
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise AgentReviewError("INVALID_RESPONSE") from exc
    if not isinstance(result, dict):
        raise AgentReviewError("INVALID_RESPONSE")
    verdict = result.get("verdict")
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        raise AgentReviewError("INVALID_RESPONSE")
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_TEXT_LENGTH:
        raise AgentReviewError("INVALID_RESPONSE")
    parsed = {"verdict": verdict, "summary": summary.strip()}
    for field in LIST_FIELDS:
        items = result.get(field)
        if not isinstance(items, list) or len(items) > MAX_LIST_ITEMS:
            raise AgentReviewError("INVALID_RESPONSE")
        clean = []
        for item in items:
            if not isinstance(item, str) or len(item) > MAX_LIST_TEXT_LENGTH:
                raise AgentReviewError("INVALID_RESPONSE")
            value = item.strip()
            if not value:
                raise AgentReviewError("INVALID_RESPONSE")
            clean.append(value)
        parsed[field] = clean
    citations = result.get("cited_evidence_ids", [] if not allowed_citation_ids else None)
    if not isinstance(citations, list) or len(citations) > MAX_CITATIONS:
        raise AgentReviewError("INVALID_CITATION")
    if any(not isinstance(item, str) or len(item) > MAX_CITATION_LENGTH for item in citations):
        raise AgentReviewError("INVALID_CITATION")
    if len(set(citations)) != len(citations) or any(item not in allowed_citation_ids for item in citations):
        raise AgentReviewError("INVALID_CITATION")
    parsed["cited_evidence_ids"] = citations
    return parsed
