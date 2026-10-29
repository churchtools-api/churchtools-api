"""Runtime support for the generated models and resources."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import enum
import functools
import json
import mimetypes
import os
import pathlib
import typing as _t
from urllib.parse import quote

from pydantic import BaseModel, BeforeValidator, ConfigDict, TypeAdapter

T = _t.TypeVar("T")


class CTModel(BaseModel):
    """Base of all generated models.

    Unknown fields (e.g. instance-specific DB fields) are kept and available via
    `model_extra`. Serialization uses the API's camelCase names.
    """

    model_config = ConfigDict(
        extra="allow",
        # The API sometimes sends numbers where the spec says string.
        coerce_numbers_to_str=True,
        # 1100+ models: build validators on first use instead of at import.
        defer_build=True,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


def _zero_date_to_none(value: _t.Any) -> _t.Any:
    # PHP renders an unset date as "-0001-11-30T00:00:00" (shifted by the time zone).
    if isinstance(value, str) and (value.startswith("-") or value.startswith("0000-")):
        return None
    return value


OptionalDateTime = _t.Annotated[_t.Optional[_dt.datetime], BeforeValidator(_zero_date_to_none)]
"""An optional timestamp; the PHP zero date some old records carry becomes `None`."""


def _empty_list_to_dict(value: _t.Any) -> _t.Any:
    # PHP encodes an empty associative array as [].
    return {} if isinstance(value, list) and not value else value


V = _t.TypeVar("V")

StrMap = _t.Annotated[_t.Dict[str, V], BeforeValidator(_empty_list_to_dict)]
"""A JSON object; also accepts `[]`, which PHP sends for an empty one."""


class UnsetType(enum.Enum):
    UNSET = "UNSET"

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = UnsetType.UNSET
"""Marks a body field that is not sent at all (as opposed to `None`, which sends null)."""


class _Envelope(BaseModel, _t.Generic[T]):
    data: T


@functools.lru_cache(maxsize=None)
def _adapter(tp: _t.Any, envelope: bool) -> TypeAdapter[_t.Any]:
    return TypeAdapter(_Envelope[tp] if envelope else tp)


def _parse(body: bytes, tp: _t.Any, envelope: bool) -> _t.Any:
    from ._errors import DecodeError
    from pydantic import ValidationError

    if not body.strip():
        return None  # 204 No Content where the spec also allows a body
    try:
        value = _adapter(tp, envelope).validate_json(body)
    except ValidationError as e:
        raise DecodeError(_describe(e), body) from None
    return value.data if envelope else value


def _describe(error: _t.Any) -> str:
    """Like `str(ValidationError)`, but without the input values: they may be
    personal data and error messages end up in logs. The body stays in `DecodeError.body`."""
    lines = [f"{error.error_count()} validation error(s) for {error.title}"]
    for e in error.errors(include_input=False, include_url=False)[:10]:
        loc = ".".join(str(part) for part in e["loc"])
        lines.append(f"  {loc}: {e['msg']} [type={e['type']}]")
    return "\n".join(lines)


def _wire_datetime(value: _dt.datetime) -> str:
    """`2026-11-01T10:00:00Z`: the server rejects offsets and fractional seconds.

    Naive datetimes are taken as local time.
    """
    return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(value: _t.Any) -> _t.Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(by_alias=True, exclude_unset=True))
    if isinstance(value, _dt.datetime):
        return _wire_datetime(value)
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items() if v is not UNSET}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _body(fields: _t.Any, extra: _t.Optional[_t.Dict[str, _t.Any]] = None) -> _t.Optional[str]:
    if fields is None:
        return None
    if isinstance(fields, dict):
        fields = {k: v for k, v in fields.items() if v is not UNSET}
        fields.update(extra or {})
    return json.dumps(_jsonable(fields))


def _query_value(value: _t.Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, _dt.datetime):
        return _wire_datetime(value)
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, (dict, BaseModel)):
        return json.dumps(_jsonable(value))
    return str(value)


def _query(items: _t.Iterable[_t.Tuple[str, _t.Any]]) -> _t.List[_t.Tuple[str, str]]:
    """Builds wire query pairs; None is skipped, lists repeat the key."""
    out: _t.List[_t.Tuple[str, str]] = []
    for key, value in items:
        if value is None:
            continue
        values = value if isinstance(value, (list, tuple, set)) else [value]
        out.extend((key, _query_value(v)) for v in values)
    return out


def _seg(value: _t.Any) -> str:
    return quote(_query_value(value), safe="")


@dataclasses.dataclass(frozen=True)
class Upload:
    """A file for an upload endpoint, e.g. `Upload("plan.pdf", data)` or `Upload.from_path("plan.pdf")`."""

    filename: str
    content: bytes
    content_type: _t.Optional[str] = None
    """MIME type; guessed from the file name when omitted."""

    @classmethod
    def from_path(cls, path: _t.Union[str, "os.PathLike[str]"], content_type: _t.Optional[str] = None) -> "Upload":
        p = pathlib.Path(path)
        return cls(p.name, p.read_bytes(), content_type)


# (name of the file field, other form fields, files)
_UploadArgs = _t.Tuple[str, _t.List[_t.Tuple[str, str]], _t.Sequence[Upload]]


class Resource:
    def __init__(self, core: _t.Any) -> None:
        self._core = core

    def _raw(
        self,
        method: str,
        path: str,
        query: _t.List[_t.Tuple[str, str]],
        body: _t.Optional[str],
        upload: _t.Optional[_UploadArgs] = None,
    ) -> bytes:
        if upload is not None:
            field, form, files = upload
            parts = [(f.filename, f.content, f.content_type or _guess_type(f.filename)) for f in files]
            return _t.cast(bytes, self._core.request_multipart(method, path, query, form, field, parts))
        return _t.cast(bytes, self._core.request(method, path, query, body))

    def _call(
        self,
        method: str,
        path: str,
        query: _t.List[_t.Tuple[str, str]],
        body: _t.Optional[str],
        tp: _t.Any,
        envelope: bool = True,
        upload: _t.Optional[_UploadArgs] = None,
    ) -> _t.Any:
        return _parse(self._raw(method, path, query, body, upload), tp, envelope)


def _guess_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


class Paginator(_t.Generic[T]):
    """Lazily iterates over all items of a paginated endpoint.

    Pages are requested only as far as you iterate; `limit` sets the page size.
    """

    def __init__(self, core: _t.Any, path: str, query: _t.List[_t.Tuple[str, str]], item: _t.Any) -> None:
        self._core = core
        self._path = path
        self._query = query
        self._item = item

    def __iter__(self) -> _t.Iterator[T]:
        for page in self._core.pages(self._path, self._query):
            yield from _parse(page, _t.List[self._item], True)  # type: ignore[name-defined]

    def pages(self) -> _t.Iterator[_t.List[T]]:
        """Iterates page by page instead of item by item."""
        for page in self._core.pages(self._path, self._query):
            yield _parse(page, _t.List[self._item], True)  # type: ignore[name-defined]

    def to_list(self) -> _t.List[T]:
        return list(self)

    def first(self) -> _t.Optional[T]:
        return next(iter(self), None)
