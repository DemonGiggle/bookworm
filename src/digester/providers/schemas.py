from __future__ import annotations

from copy import deepcopy
from typing import Dict

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "slug": {"type": "string"},
        "title": {"type": "string"},
        "routing_description": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "workflow_notes": {"type": "array", "items": {"type": "string"}},
        "reference_chunk_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "slug",
        "title",
        "routing_description",
        "summary",
        "key_points",
        "workflow_notes",
        "reference_chunk_ids",
    ],
    "additionalProperties": False,
}

DIGEST_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "topic_updates": {"type": "array", "items": TOPIC_SCHEMA},
        "should_continue": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": ["topic_updates", "should_continue", "rationale"],
    "additionalProperties": False,
}

FINALIZE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {"type": "array", "items": TOPIC_SCHEMA, "minItems": 1},
    },
    "required": ["topics"],
    "additionalProperties": False,
}


def schema_with_allowed_chunk_ids(
    schema: Dict[str, object],
    response_field: str,
    chunk_ids: object,
) -> Dict[str, object]:
    resolved_schema = deepcopy(schema)
    topic_schema = resolved_schema["properties"][response_field]["items"]
    reference_schema = topic_schema["properties"]["reference_chunk_ids"]
    allowed_ids = list(dict.fromkeys(str(chunk_id) for chunk_id in chunk_ids))
    if allowed_ids:
        reference_schema["items"] = {"type": "string", "enum": allowed_ids}
    else:
        reference_schema["maxItems"] = 0
    return resolved_schema


def validate_payload(
    payload: object,
    schema: Dict[str, object],
    payload_name: str,
) -> Dict[str, object]:
    try:
        Draft202012Validator(schema).validate(payload)
    except ValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(
            "{name} failed JSON Schema validation at {path}: {detail}".format(
                name=payload_name,
                path=path,
                detail=error.message,
            )
        ) from error
    if not isinstance(payload, dict):
        raise ValueError("{name} must be a JSON object.".format(name=payload_name))
    return payload
