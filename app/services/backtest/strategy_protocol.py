"""Versioned Backtest Strategy interface (AD-20).

Defines ``StrategyProtocolV1`` -- the typed, bounded seam a Strategy author
writes against -- plus the immutable ``Signal``/``PortfolioView`` value
objects and the pure result validators a future engine (Story 2.4) calls
before it changes any cash, position, ledger, staging, or run state.

Scope boundary: this module owns only the minimum typing surface Stories
2.2-2.4 build on. It does not define the concrete pandas-backed
``MarketView`` (Story 2.3), ``SKILL.md`` frontmatter discovery or a shared
parameter validator (Story 2.2), or any engine invocation order/state
mutation (Story 2.4). No type here accepts or returns a database
connection, repository, ORM/session, job, run, or persistence model, and
none of them may be imported anywhere near a Strategy runtime module --
that boundary is mechanically enforced by
``tests/backtest/test_strategy_runtime_import_boundary.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StrategyProtocolErrorCode(StrEnum):
    """Stable, machine-readable Strategy protocol validation failure codes."""

    INVALID_SIGNAL_CONTAINER = "invalid_signal_container"
    INVALID_SIGNAL_ELEMENT = "invalid_signal_element"
    INVALID_POSITION_SIZE_TYPE = "invalid_position_size_type"
    NEGATIVE_POSITION_SIZE = "negative_position_size"
    FUTURE_DATED_OBSERVATION = "future_dated_observation"
    DUPLICATE_POSITION = "duplicate_position"
    DUPLICATE_VOLATILITY_OBSERVATION = "duplicate_volatility_observation"


class StrategyProtocolError(Exception):
    """One typed protocol exception with a stable, inspectable ``.code``.

    Deliberately not a ``ValueError``/``TypeError``/``AssertionError``
    subclass: pydantic only wraps those three exception types into an
    opaque ``ValidationError`` when raised from inside a validator, which
    would discard ``.code``. A plain ``Exception`` subclass instead
    propagates unmodified from both ``PortfolioView`` construction and the
    pure ``validate_*`` functions below, so callers can always do
    ``except StrategyProtocolError as exc: exc.code``.
    """

    def __init__(self, code: StrategyProtocolErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class _StrategyModel(BaseModel):
    """Frozen, strict, extra-forbidding base for every Story 2.1 value object.

    Mirrors ``historical_scan_record.CanonicalModel``'s immutability
    convention (``extra="forbid"``, ``frozen=True``, ``strict=True``,
    ``allow_inf_nan=False``) without importing that module's detector/BAU
    -envelope domain into the Strategy runtime's approved import graph.
    """

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, allow_inf_nan=False
    )


class SignalSide(StrEnum):
    """The two-sided trading action a ``Signal`` requests (AD-20)."""

    BUY = "BUY"
    SELL = "SELL"


#: SELL executes before BUY for the same session/security -- AD-20's
#: execution convention, consumed directly by ``Signal.sort_key``.
_SIDE_EXECUTION_RANK: dict[SignalSide, int] = {
    SignalSide.SELL: 0,
    SignalSide.BUY: 1,
}


class Signal(_StrategyModel):
    """One immutable, deterministically ordered trading instruction.

    AD-20 fixes the shape a future engine acts on: a stable security ID, a
    ``BUY``/``SELL`` side, the session the Strategy raised it on, and a
    non-empty rule ID it can be traced back to. ``sort_key`` is a pure
    function of these fields alone -- never insertion order, hash
    iteration, object identity, or locale -- so validating the same
    signals twice, in any input order, always yields one canonical order.
    """

    security_id: str = Field(min_length=1)
    side: SignalSide
    session: date
    rule_id: str = Field(min_length=1)

    @property
    def sort_key(self) -> tuple[date, str, int, str]:
        """Deterministic ``(session, security_id, side_rank, rule_id)`` key."""
        return (
            self.session,
            self.security_id,
            _SIDE_EXECUTION_RANK[self.side],
            self.rule_id,
        )


class PositionSummaryV1(_StrategyModel):
    """A read-only simulated position summary bounded to one security.

    ``quantity``/``average_cost`` inherit ``_StrategyModel``'s
    ``allow_inf_nan=False`` config, so a ``NaN``/``Infinity`` value is
    already rejected at construction without a dedicated field validator.
    """

    security_id: str = Field(min_length=1)
    quantity: Decimal = Field(ge=Decimal(0))
    average_cost: Decimal = Field(gt=Decimal(0))


class VolatilityObservationV1(_StrategyModel):
    """A read-only historical-volatility fact bounded to one session.

    ``value`` inherits the same ``allow_inf_nan=False`` finite-value
    guarantee as :class:`PositionSummaryV1`.
    """

    security_id: str = Field(min_length=1)
    session: date
    value: Decimal


def _as_detached_tuple(value: object) -> tuple[object, ...]:
    """Copy a caller-supplied list/tuple so later caller mutation can't
    reach the value being validated into a ``PortfolioView`` field."""
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    raise TypeError(f"expected a list or tuple, got {type(value).__name__}")


class PortfolioView(_StrategyModel):
    """Read-only simulated portfolio state bounded to one session.

    Exposes only simulated cash, immutable position summaries, and
    historical-volatility observations already authorized as of
    ``as_of_session`` -- never a live SIPP/ISA identifier, repository
    handle, or mutation method (``extra="forbid"`` rejects any other
    field outright). List/tuple inputs are copied before element
    validation and every position/volatility item is itself frozen, so
    mutating a caller-supplied collection -- or a value this view returns
    -- after construction cannot affect the view.
    """

    as_of_session: date
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    cash: Decimal = Field(ge=Decimal(0))
    positions: tuple[PositionSummaryV1, ...]
    volatility_observations: tuple[VolatilityObservationV1, ...]

    @field_validator("positions", "volatility_observations", mode="before")
    @classmethod
    def _detach_collection(cls, value: object) -> tuple[object, ...]:
        return _as_detached_tuple(value)

    @model_validator(mode="after")
    def _no_future_dated_observations(self) -> "PortfolioView":
        for observation in self.volatility_observations:
            if observation.session > self.as_of_session:
                raise StrategyProtocolError(
                    StrategyProtocolErrorCode.FUTURE_DATED_OBSERVATION,
                    f"volatility observation for {observation.security_id!r} "
                    f"on {observation.session.isoformat()} is after "
                    f"as_of_session {self.as_of_session.isoformat()}",
                )
        return self

    @model_validator(mode="after")
    def _no_duplicate_positions(self) -> "PortfolioView":
        security_ids = [position.security_id for position in self.positions]
        if len(set(security_ids)) != len(security_ids):
            raise StrategyProtocolError(
                StrategyProtocolErrorCode.DUPLICATE_POSITION,
                "positions must contain at most one entry per security_id",
            )
        return self

    @model_validator(mode="after")
    def _no_duplicate_volatility_observations(self) -> "PortfolioView":
        keys = [
            (observation.security_id, observation.session)
            for observation in self.volatility_observations
        ]
        if len(set(keys)) != len(keys):
            raise StrategyProtocolError(
                StrategyProtocolErrorCode.DUPLICATE_VOLATILITY_OBSERVATION,
                "volatility_observations must contain at most one entry per "
                "(security_id, session) pair",
            )
        return self


# ---------------------------------------------------------------------------
# Parameter and market-view typing seam
# ---------------------------------------------------------------------------

#: A JSON-compatible parameter value a Strategy may receive. Story 2.2 owns
#: schema discovery and required/type/min/max/enum validation; this alias
#: only fixes the shape of the read-only mapping ``StrategyProtocolV1``
#: methods are passed.
JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | Mapping[str, "JsonValue"]
StrategyParameters = Mapping[str, JsonValue]


@runtime_checkable
class MarketViewV1(Protocol):
    """Minimal bounded market-view typing seam a Strategy method receives.

    Story 2.3 owns the concrete pandas-backed implementation, snapshot/
    evidence binding, and no-look-ahead cache access; this protocol only
    fixes the one fact every bounded view (market or portfolio) must
    expose, so ``StrategyProtocolV1`` can be typed and tested well before
    that implementation exists.
    """

    @property
    def as_of_session(self) -> date: ...


# ---------------------------------------------------------------------------
# The versioned Strategy protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class StrategyProtocolV1(Protocol):
    """The versioned seam a Backtest Strategy implements (AD-20).

    No method accepts or returns a database connection, repository,
    ORM/session, job, run, or persistence model -- only the bounded,
    immutable views and JSON-compatible parameters defined in this
    module. ``typing.Protocol`` only checks attribute/method presence at
    runtime, not full call signatures (Python 3.12 ``typing`` docs), so a
    future engine must still pair an ``isinstance`` conformance check with
    the explicit ``validate_*`` functions below before it acts on a
    Strategy's output. This is a bounded-interface guard, not a sandbox:
    first-party in-process Strategy code is trusted and code-reviewed.
    """

    def entry_signals(
        self, view: MarketViewV1, parameters: StrategyParameters
    ) -> list[Signal]:
        """Return candidate entry signals for ``view``'s session."""
        ...

    def exit_signals(
        self,
        view: MarketViewV1,
        portfolio: PortfolioView,
        parameters: StrategyParameters,
    ) -> list[Signal]:
        """Return candidate exit signals given the simulated ``portfolio``."""
        ...

    def position_size(
        self,
        signal: Signal,
        view: MarketViewV1,
        portfolio: PortfolioView,
        parameters: StrategyParameters,
    ) -> int:
        """Return the integer share count to act on ``signal`` with."""
        ...


# ---------------------------------------------------------------------------
# Pure result validators
# ---------------------------------------------------------------------------


def _validate_signal_list(value: object, *, method_name: str) -> tuple[Signal, ...]:
    if not isinstance(value, list):
        raise StrategyProtocolError(
            StrategyProtocolErrorCode.INVALID_SIGNAL_CONTAINER,
            f"{method_name} must return a list, got {type(value).__name__}",
        )
    for index, item in enumerate(value):
        if not isinstance(item, Signal):
            raise StrategyProtocolError(
                StrategyProtocolErrorCode.INVALID_SIGNAL_ELEMENT,
                f"{method_name}[{index}] must be a Signal, got {type(item).__name__}",
            )
    return tuple(sorted(value, key=lambda signal: signal.sort_key))


def validate_entry_signals(value: object) -> tuple[Signal, ...]:
    """Validate an ``entry_signals`` result before any engine mutation.

    Pure and side-effect-free: rejects a non-``list`` container or any
    non-``Signal`` element with a stable error code, then returns the
    signals in their one canonical ``sort_key`` order -- deterministic
    regardless of the order the Strategy returned them in.
    """
    return _validate_signal_list(value, method_name="entry_signals")


def validate_exit_signals(value: object) -> tuple[Signal, ...]:
    """Validate an ``exit_signals`` result before any engine mutation.

    Same contract as :func:`validate_entry_signals`.
    """
    return _validate_signal_list(value, method_name="exit_signals")


def validate_position_size(value: object) -> int:
    """Validate a ``position_size`` result before any engine mutation.

    Rejects ``bool`` (a ``bool`` is an ``int`` subclass in Python and
    would otherwise silently pass an ``int`` check), any other
    non-``int``/non-integral value, and negative sizes, each with a
    stable error code.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise StrategyProtocolError(
            StrategyProtocolErrorCode.INVALID_POSITION_SIZE_TYPE,
            f"position_size must return a plain int, got {type(value).__name__}",
        )
    if value < 0:
        raise StrategyProtocolError(
            StrategyProtocolErrorCode.NEGATIVE_POSITION_SIZE,
            f"position_size cannot be negative: {value}",
        )
    return value


__all__ = [
    "JsonScalar",
    "JsonValue",
    "MarketViewV1",
    "PortfolioView",
    "PositionSummaryV1",
    "Signal",
    "SignalSide",
    "StrategyParameters",
    "StrategyProtocolError",
    "StrategyProtocolErrorCode",
    "StrategyProtocolV1",
    "VolatilityObservationV1",
    "validate_entry_signals",
    "validate_exit_signals",
    "validate_position_size",
]
