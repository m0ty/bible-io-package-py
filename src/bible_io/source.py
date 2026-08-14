"""Translation metadata and reusable Bible source catalogs."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from types import MappingProxyType
from typing import Awaitable, cast

from bible_io_references import BibleLanguageEnum

from .errors import BibleDataFormatError, BibleDataFormatErrorCode
from .json_value import (
    EMPTY_JSON_OBJECT,
    DuplicateJsonKeyError,
    FrozenJsonObject,
    FrozenJsonValue,
    decode_json_with_unique_keys,
    freeze_json_object,
    freeze_json_value,
    json_value_equal,
    json_value_hash,
    thaw_json_value,
    validate_json_string,
)


_UNSET = object()
_NO_VALUE = object()
_SIMPLE_PATH_KEY = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


class TextDirectionHint(str, Enum):
    """Direction hint for Scripture text and labels."""

    AUTO = "auto"
    LTR = "ltr"
    RTL = "rtl"

    auto = AUTO
    ltr = LTR
    rtl = RTL

    @classmethod
    def from_string(cls, value: str | None) -> "TextDirectionHint":
        """Parse common spellings, defaulting unknown values to ``AUTO``."""

        normalized = value.strip().casefold() if isinstance(value, str) else None
        if normalized in {"ltr", "left-to-right", "left_to_right"}:
            return cls.LTR
        if normalized in {"rtl", "right-to-left", "right_to_left"}:
            return cls.RTL
        return cls.AUTO

    from_name = from_string

    def __str__(self) -> str:
        return self.value


def _json_path(base: str, key: str) -> str:
    if _SIMPLE_PATH_KEY.fullmatch(key):
        return f"{base}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{base}['{escaped}']"


def _data_error(
    code: BibleDataFormatErrorCode,
    path: str,
    message: str,
    *,
    value: object = _NO_VALUE,
    cause: BaseException | None = None,
) -> BibleDataFormatError:
    kwargs: dict[str, object] = {
        "code": code,
        "path": path,
        "message": message,
        "cause": cause,
    }
    if value is not _NO_VALUE:
        kwargs["value"] = value
    return BibleDataFormatError(**kwargs)  # type: ignore[arg-type]


def _as_object(value: object, *, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _data_error(
            BibleDataFormatErrorCode.INVALID_TYPE,
            path,
            "Expected a JSON object.",
            value=value,
        )
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise _data_error(
                BibleDataFormatErrorCode.NON_JSON_VALUE,
                path,
                "JSON object keys must be strings.",
                value=key,
            )
        result[key] = item
    return result


def _read_string(
    value: Mapping[str, object] | None,
    keys: Iterable[str],
    *,
    path: str,
) -> str | None:
    if value is None:
        return None
    for key in keys:
        if key not in value or value[key] is None:
            continue
        raw = value[key]
        if not isinstance(raw, str):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, key),
                "Expected a string.",
                value=raw,
            )
        if not raw.strip():
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_VALUE,
                _json_path(path, key),
                "String value cannot be blank.",
                value=raw,
            )
        try:
            validate_json_string(raw, path=_json_path(path, key))
        except ValueError as error:
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_VALUE,
                _json_path(path, key),
                "String value must contain valid Unicode scalar values.",
                value=raw,
                cause=error,
            ) from error
        return raw.strip()
    return None


def _read_identifier(
    value: Mapping[str, object] | None,
    keys: Iterable[str],
    *,
    path: str,
) -> str | None:
    if value is None:
        return None
    for key in keys:
        if key not in value or value[key] is None:
            continue
        raw = value[key]
        if not isinstance(raw, str):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, key),
                "Expected an identifier string.",
                value=raw,
            )
        if not raw.strip() or raw != raw.strip():
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_VALUE,
                _json_path(path, key),
                "Identifiers must be non-blank and have no surrounding whitespace.",
                value=raw,
            )
        try:
            validate_json_string(raw, path=_json_path(path, key))
        except ValueError as error:
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_VALUE,
                _json_path(path, key),
                "Identifier must contain valid Unicode scalar values.",
                value=raw,
                cause=error,
            ) from error
        return raw
    return None


def _read_int(
    value: Mapping[str, object] | None,
    keys: Iterable[str],
    *,
    path: str,
) -> int | None:
    if value is None:
        return None
    for key in keys:
        if key not in value or value[key] is None:
            continue
        raw = value[key]
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            try:
                return int(raw.strip())
            except ValueError as error:
                raise _data_error(
                    BibleDataFormatErrorCode.INVALID_VALUE,
                    _json_path(path, key),
                    "Expected an integer value.",
                    value=raw,
                    cause=error,
                ) from error
        raise _data_error(
            BibleDataFormatErrorCode.INVALID_TYPE,
            _json_path(path, key),
            "Expected an integer.",
            value=raw,
        )
    return None


def _parse_datetime(value: str, *, path: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise _data_error(
            BibleDataFormatErrorCode.INVALID_VALUE,
            path,
            "Expected an ISO-8601 date.",
            value=value,
            cause=error,
        ) from error


def _read_datetime(
    value: Mapping[str, object] | None,
    keys: Iterable[str],
    *,
    path: str,
) -> datetime | None:
    key_tuple = tuple(keys)
    raw = _read_string(value, key_tuple, path=path)
    if raw is None:
        return None
    assert value is not None
    actual_key = next(key for key in key_tuple if value.get(key) is not None)
    return _parse_datetime(raw, path=_json_path(path, actual_key))


def _read_direction(
    value: Mapping[str, object] | None,
    *,
    path: str,
) -> TextDirectionHint | None:
    keys = ("direction", "textDirection", "text_direction")
    raw = _read_string(value, keys, path=path)
    if raw is None:
        return None
    normalized = raw.casefold()
    if normalized == "auto":
        return TextDirectionHint.AUTO
    if normalized in {"ltr", "left-to-right", "left_to_right"}:
        return TextDirectionHint.LTR
    if normalized in {"rtl", "right-to-left", "right_to_left"}:
        return TextDirectionHint.RTL
    assert value is not None
    actual_key = next(key for key in keys if value.get(key) is not None)
    raise _data_error(
        BibleDataFormatErrorCode.INVALID_VALUE,
        _json_path(path, actual_key),
        "Text direction must be auto, ltr, or rtl.",
        value=raw,
    )


def _freeze_parsed_additional(
    values: Mapping[str, object],
    *,
    path: str,
    reserved_keys: frozenset[str],
) -> FrozenJsonObject:
    frozen: dict[str, FrozenJsonValue] = {}
    for key, item in values.items():
        item_path = _json_path(path, key)
        if key in reserved_keys:
            raise _data_error(
                BibleDataFormatErrorCode.RESERVED_FIELD,
                item_path,
                "Recognized metadata fields cannot be stored as extensions.",
                value=item,
            )
        try:
            frozen[key] = freeze_json_value(item, path=item_path)
        except (TypeError, ValueError) as error:
            raise _data_error(
                BibleDataFormatErrorCode.NON_JSON_VALUE,
                item_path,
                "Metadata extensions must contain JSON-compatible values.",
                value=item,
                cause=error,
            ) from error
    if not frozen:
        return EMPTY_JSON_OBJECT
    return MappingProxyType(frozen)


def _thaw_object(value: FrozenJsonObject) -> dict[str, object]:
    return cast(dict[str, object], thaw_json_value(value))


def _validate_model_string(
    value: object,
    *,
    path: str,
    label: str,
    blank_code: BibleDataFormatErrorCode = BibleDataFormatErrorCode.INVALID_VALUE,
) -> None:
    if not isinstance(value, str):
        raise _data_error(
            BibleDataFormatErrorCode.INVALID_TYPE,
            path,
            f"{label} must be a string.",
            value=value,
        )
    if not value.strip():
        raise _data_error(
            blank_code,
            path,
            f"{label} must not be blank.",
            value=value,
        )
    if value != value.strip():
        raise _data_error(
            BibleDataFormatErrorCode.INVALID_VALUE,
            path,
            f"{label} must have no surrounding whitespace.",
            value=value,
        )
    try:
        validate_json_string(value, path=path)
    except ValueError as error:
        raise _data_error(
            BibleDataFormatErrorCode.INVALID_VALUE,
            path,
            f"{label} must contain valid Unicode scalar values.",
            value=value,
            cause=error,
        ) from error


def _label_from_segment(segment: str) -> str:
    return " ".join(
        word[:1].upper() + word[1:].lower()
        for word in re.split(r"[_-]+", segment)
        if word
    )


def _sanitize_id(value: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return sanitized or "bible_source"


def _language_code_for_name(language_name: str) -> str | None:
    try:
        language = BibleLanguageEnum.from_str(language_name)
    except (TypeError, ValueError):
        language = BibleLanguageEnum.AUTO
    if language != BibleLanguageEnum.AUTO:
        return language.code
    if language_name.strip().casefold() == "italian":
        return "it"
    return None


def _direction_for_language_code(language_code: str) -> TextDirectionHint:
    if language_code.strip().casefold() in {"ar", "fa", "he", "ur"}:
        return TextDirectionHint.RTL
    return TextDirectionHint.AUTO


def _normalize_datetime(value: datetime | date | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time())
    raise TypeError("version_date must be datetime, date, or None")


def _datetime_json(value: datetime) -> str:
    return value.isoformat()


_SOURCE_PATH_KEYS = frozenset({"assetPath", "asset_path", "path", "file", "url"})
_SOURCE_RECOGNIZED_KEYS = frozenset(
    {
        *_SOURCE_PATH_KEYS,
        "id",
        "key",
        "languageName",
        "language_name",
        "language",
        "languageCode",
        "language_code",
        "lang",
        "translationName",
        "translation_name",
        "name",
        "title",
        "version",
        "abbreviation",
        "abbr",
        "shortName",
        "short_name",
        "description",
        "summary",
        "year",
        "direction",
        "textDirection",
        "text_direction",
        "sourceName",
        "source_name",
        "source",
        "copyright",
        "license",
        "canon",
        "versionDate",
        "version_date",
        "date",
    }
)
_METADATA_RECOGNIZED_KEYS = frozenset(
    {*_SOURCE_RECOGNIZED_KEYS, "editionId", "edition_id"}
)
_ROOT_RECOGNIZED_KEYS = frozenset({*_METADATA_RECOGNIZED_KEYS, "books", "metadata"})


@dataclass(frozen=True, slots=True, eq=False)
class BibleSource:
    """Metadata for one loadable Bible source."""

    id: str
    asset_path: str
    language_name: str
    language_code: str
    translation_name: str
    abbreviation: str
    description: str | None = None
    year: int | None = None
    direction: TextDirectionHint = TextDirectionHint.AUTO
    source_name: str | None = None
    copyright: str | None = None
    license: str | None = None
    canon: str | None = None
    version_date: datetime | None = None
    additional: FrozenJsonObject = field(default_factory=lambda: EMPTY_JSON_OBJECT)

    def __post_init__(self) -> None:
        object.__setattr__(self, "version_date", _normalize_datetime(self.version_date))
        if not isinstance(self.additional, Mapping):
            raise TypeError("additional must be a mapping")
        if self.additional is not EMPTY_JSON_OBJECT:
            object.__setattr__(
                self,
                "additional",
                freeze_json_object(self.additional, parameter_name="additional"),
            )

    @classmethod
    def checked(cls, *, path: str = "$", **values: object) -> "BibleSource":
        prepared = dict(values)
        if "additional" in prepared:
            raw_additional = prepared["additional"]
            if not isinstance(raw_additional, Mapping):
                raise _data_error(
                    BibleDataFormatErrorCode.INVALID_TYPE,
                    path,
                    "Bible source extensions must be an object.",
                    value=raw_additional,
                )
            prepared["additional"] = _freeze_parsed_additional(
                raw_additional,
                path=path,
                reserved_keys=_METADATA_RECOGNIZED_KEYS,
            )
        source = cls(**prepared)  # type: ignore[arg-type]
        return source.validate(path=path)

    @classmethod
    def from_asset_path(
        cls,
        asset_path: str,
        *,
        id: str | None = None,
        language_name: str | None = None,
        language_code: str | None = None,
        translation_name: str | None = None,
        abbreviation: str | None = None,
        year: int | None = None,
        direction: TextDirectionHint | None = None,
    ) -> "BibleSource":
        if not isinstance(asset_path, str):
            raise TypeError("asset_path must be a string")
        normalized = asset_path.replace("\\", "/")
        segments = [segment for segment in normalized.split("/") if segment]
        filename = segments[-1] if segments else normalized
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        inferred_language = language_name or (
            _label_from_segment(segments[-2]) if len(segments) > 1 else ""
        )
        inferred_code = (
            language_code or _language_code_for_name(inferred_language) or ""
        )
        inferred_abbreviation = abbreviation or stem.upper()
        inferred_translation = translation_name or _label_from_segment(stem).upper()
        return cls(
            id=id
            or _sanitize_id(
                "_".join(
                    item
                    for item in (inferred_language, inferred_abbreviation)
                    if item
                )
            ),
            asset_path=asset_path,
            language_name=inferred_language,
            language_code=inferred_code,
            translation_name=inferred_translation,
            abbreviation=inferred_abbreviation,
            year=year,
            direction=direction or _direction_for_language_code(inferred_code),
        )

    @classmethod
    def from_decoded_json(
        cls,
        value: Mapping[str, object],
        *,
        path: str = "$",
    ) -> "BibleSource":
        data = _as_object(value, path=path)
        asset_path = _read_string(data, _SOURCE_PATH_KEYS, path=path) or ""
        fallback = cls.from_asset_path(asset_path) if asset_path else None
        language_name = (
            _read_string(
                data,
                ("languageName", "language_name", "language"),
                path=path,
            )
            or (fallback.language_name if fallback else "")
        )
        language_code = (
            _read_string(
                data,
                ("languageCode", "language_code", "lang"),
                path=path,
            )
            or (fallback.language_code if fallback else None)
            or _language_code_for_name(language_name)
            or ""
        )
        abbreviation = (
            _read_string(
                data,
                ("abbreviation", "abbr", "shortName", "short_name"),
                path=path,
            )
            or (fallback.abbreviation if fallback else "")
        )
        translation_name = (
            _read_string(
                data,
                ("translationName", "translation_name", "name", "title", "version"),
                path=path,
            )
            or (fallback.translation_name if fallback else None)
            or abbreviation
        )
        direction = (
            _read_direction(data, path=path)
            or (fallback.direction if fallback else None)
            or _direction_for_language_code(language_code)
        )
        additional = _freeze_parsed_additional(
            {key: item for key, item in data.items() if key not in _SOURCE_RECOGNIZED_KEYS},
            path=path,
            reserved_keys=_METADATA_RECOGNIZED_KEYS,
        )
        source = cls(
            id=(
                _read_identifier(data, ("id", "key"), path=path)
                or (fallback.id if fallback else None)
                or _sanitize_id(f"{language_name}_{abbreviation}")
            ),
            asset_path=asset_path,
            language_name=language_name,
            language_code=language_code,
            translation_name=translation_name,
            abbreviation=abbreviation,
            description=_read_string(data, ("description", "summary"), path=path),
            year=_read_int(data, ("year",), path=path),
            direction=direction,
            source_name=_read_string(
                data,
                ("sourceName", "source_name", "source"),
                path=path,
            ),
            copyright=_read_string(data, ("copyright",), path=path),
            license=_read_string(data, ("license",), path=path),
            canon=_read_string(data, ("canon",), path=path),
            version_date=_read_datetime(
                data,
                ("versionDate", "version_date", "date"),
                path=path,
            ),
            additional=additional,
        )
        return source.validate(path=path)

    @classmethod
    def from_json(cls, value: str, *, path: str = "$") -> "BibleSource":
        try:
            decoded = decode_json_with_unique_keys(value)
        except DuplicateJsonKeyError as error:
            raise _data_error(
                BibleDataFormatErrorCode.DUPLICATE_KEY,
                path,
                f"Bible source JSON repeats object key {error.key!r}.",
                value=error.key,
                cause=error,
            ) from error
        except (TypeError, json.JSONDecodeError) as error:
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_JSON,
                path,
                "Bible source is not valid JSON.",
                cause=error,
            ) from error
        return cls.from_decoded_json(_as_object(decoded, path=path), path=path)

    def validate(self, *, path: str = "$") -> "BibleSource":
        for field_name, json_name in (
            ("id", "id"),
            ("asset_path", "assetPath"),
            ("language_name", "languageName"),
            ("language_code", "languageCode"),
            ("translation_name", "translationName"),
            ("abbreviation", "abbreviation"),
        ):
            value = getattr(self, field_name)
            _validate_model_string(
                value,
                path=_json_path(path, json_name),
                label=f'Bible source field "{json_name}"',
                blank_code=BibleDataFormatErrorCode.MISSING_FIELD,
            )
        for field_name, json_name in (
            ("description", "description"),
            ("source_name", "sourceName"),
            ("copyright", "copyright"),
            ("license", "license"),
            ("canon", "canon"),
        ):
            value = getattr(self, field_name)
            if value is not None:
                _validate_model_string(
                    value,
                    path=_json_path(path, json_name),
                    label=f'Bible source field "{json_name}"',
                )
        if self.year is not None and (
            isinstance(self.year, bool) or not isinstance(self.year, int)
        ):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, "year"),
                "Bible source year must be an integer.",
                value=self.year,
            )
        if not isinstance(self.direction, TextDirectionHint):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, "direction"),
                "Bible source direction must be TextDirectionHint.",
                value=self.direction,
            )
        if self.version_date is not None and not isinstance(self.version_date, datetime):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, "versionDate"),
                "Bible source version date must be a datetime.",
                value=self.version_date,
            )
        for key, item in self.additional.items():
            if key in _METADATA_RECOGNIZED_KEYS:
                raise _data_error(
                    BibleDataFormatErrorCode.RESERVED_FIELD,
                    _json_path(path, key),
                    "Recognized metadata fields cannot be stored as extensions.",
                    value=item,
                )
        return self

    def copy_with(self, **changes: object) -> "BibleSource":
        values: dict[str, object] = {
            "id": self.id,
            "asset_path": self.asset_path,
            "language_name": self.language_name,
            "language_code": self.language_code,
            "translation_name": self.translation_name,
            "abbreviation": self.abbreviation,
            "description": self.description,
            "year": self.year,
            "direction": self.direction,
            "source_name": self.source_name,
            "copyright": self.copyright,
            "license": self.license,
            "canon": self.canon,
            "version_date": self.version_date,
            "additional": self.additional,
        }
        unknown = set(changes) - set(values)
        if unknown:
            raise TypeError(f"unknown BibleSource fields: {', '.join(sorted(unknown))}")
        values.update(changes)
        return BibleSource(**values).validate()  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        self.validate()
        result = _thaw_object(self.additional)
        result.update(
            {
                "id": self.id,
                "assetPath": self.asset_path,
                "languageName": self.language_name,
                "languageCode": self.language_code,
                "translationName": self.translation_name,
                "abbreviation": self.abbreviation,
                "direction": self.direction.value,
            }
        )
        for key, value in (
            ("description", self.description),
            ("year", self.year),
            ("sourceName", self.source_name),
            ("copyright", self.copyright),
            ("license", self.license),
            ("canon", self.canon),
        ):
            if value is not None:
                result[key] = value
        if self.version_date is not None:
            result["versionDate"] = _datetime_json(self.version_date)
        return result

    to_dict = to_json
    to_json_value = to_json

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BibleSource):
            return NotImplemented
        return (
            self.id,
            self.asset_path,
            self.language_name,
            self.language_code,
            self.translation_name,
            self.abbreviation,
            self.description,
            self.year,
            self.direction,
            self.source_name,
            self.copyright,
            self.license,
            self.canon,
            self.version_date,
        ) == (
            other.id,
            other.asset_path,
            other.language_name,
            other.language_code,
            other.translation_name,
            other.abbreviation,
            other.description,
            other.year,
            other.direction,
            other.source_name,
            other.copyright,
            other.license,
            other.canon,
            other.version_date,
        ) and json_value_equal(self.additional, other.additional)

    def __hash__(self) -> int:
        return hash(
            (
                self.id,
                self.asset_path,
                self.language_name,
                self.language_code,
                self.translation_name,
                self.abbreviation,
                self.description,
                self.year,
                self.direction,
                self.source_name,
                self.copyright,
                self.license,
                self.canon,
                self.version_date,
                json_value_hash(self.additional),
            )
        )


@dataclass(frozen=True, slots=True, eq=False)
class BibleMetadata:
    """Edition identity, display metadata, provenance, and content rights."""

    source: BibleSource | None = None
    id: str | None = None
    description: str | None = None
    language_name: str | None = None
    language_code: str | None = None
    translation_name: str | None = None
    abbreviation: str | None = None
    year: int | None = None
    direction: TextDirectionHint = TextDirectionHint.AUTO
    source_name: str | None = None
    copyright: str | None = None
    license: str | None = None
    canon: str | None = None
    version_date: datetime | None = None
    additional: FrozenJsonObject = field(default_factory=lambda: EMPTY_JSON_OBJECT)

    def __post_init__(self) -> None:
        object.__setattr__(self, "version_date", _normalize_datetime(self.version_date))
        if not isinstance(self.additional, Mapping):
            raise TypeError("additional must be a mapping")
        if self.additional is not EMPTY_JSON_OBJECT:
            object.__setattr__(
                self,
                "additional",
                freeze_json_object(self.additional, parameter_name="additional"),
            )

    @classmethod
    def with_additional(cls, *, path: str = "$.metadata", **values: object) -> "BibleMetadata":
        prepared = dict(values)
        if "additional" in prepared:
            raw_additional = prepared["additional"]
            if not isinstance(raw_additional, Mapping):
                raise _data_error(
                    BibleDataFormatErrorCode.INVALID_TYPE,
                    path,
                    "Bible metadata extensions must be an object.",
                    value=raw_additional,
                )
            prepared["additional"] = _freeze_parsed_additional(
                raw_additional,
                path=path,
                reserved_keys=_METADATA_RECOGNIZED_KEYS,
            )
        metadata = cls(**prepared)  # type: ignore[arg-type]
        return metadata.validate(path=path)

    @classmethod
    def from_decoded_json(
        cls,
        value: Mapping[str, object],
        *,
        source: BibleSource | None = None,
    ) -> "BibleMetadata":
        if source is not None:
            if not isinstance(source, BibleSource):
                raise TypeError("source must be BibleSource or None")
            source.validate(path="$.source")
        root = _as_object(value, path="$")
        nested: dict[str, object] | None = None
        if "metadata" in root and root["metadata"] is not None:
            nested = _as_object(root["metadata"], path="$.metadata")

        embedded: BibleSource | None = None
        if nested is not None and nested.get("source") is not None:
            embedded = BibleSource.from_decoded_json(
                _as_object(nested["source"], path="$.metadata.source"),
                path="$.metadata.source",
            )
        elif root.get("source") is not None:
            embedded = BibleSource.from_decoded_json(
                _as_object(root["source"], path="$.source"),
                path="$.source",
            )
        effective_source = source or embedded

        def read_string(keys: tuple[str, ...]) -> str | None:
            return _read_string(nested, keys, path="$.metadata") or _read_string(
                root, keys, path="$"
            )

        def read_identifier(keys: tuple[str, ...]) -> str | None:
            return _read_identifier(
                nested, keys, path="$.metadata"
            ) or _read_identifier(root, keys, path="$")

        def read_int(keys: tuple[str, ...]) -> int | None:
            nested_value = _read_int(nested, keys, path="$.metadata")
            return nested_value if nested_value is not None else _read_int(
                root, keys, path="$"
            )

        def read_date(keys: tuple[str, ...]) -> datetime | None:
            nested_value = _read_datetime(nested, keys, path="$.metadata")
            return nested_value if nested_value is not None else _read_datetime(
                root, keys, path="$"
            )

        direction = _read_direction(nested, path="$.metadata")
        if direction is None:
            direction = _read_direction(root, path="$")

        language_name = read_string(("languageName", "language_name", "language"))
        if language_name is None and effective_source is not None:
            language_name = effective_source.language_name
        language_code = read_string(("languageCode", "language_code", "lang"))
        if language_code is None and effective_source is not None:
            language_code = effective_source.language_code
        if language_code is None and language_name is not None:
            language_code = _language_code_for_name(language_name)
        if direction is None:
            direction = (
                effective_source.direction
                if effective_source is not None
                else _direction_for_language_code(language_code or "")
            )

        additional_values: dict[str, object] = {
            key: item for key, item in root.items() if key not in _ROOT_RECOGNIZED_KEYS
        }
        if nested is not None:
            additional_values.update(
                {
                    key: item
                    for key, item in nested.items()
                    if key not in _METADATA_RECOGNIZED_KEYS
                }
            )
        additional = _freeze_parsed_additional(
            additional_values,
            path="$.metadata",
            reserved_keys=_METADATA_RECOGNIZED_KEYS,
        )

        def source_value(name: str) -> object | None:
            return getattr(effective_source, name) if effective_source else None

        metadata = cls(
            source=effective_source,
            id=read_identifier(("id", "editionId", "edition_id"))
            or cast(str | None, source_value("id")),
            description=read_string(("description", "summary"))
            or cast(str | None, source_value("description")),
            language_name=language_name,
            language_code=language_code,
            translation_name=read_string(
                ("translationName", "translation_name", "name", "title", "version")
            )
            or cast(str | None, source_value("translation_name")),
            abbreviation=read_string(
                ("abbreviation", "abbr", "shortName", "short_name")
            )
            or cast(str | None, source_value("abbreviation")),
            year=read_int(("year",))
            if read_int(("year",)) is not None
            else cast(int | None, source_value("year")),
            direction=direction,
            source_name=read_string(("sourceName", "source_name"))
            or cast(str | None, source_value("source_name")),
            copyright=read_string(("copyright",))
            or cast(str | None, source_value("copyright")),
            license=read_string(("license",))
            or cast(str | None, source_value("license")),
            canon=read_string(("canon",)) or cast(str | None, source_value("canon")),
            version_date=read_date(("versionDate", "version_date", "date"))
            or cast(datetime | None, source_value("version_date")),
            additional=additional,
        )
        return metadata.validate()

    @classmethod
    def from_json(
        cls,
        value: str,
        *,
        source: BibleSource | None = None,
    ) -> "BibleMetadata":
        try:
            decoded = decode_json_with_unique_keys(value)
        except DuplicateJsonKeyError as error:
            raise _data_error(
                BibleDataFormatErrorCode.DUPLICATE_KEY,
                "$",
                f"Bible metadata JSON repeats object key {error.key!r}.",
                value=error.key,
                cause=error,
            ) from error
        except (TypeError, json.JSONDecodeError) as error:
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_JSON,
                "$",
                "Bible metadata is not valid JSON.",
                cause=error,
            ) from error
        return cls.from_decoded_json(_as_object(decoded, path="$"), source=source)

    def validate(self, *, path: str = "$.metadata") -> "BibleMetadata":
        if self.source is not None:
            if not isinstance(self.source, BibleSource):
                raise _data_error(
                    BibleDataFormatErrorCode.INVALID_TYPE,
                    _json_path(path, "source"),
                    "Metadata source must be BibleSource.",
                    value=self.source,
                )
            self.source.validate(path=_json_path(path, "source"))
        for field_name, json_name in (
            ("id", "id"),
            ("description", "description"),
            ("language_name", "languageName"),
            ("language_code", "languageCode"),
            ("translation_name", "translationName"),
            ("abbreviation", "abbreviation"),
            ("source_name", "sourceName"),
            ("copyright", "copyright"),
            ("license", "license"),
            ("canon", "canon"),
        ):
            value = getattr(self, field_name)
            if value is not None:
                _validate_model_string(
                    value,
                    path=_json_path(path, json_name),
                    label=f'Bible metadata field "{json_name}"',
                )
        if self.year is not None and (
            isinstance(self.year, bool) or not isinstance(self.year, int)
        ):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, "year"),
                "Bible metadata year must be an integer.",
                value=self.year,
            )
        if not isinstance(self.direction, TextDirectionHint):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, "direction"),
                "Metadata direction must be TextDirectionHint.",
                value=self.direction,
            )
        if self.version_date is not None and not isinstance(self.version_date, datetime):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                _json_path(path, "versionDate"),
                "Metadata version date must be a datetime.",
                value=self.version_date,
            )
        for key, item in self.additional.items():
            if key in _METADATA_RECOGNIZED_KEYS:
                raise _data_error(
                    BibleDataFormatErrorCode.RESERVED_FIELD,
                    _json_path(path, key),
                    "Recognized metadata fields cannot be stored as extensions.",
                    value=item,
                )
        return self

    def copy_with(self, **changes: object) -> "BibleMetadata":
        values: dict[str, object] = {
            "source": self.source,
            "id": self.id,
            "description": self.description,
            "language_name": self.language_name,
            "language_code": self.language_code,
            "translation_name": self.translation_name,
            "abbreviation": self.abbreviation,
            "year": self.year,
            "direction": self.direction,
            "source_name": self.source_name,
            "copyright": self.copyright,
            "license": self.license,
            "canon": self.canon,
            "version_date": self.version_date,
            "additional": self.additional,
        }
        unknown = set(changes) - set(values)
        if unknown:
            raise TypeError(f"unknown BibleMetadata fields: {', '.join(sorted(unknown))}")
        values.update(changes)
        return BibleMetadata(**values).validate()  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        self.validate()
        result = _thaw_object(self.additional)
        if self.source is not None:
            result["source"] = self.source.to_json()
        for key, value in (
            ("id", self.id),
            ("description", self.description),
            ("languageName", self.language_name),
            ("languageCode", self.language_code),
            ("translationName", self.translation_name),
            ("abbreviation", self.abbreviation),
            ("year", self.year),
            ("sourceName", self.source_name),
            ("copyright", self.copyright),
            ("license", self.license),
            ("canon", self.canon),
        ):
            if value is not None:
                result[key] = value
        result["direction"] = self.direction.value
        if self.version_date is not None:
            result["versionDate"] = _datetime_json(self.version_date)
        return result

    to_dict = to_json
    to_json_value = to_json

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BibleMetadata):
            return NotImplemented
        return (
            self.source,
            self.id,
            self.description,
            self.language_name,
            self.language_code,
            self.translation_name,
            self.abbreviation,
            self.year,
            self.direction,
            self.source_name,
            self.copyright,
            self.license,
            self.canon,
            self.version_date,
        ) == (
            other.source,
            other.id,
            other.description,
            other.language_name,
            other.language_code,
            other.translation_name,
            other.abbreviation,
            other.year,
            other.direction,
            other.source_name,
            other.copyright,
            other.license,
            other.canon,
            other.version_date,
        ) and json_value_equal(self.additional, other.additional)

    def __hash__(self) -> int:
        return hash(
            (
                self.source,
                self.id,
                self.description,
                self.language_name,
                self.language_code,
                self.translation_name,
                self.abbreviation,
                self.year,
                self.direction,
                self.source_name,
                self.copyright,
                self.license,
                self.canon,
                self.version_date,
                json_value_hash(self.additional),
            )
        )


def merge_bible_metadata(
    *,
    metadata: BibleMetadata | None = None,
    source: BibleSource | None = None,
    fallback_language_name: str | None = None,
    fallback_language_code: str | None = None,
) -> BibleMetadata:
    """Merge metadata, source values, and language fallbacks by precedence."""

    if metadata is not None:
        if not isinstance(metadata, BibleMetadata):
            raise TypeError("metadata must be BibleMetadata or None")
        metadata.validate()
    if source is not None:
        if not isinstance(source, BibleSource):
            raise TypeError("source must be BibleSource or None")
        source.validate(path="$.source")
    effective_source = source or (metadata.source if metadata else None)
    metadata_direction = metadata.direction if metadata else None
    direction: TextDirectionHint
    if metadata_direction is not None and metadata_direction is not TextDirectionHint.AUTO:
        direction = metadata_direction
    elif effective_source is not None:
        direction = effective_source.direction
    elif metadata_direction is not None:
        direction = metadata_direction
    else:
        direction = _direction_for_language_code(
            (metadata.language_code if metadata else None)
            or (effective_source.language_code if effective_source else None)
            or fallback_language_code
            or ""
        )

    def choose(name: str, fallback: object = None) -> object:
        explicit = getattr(metadata, name) if metadata is not None else None
        if explicit is not None:
            return explicit
        inherited = getattr(effective_source, name) if effective_source is not None else None
        return inherited if inherited is not None else fallback

    return BibleMetadata(
        source=effective_source,
        id=cast(str | None, choose("id")),
        description=cast(str | None, choose("description")),
        language_name=cast(str | None, choose("language_name", fallback_language_name)),
        language_code=cast(str | None, choose("language_code", fallback_language_code)),
        translation_name=cast(str | None, choose("translation_name")),
        abbreviation=cast(str | None, choose("abbreviation")),
        year=cast(int | None, choose("year")),
        direction=direction,
        source_name=cast(str | None, choose("source_name")),
        copyright=cast(str | None, choose("copyright")),
        license=cast(str | None, choose("license")),
        canon=cast(str | None, choose("canon")),
        version_date=cast(datetime | None, choose("version_date")),
        additional=metadata.additional if metadata is not None else EMPTY_JSON_OBJECT,
    ).validate()


class BibleCatalog:
    """Immutable collection of sources indexed by stable edition ID."""

    __slots__ = ("_sources", "_sources_by_id")

    def __init__(self, sources: Iterable[BibleSource]) -> None:
        source_values = tuple(sources)
        by_id: dict[str, BibleSource] = {}
        for index, source in enumerate(source_values):
            if not isinstance(source, BibleSource):
                raise TypeError("catalog sources must be BibleSource values")
            path = f"$.sources[{index}]"
            source.validate(path=path)
            if source.id in by_id:
                raise _data_error(
                    BibleDataFormatErrorCode.DUPLICATE_ID,
                    f"{path}.id",
                    "Bible source IDs must be unique.",
                    value=source.id,
                )
            by_id[source.id] = source
        self._sources = source_values
        self._sources_by_id = MappingProxyType(by_id)

    @property
    def sources(self) -> tuple[BibleSource, ...]:
        return self._sources

    @classmethod
    def from_json(cls, value: str) -> "BibleCatalog":
        try:
            decoded = decode_json_with_unique_keys(value)
        except DuplicateJsonKeyError as error:
            raise _data_error(
                BibleDataFormatErrorCode.DUPLICATE_KEY,
                "$",
                f"Catalog JSON repeats object key {error.key!r}.",
                value=error.key,
                cause=error,
            ) from error
        except (TypeError, json.JSONDecodeError) as error:
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_JSON,
                "$",
                "Catalog is not valid JSON.",
                cause=error,
            ) from error
        return cls.from_decoded_json(decoded)

    @classmethod
    def from_utf8_bytes(
        cls,
        value: bytes | bytearray | memoryview | Iterable[int],
    ) -> "BibleCatalog":
        try:
            text = bytes(value).decode("utf-8")
        except (TypeError, ValueError, UnicodeError) as error:
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_JSON,
                "$",
                "Catalog is not valid UTF-8 JSON.",
                cause=error,
            ) from error
        return cls.from_json(text)

    @classmethod
    def from_decoded_json(cls, value: object) -> "BibleCatalog":
        sources: list[BibleSource] = []
        cls._parse_sources(value, path="$", output=sources)
        return cls(sources)

    @classmethod
    async def load_asset(cls, asset_bundle: object, key: str) -> "BibleCatalog":
        loader = getattr(asset_bundle, "load_string", None) or getattr(
            asset_bundle, "loadString", None
        )
        if not callable(loader):
            raise TypeError("asset_bundle must provide load_string(key)")
        loaded = loader(key)
        if inspect.isawaitable(loaded):
            loaded = await cast(Awaitable[object], loaded)
        if not isinstance(loaded, str):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                "$",
                "Asset bundle load_string must return a string.",
                value=loaded,
            )
        return cls.from_json(loaded)

    @classmethod
    def _parse_sources(
        cls,
        value: object,
        *,
        path: str,
        output: list[BibleSource],
        language_name: str | None = None,
        source_id: str | None = None,
        expect_source: bool = False,
    ) -> None:
        if isinstance(value, str):
            if not value.strip():
                raise _data_error(
                    BibleDataFormatErrorCode.INVALID_VALUE,
                    path,
                    "Bible source asset path cannot be blank.",
                    value=value,
                )
            source = BibleSource.from_asset_path(
                value,
                id=source_id,
                language_name=language_name,
            )
            output.append(source.validate(path=path))
            return
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                cls._parse_sources(
                    item,
                    path=f"{path}[{index}]",
                    output=output,
                    language_name=language_name,
                    expect_source=True,
                )
            return
        if not isinstance(value, Mapping):
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_TYPE,
                path,
                "Catalog entries must be source objects, lists, or paths.",
                value=value,
            )
        data = _as_object(value, path=path)
        if expect_source or any(key in _SOURCE_RECOGNIZED_KEYS for key in data):
            source_data = dict(data)
            if source_id is not None:
                source_data.setdefault("id", source_id)
            if language_name is not None:
                source_data.setdefault("languageName", language_name)
            output.append(BibleSource.from_decoded_json(source_data, path=path))
            return

        containers = [key for key in ("sources", "bibles", "translations") if key in data]
        if len(containers) > 1:
            raise _data_error(
                BibleDataFormatErrorCode.INVALID_VALUE,
                path,
                "Catalog must use only one source container key.",
                value=containers,
            )
        if containers:
            container_key = containers[0]
            cls._parse_sources(
                data[container_key],
                path=_json_path(path, container_key),
                output=output,
                language_name=language_name,
            )
            return

        for entry_key, item in data.items():
            item_path = _json_path(path, entry_key)
            if isinstance(item, str):
                cls._parse_sources(
                    item,
                    path=item_path,
                    output=output,
                    language_name=language_name,
                    source_id=entry_key,
                )
            elif isinstance(item, (list, tuple)):
                cls._parse_sources(
                    item,
                    path=item_path,
                    output=output,
                    language_name=language_name or entry_key,
                )
            elif isinstance(item, Mapping):
                item_data = _as_object(item, path=item_path)
                if any(name in _SOURCE_RECOGNIZED_KEYS for name in item_data):
                    cls._parse_sources(
                        item_data,
                        path=item_path,
                        output=output,
                        language_name=language_name,
                        source_id=entry_key,
                    )
                else:
                    cls._parse_sources(
                        item_data,
                        path=item_path,
                        output=output,
                        language_name=language_name or entry_key,
                    )
            else:
                raise _data_error(
                    BibleDataFormatErrorCode.INVALID_TYPE,
                    item_path,
                    "Catalog entry must be a source object, list, or path.",
                    value=item,
                )

    def find_by_id(self, source_id: str) -> BibleSource | None:
        return self._sources_by_id.get(source_id)

    def for_language(self, language_name_or_code: str) -> tuple[BibleSource, ...]:
        normalized = language_name_or_code.strip().casefold()
        return tuple(
            source
            for source in self.sources
            if source.language_name.casefold() == normalized
            or source.language_code.casefold() == normalized
        )

    @property
    def by_language_name(self) -> Mapping[str, tuple[BibleSource, ...]]:
        grouped: dict[str, list[BibleSource]] = {}
        for source in self.sources:
            grouped.setdefault(source.language_name, []).append(source)
        return MappingProxyType(
            {language: tuple(sources) for language, sources in grouped.items()}
        )

    def to_json(self) -> dict[str, object]:
        return {"sources": [source.to_json() for source in self.sources]}

    to_dict = to_json
    to_json_value = to_json

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BibleCatalog) and self.sources == other.sources

    def __hash__(self) -> int:
        return hash(self.sources)

    def __repr__(self) -> str:
        return f"BibleCatalog(sources={self.sources!r})"


__all__ = [
    "BibleCatalog",
    "BibleMetadata",
    "BibleSource",
    "TextDirectionHint",
    "merge_bible_metadata",
]
