"""Helpers for validating and defensively storing JSON-compatible values."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeAlias, cast

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = (
    JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
)
FrozenJsonValue: TypeAlias = (
    JsonScalar
    | tuple["FrozenJsonValue", ...]
    | Mapping[str, "FrozenJsonValue"]
)
FrozenJsonObject: TypeAlias = Mapping[str, FrozenJsonValue]

EMPTY_JSON_OBJECT: FrozenJsonObject = MappingProxyType({})


class DuplicateJsonKeyError(ValueError):
    """Raised when a serialized JSON object repeats an exact member name."""

    def __init__(self, key: str) -> None:
        super().__init__(f"duplicate JSON object key: {key!r}")
        self.key = key


def decode_json_with_unique_keys(value: str) -> object:
    """Decode JSON while rejecting exact duplicate object member names."""

    def build_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise DuplicateJsonKeyError(key)
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=build_object)


def validate_json_string(value: str, *, path: str = "$") -> str:
    """Return a string after rejecting Unicode surrogate code points."""

    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(
            f"{path} must contain valid Unicode scalar values"
        ) from error
    return value


def freeze_json_value(value: object, *, path: str = "$") -> FrozenJsonValue:
    """Validate and deeply freeze one JSON-compatible value.

    JSON arrays become tuples and objects become read-only mapping proxies.
    Non-finite floating-point values, non-string object keys, unsupported
    Python objects, and circular containers are rejected.
    """

    return _freeze_json_value(value, path=path, seen=set())


def freeze_json_object(
    values: Mapping[str, object] | None = None,
    *,
    reserved_keys: frozenset[str] | set[str] | tuple[str, ...] = (),
    parameter_name: str = "annotations",
) -> FrozenJsonObject:
    """Validate and deeply freeze a JSON object.

    ``reserved_keys`` prevents extension metadata from shadowing structural
    fields such as ``text`` or ``chapters``.
    """

    if values is None:
        return EMPTY_JSON_OBJECT
    if not isinstance(values, Mapping):
        raise TypeError(f"{parameter_name} must be a mapping")

    reserved = frozenset(reserved_keys)
    for key in values:
        if not isinstance(key, str):
            raise TypeError(f"{parameter_name} keys must be strings")
        validate_json_string(key, path=f"{parameter_name} key")
        if key in reserved:
            raise ValueError(
                f'{parameter_name} must not contain the structural key "{key}"'
            )

    if not values:
        return EMPTY_JSON_OBJECT
    frozen = _freeze_json_value(values, path=parameter_name, seen=set())
    return cast(FrozenJsonObject, frozen)


# A concise alias matching the terminology used by the sibling packages.
freeze_json_map = freeze_json_object


def thaw_json_value(value: FrozenJsonValue) -> JsonValue:
    """Return a fresh ordinary ``dict``/``list`` JSON value.

    The returned value can be passed directly to :mod:`json`; mutating it does
    not mutate the model that owns the frozen source value.
    """

    if isinstance(value, Mapping):
        return {key: thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json_value(item) for item in value]
    return value


def json_value_equal(first: object, second: object) -> bool:
    """Compare JSON values structurally without Python's ``True == 1`` quirk."""

    if isinstance(first, bool) or isinstance(second, bool):
        return isinstance(first, bool) and isinstance(second, bool) and first == second
    if isinstance(first, Mapping) or isinstance(second, Mapping):
        if not isinstance(first, Mapping) or not isinstance(second, Mapping):
            return False
        if first.keys() != second.keys():
            return False
        return all(json_value_equal(first[key], second[key]) for key in first)
    if isinstance(first, (list, tuple)) or isinstance(second, (list, tuple)):
        if not isinstance(first, (list, tuple)) or not isinstance(second, (list, tuple)):
            return False
        return len(first) == len(second) and all(
            json_value_equal(left, right) for left, right in zip(first, second)
        )
    return first == second


def json_value_hash(value: FrozenJsonValue) -> int:
    """Return an order-independent structural hash for a frozen JSON value."""

    if value is None:
        return hash(("null",))
    if isinstance(value, bool):
        return hash(("bool", value))
    if isinstance(value, (int, float)):
        return hash(("number", value))
    if isinstance(value, str):
        return hash(("string", value))
    if isinstance(value, Mapping):
        return hash(
            (
                "object",
                frozenset(
                    (key, json_value_hash(item)) for key, item in value.items()
                ),
            )
        )
    return hash(("array", tuple(json_value_hash(item) for item in value)))


def _freeze_json_value(
    value: object,
    *,
    path: str,
    seen: set[int],
) -> FrozenJsonValue:
    if isinstance(value, str):
        return validate_json_string(value, path=path)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be a finite JSON number")
        return value

    if isinstance(value, Mapping):
        identity = id(value)
        if identity in seen:
            raise ValueError(f"{path} must not contain circular references")
        seen.add(identity)
        try:
            result: dict[str, FrozenJsonValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError(f"{path} keys must be strings")
                validate_json_string(key, path=f"{path} key")
                result[key] = _freeze_json_value(
                    item,
                    path=f"{path}.{key}",
                    seen=seen,
                )
            return MappingProxyType(result)
        finally:
            seen.remove(identity)

    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in seen:
            raise ValueError(f"{path} must not contain circular references")
        seen.add(identity)
        try:
            return tuple(
                _freeze_json_value(item, path=f"{path}[{index}]", seen=seen)
                for index, item in enumerate(value)
            )
        finally:
            seen.remove(identity)

    raise TypeError(f"{path} must be JSON-compatible, got {type(value).__name__}")
