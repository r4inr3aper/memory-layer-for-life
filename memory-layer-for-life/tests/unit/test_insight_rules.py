"""What insights the memories support, grounded in them, and the Monday line of the brief."""

import uuid
from datetime import UTC, date, datetime, timedelta

from app.domain.enums import InsightKind, InsightTarget
from app.domain.insights import (
    Closure,
    InsightInputs,
    Mention,
    MoneyNote,
    OpenGoal,
    compute_insights,
    follow_through_insight,
    money_insights,
    people_insights,
    streak,
    theme_insights,
)
from app.domain.life_state import BriefInputs, compose_brief

TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def note(
    amount: float, day: date, category: str | None = None, currency: str | None = "INR"
) -> MoneyNote:
    return MoneyNote(
        memory_id=uuid.uuid4(), happened_on=day, amount=amount, currency=currency, category=category
    )


def mention(entity: uuid.UUID, name: str, days_ago: int, entity_type: str = "person") -> Mention:
    return Mention(
        memory_id=uuid.uuid4(),
        entity_id=entity,
        entity_name=name,
        entity_type=entity_type,
        happened_at=NOW - timedelta(days=days_ago),
    )


# --- Money -----------------------------------------------------------------------------


def test_money_noted_this_month_is_summed_by_category_and_compared() -> None:
    notes = [
        note(400, date(2026, 10, 2), "food"),
        note(600, date(2026, 10, 20), "fuel"),
        note(250, date(2026, 10, 21), "food"),
        note(1000, date(2026, 9, 15), "food"),
        note(9999, date(2026, 8, 1), "rent"),
    ]

    [insight] = money_insights(notes, TODAY)

    assert insight.kind is InsightKind.MONEY
    assert insight.key == "money:2026-10:INR"
    assert insight.title == "INR 1,250 noted this month"
    assert insight.body == (
        "3 money notes this month: food INR 650, fuel INR 600. Last month: INR 1,000 (+25%)."
    )
    assert set(insight.memory_ids) == {n.memory_id for n in notes[:3]}


def test_each_currency_gets_its_own_insight() -> None:
    insights = money_insights(
        [note(10, TODAY, currency="USD"), note(500, TODAY, currency=None)], TODAY
    )

    assert sorted(insight.key for insight in insights) == [
        "money:2026-10:USD",
        "money:2026-10:none",
    ]


# --- People ----------------------------------------------------------------------------


def test_the_people_mentioned_most_lately_are_on_the_user_s_mind() -> None:
    priya, raju = uuid.uuid4(), uuid.uuid4()
    mentions = [
        mention(priya, "Priya", 1),
        mention(priya, "Priya", 3),
        mention(priya, "Priya", 9),
        mention(raju, "Raju", 2),
        mention(raju, "Raju", 5),
        mention(uuid.uuid4(), "Sam", 4),
    ]

    [top] = people_insights(mentions, NOW, TODAY)

    assert top.kind is InsightKind.PEOPLE_TOP
    assert top.title == "On your mind: Priya"
    assert top.body == "Mentioned most in the last 30 days: Priya (3), Raju (2)."
    assert (top.target, top.target_id) == (InsightTarget.PERSON, priya)


def test_someone_mentioned_often_who_went_quiet_is_noticed() -> None:
    mum = uuid.uuid4()
    once = uuid.uuid4()
    mentions = [
        mention(mum, "Mum", 50),
        mention(mum, "Mum", 60),
        mention(mum, "Mum", 70),
        mention(once, "Old friend", 90),
    ]

    [quiet] = people_insights(mentions, NOW, TODAY)

    assert quiet.kind is InsightKind.PEOPLE_QUIET
    assert quiet.title == "You haven't mentioned Mum in 7 weeks"
    assert quiet.key == f"people.quiet:{mum}:2026-10"


# --- Follow-through and goals ----------------------------------------------------------


def test_follow_through_needs_enough_items_and_counts_a_streak() -> None:
    def closure(days_ago: int, done: bool = True) -> Closure:
        return Closure(
            memory_id=uuid.uuid4(), closed_on=TODAY - timedelta(days=days_ago), done=done
        )

    closures = [closure(0), closure(1), closure(2), closure(5, done=False), closure(40)]
    overdue = [uuid.uuid4()]

    insight = follow_through_insight(closures, overdue, TODAY)

    assert insight is not None
    assert insight.title == "You finish 60% of what you plan"
    assert insight.body == (
        "In the last 30 days: 3 done, 1 dropped, 1 overdue. "
        "You've finished something 3 days in a row."
    )
    assert insight.target is InsightTarget.TODO
    assert follow_through_insight(closures[:2], [], TODAY) is None
    assert streak([closure(1), closure(2)], TODAY) == 2
    assert streak([closure(3)], TODAY) == 0


def test_a_goal_untouched_for_a_month_is_quiet() -> None:
    old = OpenGoal(
        memory_id=uuid.uuid4(), content="Run a marathon", last_activity=NOW - timedelta(days=36)
    )
    fresh = OpenGoal(
        memory_id=uuid.uuid4(), content="Learn Spanish", last_activity=NOW - timedelta(days=3)
    )

    insights = compute_insights(InsightInputs(today=TODAY, now=NOW, goals=[old, fresh]))

    [quiet] = insights
    assert quiet.kind is InsightKind.GOAL_QUIET
    assert quiet.title == "“Run a marathon” has been quiet for 5 weeks"
    assert quiet.target_id == old.memory_id


def test_a_topic_mentioned_often_this_week_is_a_theme() -> None:
    work = uuid.uuid4()
    mentions = [mention(work, "Work", days, "topic") for days in (0, 2, 4)]
    mentions.append(mention(work, "Work", 20, "topic"))

    [theme] = theme_insights(mentions, NOW, TODAY)

    assert theme.title == "Work keeps coming up"
    assert theme.body == "Mentioned in 3 memories this week."
    assert theme_insights(mentions[:2], NOW, TODAY) == []


# --- Together --------------------------------------------------------------------------


def test_insights_marked_not_useful_are_left_out_and_the_rest_are_ordered() -> None:
    goal = OpenGoal(
        memory_id=uuid.uuid4(), content="Write a book", last_activity=NOW - timedelta(days=60)
    )
    inputs = InsightInputs(today=TODAY, now=NOW, money=[note(300, TODAY, "food")], goals=[goal])

    shown = compute_insights(inputs)
    hidden = compute_insights(
        InsightInputs(
            today=TODAY,
            now=NOW,
            money=inputs.money,
            goals=inputs.goals,
            hidden=frozenset({"money:2026-10:INR"}),
        )
    )

    assert [insight.kind for insight in shown] == [InsightKind.MONEY, InsightKind.GOAL_QUIET]
    assert [insight.kind for insight in hidden] == [InsightKind.GOAL_QUIET]


def test_nothing_to_show_is_an_empty_list() -> None:
    assert compute_insights(InsightInputs(today=TODAY, now=NOW)) == []


def test_the_monday_brief_counts_last_week() -> None:
    brief = compose_brief(BriefInputs(today=date(2026, 10, 26), user_name=None, last_week_done=4))

    assert "Last week you finished 4 things on your list." in brief.text
    assert not brief.nothing_to_say
