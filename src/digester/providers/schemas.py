from __future__ import annotations

from typing import Dict

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


SOURCE_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "source_path": {"type": "string"},
        "locator": {"type": "string"},
    },
    "required": ["source_id", "source_path", "locator"],
    "additionalProperties": False,
}

TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "slug": {"type": "string"},
        "title": {"type": "string"},
        "routing_description": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "workflow_notes": {"type": "array", "items": {"type": "string"}},
        "references": {"type": "array", "items": SOURCE_REF_SCHEMA},
    },
    "required": [
        "slug",
        "title",
        "routing_description",
        "summary",
        "key_points",
        "workflow_notes",
        "references",
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
