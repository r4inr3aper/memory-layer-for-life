"""Scheduling v2

* ``scheduled_tasks``: one-time, monthly, and interval schedules, and weekly schedules on
  several weekdays. ``weekday`` becomes ``weekdays`` (an array; existing rows keep their
  day), alongside ``day_of_month``, ``start_date``, and ``interval_hours``. Check
  constraints keep each frequency's fields present and the others empty. The status
  ``completed`` ends a one-time schedule; ended schedules have no next run.
* ``scheduled_task_runs``: the status ``skipped``, for a slot that was not run because it
  was missed by too much or an earlier run was still going (ADR-043).

Revision ID: 010
Revises: 009
Create Date: 2026-10-24 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# revision identifiers
revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TASKS = "scheduled_tasks"
_RUNS = "scheduled_task_runs"
_WEEKDAYS = "'monday','tuesday','wednesday','thursday','friday','saturday','sunday'"

# Check constraints added by this revision, as (name, expression).
_NEW_TASK_CHECKS = (
    (
        "valid_weekdays",
        "weekdays IS NULL OR (cardinality(weekdays) BETWEEN 1 AND 7 "
        f"AND weekdays <@ ARRAY[{_WEEKDAYS}]::varchar[])",
    ),
    ("weekly_has_weekdays", "(frequency = 'weekly') = (weekdays IS NOT NULL)"),
    ("valid_day_of_month", "day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31"),
    ("monthly_has_day", "(frequency = 'monthly') = (day_of_month IS NOT NULL)"),
    ("dated_has_start_date", "(frequency IN ('once','interval')) = (start_date IS NOT NULL)"),
    ("valid_interval_hours", "interval_hours IS NULL OR interval_hours BETWEEN 1 AND 24"),
    ("interval_has_hours", "(frequency = 'interval') = (interval_hours IS NOT NULL)"),
    ("ended_has_no_next_run", "status NOT IN ('cancelled','completed') OR next_run_at IS NULL"),
    ("only_once_completes", "status <> 'completed' OR frequency = 'once'"),
)


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, expression)


def upgrade() -> None:
    op.add_column(_TASKS, sa.Column("weekdays", ARRAY(sa.String(10)), nullable=True))
    op.add_column(_TASKS, sa.Column("day_of_month", sa.SmallInteger(), nullable=True))
    op.add_column(_TASKS, sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column(_TASKS, sa.Column("interval_hours", sa.SmallInteger(), nullable=True))

    op.execute(
        "UPDATE scheduled_tasks SET weekdays = ARRAY[weekday]::varchar[] WHERE weekday IS NOT NULL"
    )
    # Cancelling already cleared the next run; make sure before the constraint holds it.
    op.execute("UPDATE scheduled_tasks SET next_run_at = NULL WHERE status = 'cancelled'")

    op.drop_constraint(op.f("ck_scheduled_tasks_weekly_has_weekday"), _TASKS, type_="check")
    op.drop_constraint(op.f("ck_scheduled_tasks_valid_weekday"), _TASKS, type_="check")
    op.drop_column(_TASKS, "weekday")

    _replace_check(
        _TASKS, "valid_frequency", "frequency IN ('once','daily','weekly','monthly','interval')"
    )
    _replace_check(_TASKS, "valid_status", "status IN ('active','paused','cancelled','completed')")
    _replace_check(
        _TASKS,
        "valid_last_run_status",
        "last_run_status IS NULL OR last_run_status IN ('succeeded','failed','skipped')",
    )
    for name, expression in _NEW_TASK_CHECKS:
        op.create_check_constraint(op.f(f"ck_{_TASKS}_{name}"), _TASKS, expression)

    _replace_check(_RUNS, "valid_status", "status IN ('running','succeeded','failed','skipped')")


def downgrade() -> None:
    # The old schema cannot hold skipped runs or the new frequencies: they are removed (only
    # one-time schedules complete, so no completed schedule remains). A weekly schedule on
    # several days keeps its first day.
    op.execute("DELETE FROM scheduled_task_runs WHERE status = 'skipped'")
    op.execute(
        "UPDATE scheduled_tasks SET last_run_status = NULL, last_run_error = NULL "
        "WHERE last_run_status = 'skipped'"
    )
    op.execute("DELETE FROM scheduled_tasks WHERE frequency IN ('once','monthly','interval')")

    _replace_check(_RUNS, "valid_status", "status IN ('running','succeeded','failed')")

    for name, _ in reversed(_NEW_TASK_CHECKS):
        op.drop_constraint(op.f(f"ck_{_TASKS}_{name}"), _TASKS, type_="check")
    _replace_check(
        _TASKS,
        "valid_last_run_status",
        "last_run_status IS NULL OR last_run_status IN ('succeeded','failed')",
    )
    _replace_check(_TASKS, "valid_status", "status IN ('active','paused','cancelled')")
    _replace_check(_TASKS, "valid_frequency", "frequency IN ('daily','weekly')")

    op.add_column(_TASKS, sa.Column("weekday", sa.String(10), nullable=True))
    op.execute("UPDATE scheduled_tasks SET weekday = weekdays[1] WHERE weekdays IS NOT NULL")
    op.create_check_constraint(
        op.f("ck_scheduled_tasks_valid_weekday"),
        _TASKS,
        f"weekday IS NULL OR weekday IN ({_WEEKDAYS})",
    )
    op.create_check_constraint(
        op.f("ck_scheduled_tasks_weekly_has_weekday"),
        _TASKS,
        "(frequency = 'weekly') = (weekday IS NOT NULL)",
    )

    op.drop_column(_TASKS, "interval_hours")
    op.drop_column(_TASKS, "start_date")
    op.drop_column(_TASKS, "day_of_month")
    op.drop_column(_TASKS, "weekdays")
