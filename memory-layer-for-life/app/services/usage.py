"""The daily prompt limit per user, and the usage meter the app shows.

A prompt is a chat message the user sends or a scheduled run. Each is counted in
``daily_usage`` for the current UTC day, by the same statement that checks the limit, so
the limit holds under concurrent requests and across every process serving the API. The
count joins the caller's transaction: a message that is not stored is not counted.

The limit is ASSISTANT_DAILY_PROMPT_LIMIT, unless the user has their own
(``app_users.daily_prompt_limit``); 0 means unlimited.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock, utc_now
from app.domain.enums import UsageGranularity
from app.domain.errors import QuotaExceededError
from app.domain.principal import Principal
from app.repositories.usage_repository import UsageRepository

# How many periods a usage history covers, the current one included.
HISTORY_PERIODS: Final = {
    UsageGranularity.DAY: 14,
    UsageGranularity.WEEK: 12,
    UsageGranularity.MONTH: 12,
}


def period_starts(granularity: UsageGranularity, today: date) -> list[date]:
    """The first day of each period in a usage history, oldest first, ending with the
    period ``today`` is in. Weeks start on Monday, as PostgreSQL's ``date_trunc`` has it."""
    count = HISTORY_PERIODS[granularity]
    if granularity is UsageGranularity.DAY:
        return [today - timedelta(days=back) for back in reversed(range(count))]
    if granularity is UsageGranularity.WEEK:
        monday = today - timedelta(days=today.weekday())
        return [monday - timedelta(weeks=back) for back in reversed(range(count))]
    starts = []
    year, month = today.year, today.month
    for _ in range(count):
        starts.append(date(year, month, 1))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(starts))


def day_window(now: datetime) -> tuple[date, datetime]:
    """Today's UTC date, and when the next UTC day starts."""
    today = now.astimezone(UTC).date()
    return today, datetime.combine(today + timedelta(days=1), time(), tzinfo=UTC)


# Converted costs keep this many decimals: fractions of a paisa still add up.
_COST_EXPONENT: Final = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Money:
    """How costs are shown: a currency, and how many units of it one US dollar buys."""

    currency: str
    per_usd: Decimal

    def from_usd(self, usd: Decimal) -> Decimal:
        return (usd * self.per_usd).quantize(_COST_EXPONENT)


@dataclass(frozen=True, slots=True)
class UsageReport:
    day: date
    resets_at: datetime
    prompt_limit: int | None
    chat_messages: int
    scheduled_runs: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal | None
    currency: str
    estimated_cost: Decimal | None

    @property
    def prompts_used(self) -> int:
        return self.chat_messages + self.scheduled_runs

    @property
    def prompts_remaining(self) -> int | None:
        if self.prompt_limit is None:
            return None
        return max(0, self.prompt_limit - self.prompts_used)


@dataclass(frozen=True, slots=True)
class UsagePeriod:
    start: date
    prompts: int
    cost_usd: Decimal
    cost: Decimal
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class UsageHistory:
    granularity: UsageGranularity
    currency: str
    periods: list[UsagePeriod]

    @property
    def total_cost_usd(self) -> Decimal:
        return sum((period.cost_usd for period in self.periods), Decimal(0))

    @property
    def total_cost(self) -> Decimal:
        return sum((period.cost for period in self.periods), Decimal(0))

    @property
    def total_prompts(self) -> int:
        return sum(period.prompts for period in self.periods)


class UsageService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        daily_prompt_limit: int,
        currency: str = "USD",
        currency_per_usd: Decimal = Decimal(1),
        clock: Clock = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._default_limit = daily_prompt_limit
        self._money = Money(currency=currency, per_usd=currency_per_usd)
        self._clock = clock

    async def report(self, principal: Principal) -> UsageReport:
        now = self._clock()
        today, resets_at = day_window(now)
        async with self._session_factory() as session:
            usage = UsageRepository(session)
            counted = await usage.day(principal.id, today)
            limit = self._limit(await usage.prompt_limit_of(principal.id))
            model = await usage.model_usage_since(principal.id, resets_at - timedelta(days=1))
        return UsageReport(
            day=today,
            resets_at=resets_at,
            prompt_limit=limit,
            chat_messages=counted.chat_messages if counted is not None else 0,
            scheduled_runs=counted.scheduled_runs if counted is not None else 0,
            input_tokens=model.input_tokens,
            output_tokens=model.output_tokens,
            estimated_cost_usd=model.estimated_cost_usd,
            currency=self._money.currency,
            estimated_cost=(
                self._money.from_usd(model.estimated_cost_usd)
                if model.estimated_cost_usd is not None
                else None
            ),
        )

    async def history(self, principal: Principal, granularity: UsageGranularity) -> UsageHistory:
        """Prompts and model cost per day, week, or month, for the usage chart."""
        today, _ = day_window(self._clock())
        starts = period_starts(granularity, today)
        async with self._session_factory() as session:
            usage = UsageRepository(session)
            prompts = await usage.prompts_by_period(principal.id, granularity, starts[0])
            model = await usage.model_usage_by_period(principal.id, granularity, starts[0])
        periods = []
        for start in starts:
            calls = model.get(start)
            cost_usd = (calls.estimated_cost_usd if calls else None) or Decimal(0)
            periods.append(
                UsagePeriod(
                    start=start,
                    prompts=prompts.get(start, 0),
                    cost_usd=cost_usd,
                    cost=self._money.from_usd(cost_usd),
                    input_tokens=calls.input_tokens if calls else 0,
                    output_tokens=calls.output_tokens if calls else 0,
                )
            )
        return UsageHistory(granularity=granularity, currency=self._money.currency, periods=periods)

    async def count_chat_message(
        self, session: AsyncSession, user_id: uuid.UUID, *, timezone_name: str
    ) -> None:
        """Count a chat message against today's prompts, in the caller's transaction.

        Raises ``QuotaExceededError`` when none are left; ``timezone_name`` is the user's,
        for saying when more are available.
        """
        usage = UsageRepository(session)
        await self._count(usage, user_id, usage.count_chat_message, timezone_name)

    async def count_scheduled_run(
        self, session: AsyncSession, user_id: uuid.UUID, *, timezone_name: str
    ) -> None:
        """Count a scheduled run against today's prompts; see ``count_chat_message``."""
        usage = UsageRepository(session)
        await self._count(usage, user_id, usage.count_scheduled_run, timezone_name)

    async def _count(
        self,
        usage: UsageRepository,
        user_id: uuid.UUID,
        add: Callable[..., Awaitable[bool]],
        timezone_name: str,
    ) -> None:
        now = self._clock()
        today, resets_at = day_window(now)
        limit = self._limit(await usage.prompt_limit_of(user_id))
        if not await add(user_id, today, limit=limit, now=now):
            raise QuotaExceededError(_limit_reached(limit, resets_at, timezone_name))

    def _limit(self, own: int | None) -> int | None:
        limit = self._default_limit if own is None else own
        return limit or None


def _limit_reached(limit: int | None, resets_at: datetime, timezone_name: str) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    local = resets_at.astimezone(zone)
    return (
        f"You have used today's {limit} prompts. More are available after "
        f"{local:%H:%M} ({zone.key})."
    )
