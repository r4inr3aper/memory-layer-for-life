"""Apps a user can connect, and the Composio toolkits behind them.

The catalog is code, not data: it changes with the application and needs no migration.
Each entry's ``slug`` is the Composio toolkit slug and the app's id in the API.

Composio auth configs belong to a Composio project, not to the code, so the catalog holds
none: the connect flow uses ``COMPOSIO_AUTH_CONFIGS``, else the project's auth config for
the toolkit, else one it creates with Composio's managed sign-in
(``ToolConnectionService``).
"""

from dataclasses import dataclass
from typing import Final

from app.domain.enums import ScheduleDelivery

_LOGO_BASE_URL: Final = "https://logos.composio.dev/api"


@dataclass(frozen=True, slots=True)
class ToolAction:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ToolSpec:
    slug: str
    name: str
    description: str
    category: str
    actions: tuple[ToolAction, ...]

    @property
    def logo_url(self) -> str:
        return f"{_LOGO_BASE_URL}/{self.slug}"


TOOL_CATALOG: Final[tuple[ToolSpec, ...]] = (
    ToolSpec(
        slug="gmail",
        name="Gmail",
        description="Read, search, draft, and send email.",
        category="Communication",
        actions=(
            ToolAction("Read email", "Search and summarize messages in your inbox."),
            ToolAction("Send email", "Draft and send messages after you confirm."),
        ),
    ),
    ToolSpec(
        slug="slack",
        name="Slack",
        description="Read channels and post messages.",
        category="Communication",
        actions=(
            ToolAction("Read channels", "Summarize recent conversation in a channel."),
            ToolAction("Send message", "Post a message to a channel after you confirm."),
        ),
    ),
    ToolSpec(
        slug="googlecalendar",
        name="Google Calendar",
        description="See your schedule and manage events.",
        category="Productivity",
        actions=(
            ToolAction("List events", "Show what is on your calendar."),
            ToolAction("Create event", "Add an event after you confirm."),
        ),
    ),
    ToolSpec(
        slug="googlesheets",
        name="Google Sheets",
        description="Read and update spreadsheets.",
        category="Productivity",
        actions=(
            ToolAction("Read sheet", "Look up values in a spreadsheet."),
            ToolAction("Update sheet", "Append or change rows after you confirm."),
        ),
    ),
    ToolSpec(
        slug="googledocs",
        name="Google Docs",
        description="Read and write documents.",
        category="Productivity",
        actions=(
            ToolAction("Read document", "Summarize or search a document."),
            ToolAction("Write document", "Create or edit a document after you confirm."),
        ),
    ),
    ToolSpec(
        slug="notion",
        name="Notion",
        description="Search and update your Notion workspace.",
        category="Productivity",
        actions=(
            ToolAction("Search pages", "Find pages and databases."),
            ToolAction("Create page", "Create or update a page after you confirm."),
        ),
    ),
    ToolSpec(
        slug="outlook",
        name="Outlook",
        description="Read and send Outlook email.",
        category="Communication",
        actions=(
            ToolAction("Read email", "Search and summarize messages."),
            ToolAction("Send email", "Send messages after you confirm."),
        ),
    ),
    ToolSpec(
        slug="microsoftteams",
        name="Microsoft Teams",
        description="Read and post Teams messages.",
        category="Communication",
        actions=(ToolAction("Send message", "Post to a chat or channel after you confirm."),),
    ),
    ToolSpec(
        slug="discord",
        name="Discord",
        description="Post messages to Discord.",
        category="Communication",
        actions=(ToolAction("Send message", "Post to a channel after you confirm."),),
    ),
    ToolSpec(
        slug="youtube",
        name="YouTube",
        description="Search videos and read channel data.",
        category="Media",
        actions=(ToolAction("Search videos", "Find videos and their details."),),
    ),
    ToolSpec(
        slug="linkedin",
        name="LinkedIn",
        description="Read post content and profile details.",
        category="Career",
        actions=(
            ToolAction("Read post", "Fetch and summarize a hiring post."),
            ToolAction("Read profile", "Look up company or person profile details."),
        ),
    ),
    ToolSpec(
        slug="instagram",
        name="Instagram",
        description="Read account insights and media.",
        category="Media",
        actions=(ToolAction("Read media", "Look up posts and insights."),),
    ),
)

# The toolkit that carries each non-chat delivery of a scheduled run.
DELIVERY_TOOLKITS: Final[dict[ScheduleDelivery, str]] = {
    ScheduleDelivery.SLACK: "slack",
    ScheduleDelivery.EMAIL: "gmail",
    ScheduleDelivery.CALENDAR: "googlecalendar",
    ScheduleDelivery.NOTION: "notion",
    ScheduleDelivery.TEAMS: "microsoftteams",
    ScheduleDelivery.DISCORD: "discord",
}

_BY_SLUG: Final[dict[str, ToolSpec]] = {spec.slug: spec for spec in TOOL_CATALOG}


def find_tool(slug: str) -> ToolSpec | None:
    return _BY_SLUG.get(slug.strip().lower())
