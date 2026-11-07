"""What tokens cost: at API list prices in EUR, and as a share of a Claude subscription.

API prices are USD per million tokens. A cache write costs 1.25x the input price for the 5-minute TTL and
2x for the 1-hour TTL. lineage.toml can override any model and the exchange rate under [prices].

A subscription has no published token allowance, so its monthly budget is calibrated from the account's own
transcripts: the API-equivalent cost of everything the account did (all projects) in the week that ended in a
weekly-limit hit, scaled to a month.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from lineage import settings, transcripts
from lineage.limits import limit_reset
from lineage.transcripts import Usage

WRITE_5M, WRITE_1H = 1.25, 2.0
# USD per million tokens: input, output, cache read.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-opus-4-7": (5.0, 25.0, 0.50),
    "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
USD_EUR = 0.86
DAYS_PER_MONTH = 365.25 / 12


class PriceError(ValueError):
    pass


@dataclass(frozen=True)
class PriceTable:
    models: dict[str, tuple[float, float, float]]
    usd_eur: float

    def price(self, model: str) -> tuple[float, float, float] | None:
        """Exact id first, then the longest known id the model starts with (dated snapshots)."""
        if model in self.models:
            return self.models[model]
        known = [m for m in self.models if model.startswith(m)]
        return self.models[max(known, key=len)] if known else None

    def eur(self, model: str, usage: Usage) -> float:
        if model == transcripts.SYNTHETIC or usage.total == 0:
            return 0.0
        price = self.price(model)
        if price is None:
            raise PriceError(f"no price for model {model}; add it under [prices] in lineage.toml")
        inp, out, read = price
        usd = (
            usage.input * inp
            + usage.output * out
            + usage.cache_read * read
            + usage.cache_write_5m * inp * WRITE_5M
            + usage.cache_write_1h * inp * WRITE_1H
        ) / 1_000_000
        return usd * self.usd_eur


def table(config: settings.Config | None = None) -> PriceTable:
    """[prices] usd_eur = 0.86 and per model a list [input, output, cache_read] in USD per million."""
    config = config or settings.current()
    models = dict(PRICES)
    rate = USD_EUR
    for key, value in config.prices.items():
        if key == "usd_eur":
            rate = float(value)
        else:
            models[key] = tuple(float(v) for v in value)  # type: ignore[assignment]
    return PriceTable(models, rate)


def account_dirs(config: settings.Config | None = None) -> dict[str, Path]:
    config = config or settings.current()
    accounts = config.accounts or {"default": {}}
    return {
        name: Path(values["config_dir"]).expanduser()
        if values.get("config_dir")
        else transcripts.default_config_dir()
        for name, values in accounts.items()
    }


def _number(values: dict[str, str], key: str) -> float | None:
    try:
        return float(values[key])
    except (KeyError, ValueError):
        return None


def subscription_eur(
    account: str, api_eur: float, config: settings.Config | None = None
) -> float | None:
    """The round's share of the account's monthly budget times its monthly price; None without both."""
    values = (config or settings.current()).accounts.get(account, {})
    price, budget = _number(values, "subscription_eur"), _number(values, "monthly_budget_eur")
    if not price or not budget:
        return None
    return api_eur / budget * price


@dataclass(frozen=True)
class Week:
    start: dt.datetime
    hit: dt.datetime
    api_eur: float
    complete: bool = True

    @property
    def monthly(self) -> float:
        """A weekly limit is an allowance per week: used up early, the rest of the week stands still."""
        return self.api_eur * DAYS_PER_MONTH / 7


def calibrate(config_dir: Path, prices: PriceTable) -> list[Week]:
    """Every week that ended in a weekly-limit hit, with what the account used in it at API prices.

    A week that began before the oldest transcript still on disk (Claude Code deletes old ones) is
    incomplete and does not count towards the budget."""
    spent: list[tuple[dt.datetime, float]] = []
    hits: dict[int, dt.datetime] = {}
    for session in transcripts.sessions(config_dir / "projects", config_dir):
        for message in session.messages.values():
            local = message.time.astimezone().replace(tzinfo=None)
            if message.model == transcripts.SYNTHETIC and transcripts.WEEKLY.search(message.text):
                reset = limit_reset(message.text, local)
                # Every session that runs into the limit gets the message; the first one is the hit.
                if reset is not None and (reset not in hits or local < hits[reset]):
                    hits[reset] = local
            else:
                spent.append((local, prices.eur(message.model, message.usage)))
    if not spent:
        return []
    oldest = min(when for when, _ in spent)
    weeks = []
    for reset, hit in sorted(hits.items()):
        start = dt.datetime.fromtimestamp(reset) - dt.timedelta(days=7)
        total = sum(eur for when, eur in spent if start <= when <= hit)
        weeks.append(Week(start, hit, total, complete=start >= oldest))
    return weeks


def monthly_budget(weeks: list[Week]) -> float | None:
    complete = [w.monthly for w in weeks if w.complete]
    return statistics.median(complete) if complete else None


def write_account_values(file: Path, account: str, values: dict[str, str]) -> None:
    """Sets keys in [accounts.<account>] of lineage.toml in place, keeping comments and order."""
    lines = file.read_text(encoding="utf-8").splitlines()
    header = f"[accounts.{account}]"
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == header)
    except StopIteration:
        lines += ["", header]
        start = len(lines) - 1
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines)
    )
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    for key, value in values.items():
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        rendered = f"{key} = {value}"
        at = next((i for i in range(start + 1, end) if pattern.match(lines[i])), None)
        if at is None:
            lines.insert(end, rendered)
            end += 1
        else:
            lines[at] = rendered
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
