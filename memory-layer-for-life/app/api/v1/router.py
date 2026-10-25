from fastapi import APIRouter, Depends

from app.api.dependencies import require_operator
from app.api.v1.endpoints import (
    activity,
    console,
    evaluations,
    feedback,
    health,
    ingestion,
    insights,
    life,
    llm_calls,
    me,
    memories,
    my_memories,
    people,
    playground,
    processing,
    reports,
    schedules,
    sources,
    threads,
    tools,
)

v1_router = APIRouter()
v1_router.include_router(health.router, prefix="/health", tags=["health"])

# The memory layer and its console, for the operator. No user sign-in (ADR-022): they
# answer only the computer running the API, or a request with the operator key.
_operator = [Depends(require_operator)]
for router, prefix, tag in (
    (ingestion.router, "/ingestion", "ingestion"),
    (processing.router, "/processing", "processing"),
    (memories.router, "/memories", "memories"),
    (console.router, "/console", "console"),
    (llm_calls.router, "/llm-calls", "model calls"),
    (playground.router, "/playground", "playground"),
    (evaluations.router, "/evaluations", "evaluations"),
    (reports.router, "/reports", "reports"),
):
    v1_router.include_router(router, prefix=prefix, tags=[tag], dependencies=_operator)

# The assistant app. Every route below acts for a signed-in user.
v1_router.include_router(me.router, prefix="/me", tags=["user"])
v1_router.include_router(my_memories.router, prefix="/me/memories", tags=["memories (app)"])
v1_router.include_router(people.router, prefix="/me/people", tags=["memories (app)"])
v1_router.include_router(life.router, prefix="/me", tags=["life"])
v1_router.include_router(insights.router, prefix="/me/insights", tags=["life"])
v1_router.include_router(sources.router, prefix="/me", tags=["memory sources"])
v1_router.include_router(threads.router, prefix="/threads", tags=["chat"])
v1_router.include_router(schedules.router, prefix="/schedules", tags=["schedules"])
v1_router.include_router(tools.router, prefix="/tools", tags=["apps"])
v1_router.include_router(activity.router, prefix="/activity", tags=["schedules"])
v1_router.include_router(feedback.router, prefix="/feedback", tags=["user"])
