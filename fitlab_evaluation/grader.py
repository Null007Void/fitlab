"""Strict task oracle: model-authored scores and explanations confer no credit."""
import hashlib
import json
import math
from pathlib import Path

MAX_RESPONSE_BYTES = 65536


def strict_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate key')
            out[key] = value
        return out
    def reject(value):
        raise ValueError('nonstandard number')
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite number')
        return result
    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject, parse_float=finite_float)


def exact_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(exact_equal(actual[k], v) for k, v in expected.items())
    if type(expected) is list:
        return len(actual) == len(expected) and all(exact_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def load_pack(path):
    path = Path(path)
    payload = path.read_bytes()
    expected_hash = path.with_suffix('.sha256').read_text().split()[0]
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValueError('task pack hash mismatch')
    pack = strict_json(payload.decode('utf-8'))
    if pack['schema_version'] not in {'fitlab-tasks-v1','fitlab-tasks-v2'} or len(pack['cases']) != 8:
        raise ValueError('unsupported task pack')
    if len({c['id'] for c in pack['cases']}) != len(pack['cases']):
        raise ValueError('duplicate task identity')
    return pack, expected_hash


def optional_fields_error(tool_calls, function_call, refusal):
    if tool_calls is not None and type(tool_calls) is not list:
        return 'malformed_tool_calls'
    if function_call is not None and (type(function_call) is not dict or not function_call):
        return 'malformed_function_call'
    if refusal is not None and type(refusal) is not str:
        return 'malformed_refusal'
    return None


def grade(case, content, *, tool_calls=None, function_call=None, finish_reason='stop', refusal=None):
    def result(passed, reason):
        return {'case_id': case['id'], 'passed': passed, 'reason': reason}
    field_error = optional_fields_error(tool_calls, function_call, refusal)
    if field_error:
        return result(False, field_error)
    if tool_calls or function_call is not None:
        return result(False, 'unexpected_tool_call')
    if refusal:
        return result(False, 'unexpected_refusal_field')
    if finish_reason != 'stop':
        return result(False, 'incomplete_or_unsupported_finish')
    if type(content) is not str:
        return result(False, 'content_not_text')
    try:
        if len(content.encode('utf-8')) > MAX_RESPONSE_BYTES:
            return result(False, 'output_too_large')
        if type(case['expected']) is str:
            passed = content.strip() == case['expected']
        else:
            passed = exact_equal(strict_json(content), case['expected'])
    except (ValueError, RecursionError, UnicodeError):
        return result(False, 'invalid_json_or_unicode')
    return result(passed, 'exact_match' if passed else 'value_or_type_mismatch')
