"""SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from app.models.app_user import AppUser
from app.models.chat_import import ChatImport
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread
from app.models.daily_usage import DailyUsage
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_file import DocumentFile
from app.models.entity import Entity
from app.models.entity_mention import EntityMention
from app.models.evaluation import EvaluationCaseResult, EvaluationRun
from app.models.extraction_result import ExtractionResult
from app.models.feedback import Feedback
from app.models.insight_feedback import InsightFeedback
from app.models.llm_call import LlmCall
from app.models.memory import Memory
from app.models.memory_embedding import MemoryEmbedding
from app.models.memory_entity import MemoryEntity
from app.models.memory_event import MemoryEvent
from app.models.memory_relation import MemoryRelation
from app.models.memory_source import MemorySource
from app.models.playground_run import PlaygroundRun
from app.models.processing_run import ProcessingRun
from app.models.processing_run_event import ProcessingRunEvent
from app.models.processing_run_message import ProcessingRunMessage
from app.models.push_token import PushToken
from app.models.raw_message import RawMessage
from app.models.saved_link import SavedLink
from app.models.scheduled_task import ScheduledTask
from app.models.scheduled_task_run import ScheduledTaskRun
from app.models.synced_item import SyncedItem
from app.models.tool_connection import ToolConnection

__all__ = [
    "AppUser",
    "ChatImport",
    "ChatMessage",
    "ChatThread",
    "DailyUsage",
    "Document",
    "DocumentChunk",
    "DocumentFile",
    "Entity",
    "EntityMention",
    "EvaluationCaseResult",
    "EvaluationRun",
    "ExtractionResult",
    "Feedback",
    "InsightFeedback",
    "LlmCall",
    "Memory",
    "MemoryEmbedding",
    "MemoryEntity",
    "MemoryEvent",
    "MemoryRelation",
    "MemorySource",
    "PlaygroundRun",
    "ProcessingRun",
    "ProcessingRunEvent",
    "ProcessingRunMessage",
    "PushToken",
    "RawMessage",
    "SavedLink",
    "ScheduledTask",
    "ScheduledTaskRun",
    "SyncedItem",
    "ToolConnection",
]
