"""Between the memory management services and their HTTP shapes."""

from app.api.v1.mappers import to_memory_response
from app.schemas.memory import MemoryEntityResponse
from app.schemas.my_memories import (
    HeldBackMessageResponse,
    HeldBackResponse,
    MemoryEventResponse,
    MemoryVersionResponse,
    MyMemoryDetailResponse,
    MyMemorySourceResponse,
    PersonDetailResponse,
    PersonResponse,
    ReviewInboxResponse,
    SuggestionResponse,
)
from app.services.memories import MyMemoryDetail
from app.services.memory_review import ReviewInbox
from app.services.people import PersonDetail, PersonView


def to_my_memory_detail_response(found: MyMemoryDetail) -> MyMemoryDetailResponse:
    detail = found.detail
    return MyMemoryDetailResponse(
        **to_memory_response(detail.memory).model_dump(),
        sources=[
            MyMemorySourceResponse(
                raw_message_id=source.raw_message_id,
                source_role=source.source_role,
                evidence_text=source.evidence_text,
                source=source.source,
                sent_at=source.source_created_at,
                content=source.content,
                thread_id=source.thread_id,
            )
            for source in detail.sources
        ],
        entities=[MemoryEntityResponse.model_validate(entity) for entity in detail.entities],
        history=[MemoryEventResponse.model_validate(event) for event in found.history],
        replaced=[MemoryVersionResponse.model_validate(old) for old in found.replaced],
        replaced_by_id=found.replaced_by_id,
    )


def to_review_inbox_response(inbox: ReviewInbox) -> ReviewInboxResponse:
    return ReviewInboxResponse(
        proposed_count=inbox.proposed_count,
        suggestions=[
            SuggestionResponse(
                kind=suggestion.kind,
                first=to_memory_response(suggestion.first),
                second=to_memory_response(suggestion.second),
                similarity=suggestion.similarity,
                shared_entities=suggestion.shared_entities,
            )
            for suggestion in inbox.suggestions
        ],
        held_back=[
            HeldBackResponse(
                run_id=held.run_id,
                held_at=held.held_at,
                reason="unclear" if held.unclear else "unreadable",
                messages=[
                    HeldBackMessageResponse.model_validate(message) for message in held.messages
                ],
            )
            for held in inbox.held_back
        ],
        held_back_count=inbox.held_back_count,
    )


def to_person_response(person: PersonView) -> PersonResponse:
    return PersonResponse.model_validate(person)


def to_person_detail_response(found: PersonDetail) -> PersonDetailResponse:
    return PersonDetailResponse(
        **to_person_response(found.person).model_dump(),
        aliases=list(found.aliases),
        memories=[to_memory_response(memory) for memory in found.memories],
    )
