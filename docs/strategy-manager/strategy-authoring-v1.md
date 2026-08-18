# Authoring a Backtest Strategy against `StrategyProtocolV1`

This document defines the v1 convention for writing a Backtest Strategy: the
layout a Strategy lives in, the interface it implements, how it constructs
signals and reads bounded market/portfolio state, how its source identity is
versioned, and how to run its contract tests.

It covers **Story 2.1's** scope only: the typed protocol, the immutable
`Signal`/`PortfolioView` value objects, pure result validation, and the
mechanically enforced safety boundary. It does not cover Skill discovery
(Story 2.2), the concrete pandas-backed `MarketView` (Story 2.3), or engine
invocation/mutation (Story 2.4) -- those extend this contract without
changing it.

## Layout

A real Strategy lives under `skills/<strategy-name>/`, mirroring every other
Skill in this repository:

```
skills/<strategy-name>/
  SKILL.md              # frontmatter + description (Story 2.2 discovers this)
  scripts/
    strategy.py          # StrategyProtocolV1 implementation (this story)
    tests/
      conftest.py         # adds ../ (scripts/) to sys.path
      test_contract.py     # protocol conformance + determinism tests
```

`tests/fixtures/backtest-strategies/minimal-strategy/` is a worked example of
this exact layout, used only by the repository's own test suite -- it is
**not** discoverable as a live Skill and must never be treated as a real
trading rule. Never repurpose an existing live-trading Skill (one that
places orders or touches `TraderAgent`) as a Backtest Strategy; author a new
one against this protocol instead.

## The protocol

Import everything from `app.services.backtest.strategy_protocol`:

```python
from app.services.backtest.strategy_protocol import (
    MarketViewV1,
    PortfolioView,
    Signal,
    SignalSide,
    StrategyParameters,
    StrategyProtocolV1,
)
```

A Strategy is any object implementing three methods:

```python
class MyStrategy:
    def entry_signals(
        self, view: MarketViewV1, parameters: StrategyParameters
    ) -> list[Signal]:
        ...

    def exit_signals(
        self,
        view: MarketViewV1,
        portfolio: PortfolioView,
        parameters: StrategyParameters,
    ) -> list[Signal]:
        ...

    def position_size(
        self,
        signal: Signal,
        view: MarketViewV1,
        portfolio: PortfolioView,
        parameters: StrategyParameters,
    ) -> int:
        ...
```

`StrategyProtocolV1` is `@runtime_checkable`, so `isinstance(strategy,
StrategyProtocolV1)` works for a cheap conformance smoke check -- but
`typing.Protocol` only checks that these three methods exist, not their full
signatures or return types at runtime. Always pair it with the explicit
`validate_*` functions below and with static Pyrefly checking; do not rely on
`isinstance` alone.

No method may accept or return a database connection, repository,
ORM/session, job, run, or persistence model. Only the bounded views and
JSON-compatible `parameters` mapping defined in `strategy_protocol.py` may
cross this boundary.

### `MarketViewV1`

Story 2.1 defines only the minimal typing seam every bounded view must
expose -- a single `as_of_session: date` property. Story 2.3 owns the
concrete pandas-backed `MarketView` (snapshot binding, no-look-ahead cache
access); write and test your Strategy against this minimal seam today, and
it will keep working unchanged once the concrete implementation lands.

### `PortfolioView`

An immutable, read-only snapshot of simulated portfolio state bounded to one
`as_of_session`:

```python
from decimal import Decimal
from app.services.backtest.strategy_protocol import (
    PortfolioView,
    PositionSummaryV1,
    VolatilityObservationV1,
)

view = PortfolioView(
    as_of_session=date(2026, 6, 1),
    base_currency="GBP",
    cash=Decimal("10000"),
    positions=(
        PositionSummaryV1(
            security_id="sec-aapl",
            quantity=Decimal("10"),
            average_cost=Decimal("150.00"),
        ),
    ),
    volatility_observations=(
        VolatilityObservationV1(
            security_id="sec-aapl", session=date(2026, 6, 1), value=Decimal("0.22")
        ),
    ),
)
```

- It exposes only simulated `cash`, immutable `positions`, and
  `volatility_observations` already authorized as of `as_of_session` -- never
  a live SIPP/ISA account identifier.
- Construction rejects any `volatility_observations` entry dated **after**
  `as_of_session` (`StrategyProtocolError` with code
  `future_dated_observation`) and any non-finite `cash`/`quantity`/
  `average_cost`/`value` (`NaN`/`Infinity`, rejected by pydantic's own
  `allow_inf_nan=False` config).
- Passing a `list` for `positions`/`volatility_observations` is fine -- it is
  copied into a tuple before validation, and every item is itself a frozen
  model, so mutating your original list (or dict) after construction can
  never change the view. There is no mutation method.

### `Signal`

```python
from app.services.backtest.strategy_protocol import Signal, SignalSide

signal = Signal(
    security_id="sec-aapl",
    side=SignalSide.BUY,
    session=view.as_of_session,
    rule_id="breakout_pivot_v1",
)
```

Every `Signal` is frozen and carries a `sort_key` property -- a pure
function of `(session, security_id, side, rule_id)` alone, with SELL ranked
before BUY for the same session/security. Return signals in whatever order
is convenient; the validators below always produce one canonical order.

### `parameters`

`parameters: StrategyParameters` is a read-only, JSON-compatible mapping
(`str | int | float | bool | None`, plus nested tuples/mappings of the
same). Story 2.2 owns parameter schema discovery and the shared
required/type/min/max/enum validator -- this story does not duplicate that;
a Strategy simply reads whatever keys its `SKILL.md` documents.

## Validating results

Before any future engine state mutation, validate every method result with
the matching pure validator:

```python
from app.services.backtest.strategy_protocol import (
    StrategyProtocolError,
    validate_entry_signals,
    validate_exit_signals,
    validate_position_size,
)

try:
    entries = validate_entry_signals(strategy.entry_signals(view, parameters))
    size = validate_position_size(
        strategy.position_size(entries[0], view, portfolio, parameters)
    )
except StrategyProtocolError as exc:
    # exc.code is a stable, machine-readable StrategyProtocolErrorCode
    ...
```

- `validate_entry_signals`/`validate_exit_signals` reject a non-`list`
  return (`invalid_signal_container`) or any non-`Signal` element
  (`invalid_signal_element`), then return the signals sorted by `sort_key`.
- `validate_position_size` rejects `bool` and any non-`int` value
  (`invalid_position_size_type` -- note a `bool` is an `int` subclass in
  Python, so it is checked explicitly) and negative sizes
  (`negative_position_size`).

All validators are pure and side-effect-free: they never touch cash,
positions, the ledger, staging, or run state themselves -- that is Story
2.4's job, once these checks pass.

## Source identity and versioning

A Strategy's version is a canonical source-identity manifest, built the same
way as every detector and the yfinance ingestion path -- through
`build_source_manifest`, never a second canonicalizer:

```python
from pathlib import Path
from app.services.backtest.source_manifest import build_strategy_source_manifest

manifest = build_strategy_source_manifest(
    project_root=Path(__file__).resolve().parents[3],
    strategy_id="breakout_pivot_v1",
    api_version=1,
    allowlist=("skills/breakout-pivot/scripts/strategy.py",),
    defaults={"pivot_lookback_sessions": 20},
    python_runtime="3.14",
    dependency_versions={"pydantic": "2.13.4"},
)
```

- `allowlist` is one explicit, closed list of POSIX-relative runtime source
  paths (sorted, UTF-8, newline-normalized). Only list files your Strategy
  actually imports at runtime -- never `scripts/tests/`, `__pycache__`,
  bytecode, logs, reports, or generated output; those are rejected outright.
- `api_version` is a plain positive integer, represented canonically as its
  decimal string in the manifest.
- The resulting digest changes when runtime source or `defaults`/config
  changes materially, and is unchanged by newline-style-only edits or by
  anything outside the allowlist.

## Running contract tests

Every Strategy should have a `scripts/tests/` suite proving protocol
conformance, deterministic output, parameter pass-through, bounded inputs,
and immutable portfolio data -- the same shape as
`tests/fixtures/backtest-strategies/minimal-strategy/scripts/tests/`. Run a
Strategy's own contract tests directly:

```bash
uv run pytest skills/<strategy-name>/scripts/tests -q
```

For the repository's fixture Strategy:

```bash
uv run pytest tests/fixtures/backtest-strategies/minimal-strategy/scripts/tests -q
```

Strategy functions always run in-process, called directly as Python
methods. Never invoke a Strategy's script through a per-signal, per-ticker,
or per-session subprocess call.

## The safety boundary (AD-10)

A Strategy runtime module may only import:

- `app.services.backtest.strategy_protocol` (this module),
- dependency-free `app.core` utilities (e.g. `app.core.stage_classification`,
  which has no imports beyond `decimal`/`typing`),
- the standard library, and
- explicitly approved calculation modules for its own pattern logic.

It must never import -- directly, aliased, via `from ... import ...`, or
transitively through any other first-party module -- `TraderAgent`,
anything under `app.agents`, live portfolio/trade/cash/position
repositories or the `Connect`/DB-session factory under `app.repositories`,
or any order-submission path. This is enforced mechanically, not just by
convention: `tests/backtest/test_strategy_runtime_import_boundary.py`
statically parses a Strategy module's import graph (AST only -- nothing is
ever executed) and follows every local `app.*` import it finds, failing with
a diagnostic naming both the offending module and the forbidden dependency
it reached, however many hops away.

**This is a bounded-interface guard, not a Python sandbox.** First-party
in-process Strategy code is trusted and code-reviewed like any other module
in this repository; nothing here provides process isolation, resource
limits, or protection against arbitrary Python execution. Untrusted
third-party Skills remain explicitly out of scope for this protocol.
