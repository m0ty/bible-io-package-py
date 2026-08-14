"""A small typed result value for non-throwing application boundaries."""

from __future__ import annotations

from types import TracebackType
from typing import Callable, Generic, TypeVar, cast

from .errors import BibleError


T = TypeVar("T")
U = TypeVar("U")


class Result(Generic[T]):
    """A successful value or a failure retaining its original exception."""

    __slots__ = ()

    @classmethod
    def success(cls, value: T) -> "Result[T]":
        return Success(value)

    @classmethod
    def failure(cls, error: str) -> "Result[T]":
        return Failure(error)

    @classmethod
    def failure_from(
        cls,
        error: BaseException,
        traceback: TracebackType | None = None,
    ) -> "Result[T]":
        return Failure.from_exception(error, traceback)

    @property
    def is_success(self) -> bool:
        return isinstance(self, Success)

    @property
    def is_failure(self) -> bool:
        return isinstance(self, Failure)

    @property
    def value(self) -> T:
        if isinstance(self, Success):
            return cast(T, self._value)
        failure = cast(Failure[T], self)
        exception = ResultException(
            failure._error,
            cause=failure.cause,
            traceback=failure.traceback,
        )
        if failure.cause is not None:
            raise exception.with_traceback(failure.traceback) from failure.cause
        raise exception.with_traceback(failure.traceback)

    @property
    def error(self) -> str | None:
        return self._error if isinstance(self, Failure) else None

    @property
    def cause(self) -> BaseException | None:
        return self._cause if isinstance(self, Failure) else None

    @property
    def traceback(self) -> TracebackType | None:
        return self._traceback if isinstance(self, Failure) else None

    @property
    def stack_trace(self) -> TracebackType | None:
        return self.traceback

    def map(self, transform: Callable[[T], U]) -> "Result[U]":
        if isinstance(self, Success):
            return Success(transform(cast(T, self._value)))
        failure = cast(Failure[T], self)
        return Failure(
            failure._error,
            cause=failure._cause,
            traceback=failure._traceback,
        )

    def flat_map(self, transform: Callable[[T], "Result[U]"]) -> "Result[U]":
        if isinstance(self, Success):
            result = transform(cast(T, self._value))
            if not isinstance(result, Result):
                raise TypeError("flat_map transform must return Result")
            return result
        failure = cast(Failure[T], self)
        return Failure(
            failure._error,
            cause=failure._cause,
            traceback=failure._traceback,
        )

    def get_or_else(self, default_value: T) -> T:
        return self.value if isinstance(self, Success) else default_value

    def fold(
        self,
        on_failure: Callable[[str], U],
        on_success: Callable[[T], U],
    ) -> U:
        if isinstance(self, Success):
            return on_success(cast(T, self._value))
        return on_failure(cast(Failure[T], self)._error)


class Success(Result[T]):
    """Successful result."""

    __slots__ = ("_value",)
    __match_args__ = ("value",)

    def __init__(self, value: T) -> None:
        self._value = value

    def __repr__(self) -> str:
        return f"Success({self._value!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Success) and self._value == other._value

    def __hash__(self) -> int:
        return hash((Success, self._value))


class Failure(Result[T]):
    """Failed result with optional original exception and traceback."""

    __slots__ = ("_error", "_cause", "_traceback")
    __match_args__ = ("error", "cause", "traceback")

    def __init__(
        self,
        error: str,
        *,
        cause: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        if not isinstance(error, str):
            raise TypeError("error must be a string")
        self._error = error
        self._cause = cause
        self._traceback = (
            traceback if traceback is not None else getattr(cause, "__traceback__", None)
        )

    @classmethod
    def from_exception(
        cls,
        error: BaseException,
        traceback: TracebackType | None = None,
    ) -> "Failure[T]":
        message = error.message if isinstance(error, BibleError) else str(error)
        retained = traceback
        if retained is None and isinstance(error, BibleError):
            retained = error.traceback
        if retained is None:
            retained = error.__traceback__
        return cls(message, cause=error, traceback=retained)

    from_object = from_exception

    def __repr__(self) -> str:
        return f"Failure({self._error!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Failure)
            and self._error == other._error
            and self._cause is other._cause
            and self._traceback is other._traceback
        )

    def __hash__(self) -> int:
        return hash((Failure, self._error, id(self._cause), id(self._traceback)))


class ResultException(Exception):
    """Raised when reading :attr:`Result.value` from a failure."""

    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.traceback = traceback
        if cause is not None:
            self.__cause__ = cause

    @property
    def stack_trace(self) -> TracebackType | None:
        return self.traceback

    def __str__(self) -> str:
        return f"ResultException: {self.message}"


__all__ = ["Failure", "Result", "ResultException", "Success"]
