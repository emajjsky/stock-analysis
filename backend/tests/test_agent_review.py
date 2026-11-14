"""Agent结构化输入/输出限额与引用协议。"""
import json

import pytest

from backend.agent_review import (
    MAX_AGENT_INPUT_BYTES,
    MAX_AGENT_OUTPUT_BYTES,
    AgentReviewError,
    input_size,
    parse_response,
)


def response(**updates):
    result = dict(verdict='SUPPORT', summary='复核摘要', supporting_evidence=['依据'],
        opposing_evidence=[], unknowns=[], conditions=[], limitations=[], cited_evidence_ids=['ev-1'])
    result.update(updates)
    return json.dumps(result, ensure_ascii=False)


def response_without_citations():
    result = json.loads(response())
    del result['cited_evidence_ids']
    return json.dumps(result, ensure_ascii=False)


def test_valid_response_is_trimmed_and_citations_are_whitelisted():
    parsed = parse_response(response(summary='  摘要  ', cited_evidence_ids=['ev-1']), {'ev-1'})
    assert parsed['summary'] == '摘要'
    assert parsed['cited_evidence_ids'] == ['ev-1']


@pytest.mark.parametrize('content,allowed,code', [
    (response(cited_evidence_ids=['other']), {'ev-1'}, 'INVALID_CITATION'),
    (response(cited_evidence_ids=['ev-1', 'ev-1']), {'ev-1'}, 'INVALID_CITATION'),
    (response(cited_evidence_ids=['ev-1']), set(), 'INVALID_CITATION'),
    (response_without_citations(), {'ev-1'}, 'INVALID_CITATION'),
    (response(summary=''), {'ev-1'}, 'INVALID_RESPONSE'),
    (response(unknowns=['x' * 501]), {'ev-1'}, 'INVALID_RESPONSE'),
    (response(conditions=[''] * 21), {'ev-1'}, 'INVALID_RESPONSE'),
    ('not json', set(), 'INVALID_RESPONSE'),
    pytest.param('x' * (MAX_AGENT_OUTPUT_BYTES + 1), set(), 'OUTPUT_TOO_LARGE', id='oversized-output'),
    ('[]', set(), 'INVALID_RESPONSE'),
    (response(verdict=[]), {'ev-1'}, 'INVALID_RESPONSE'),
    (response(verdict={}), {'ev-1'}, 'INVALID_RESPONSE'),
])
def test_invalid_response_shapes_fail_closed(content, allowed, code):
    with pytest.raises(AgentReviewError) as error:
        parse_response(content, allowed)
    assert error.value.code == code


def test_input_payload_has_a_byte_limit():
    assert input_size({'text': 'x'}) < MAX_AGENT_INPUT_BYTES
    assert input_size({'text': 'x' * MAX_AGENT_INPUT_BYTES}) > MAX_AGENT_INPUT_BYTES
    with pytest.raises(AgentReviewError, match='INVALID_INPUT'):
        input_size({'not_json': object()})
