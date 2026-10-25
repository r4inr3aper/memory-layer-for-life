import type { ChatMessage as ApiChatMessage } from "@/lib/api/types";
import { toUiMessage } from "@/types";

function apiMessage(overrides: Partial<ApiChatMessage> = {}): ApiChatMessage {
  return {
    id: "msg-1",
    thread_id: "thread-1",
    role: "user",
    content: "Here are the files",
    metadata: {},
    created_at: "2026-10-19T08:30:00Z",
    updated_at: "2026-10-19T08:30:00Z",
    ...overrides,
  };
}

describe("toUiMessage", () => {
  it("maps a stored user message", () => {
    const message = toUiMessage(apiMessage());

    expect(message).toMatchObject({
      id: "msg-1",
      sender: "user",
      text: "Here are the files",
      attachments: undefined,
    });
    expect(typeof message.timestamp).toBe("string");
    expect(message.timestamp.length).toBeGreaterThan(0);
    expect(message.pending).toBeUndefined();
  });

  it("lists the files sent with a message", () => {
    const message = toUiMessage(
      apiMessage({
        content: "",
        metadata: {
          attachments: [
            {
              name: "receipt.pdf",
              media_type: "application/pdf",
              size_bytes: 120_000,
            },
            { name: "photo.jpg", media_type: "image/jpeg", size_bytes: 2_048 },
          ],
        },
      }),
    );

    expect(message.text).toBe("");
    expect(message.attachments).toEqual([
      { name: "receipt.pdf", mediaType: "application/pdf", sizeBytes: 120_000 },
      { name: "photo.jpg", mediaType: "image/jpeg", sizeBytes: 2_048 },
    ]);
  });

  it("leaves out an empty or missing attachment list", () => {
    expect(
      toUiMessage(apiMessage({ metadata: { attachments: [] } })).attachments,
    ).toBeUndefined();
    expect(
      toUiMessage(apiMessage({ metadata: { attachments: null } })).attachments,
    ).toBeUndefined();
  });

  it("maps an assistant reply and its cards", () => {
    const proposal = {
      title: "Inbox summary",
      original_prompt: "Summarize my inbox every morning",
      task: "Summarize unread email",
      frequency: "daily" as const,
      local_time: "08:00",
      weekday: null,
      timezone: "UTC",
      delivery: "chat" as const,
      delivery_target: null,
      summary: "Every day at 8:00",
      status: "pending" as const,
      scheduled_task_id: null,
    };
    const connectLink = {
      toolkit: "gmail",
      tool_name: "Gmail",
      connect_url: "https://c.test",
    };
    const jobDraft = {
      linkedin_post_url: "https://www.linkedin.com/posts/example",
      recipient_email: "jobs@example.com",
      subject: "Application for Backend Engineer",
      body: "Hello, I am interested in this role.",
      company: "Example Inc",
      role_title: "Backend Engineer",
      delivery_app: "gmail",
      send_tool_slug: "GMAIL_SEND_EMAIL",
      send_arguments: {
        to: ["jobs@example.com"],
        subject: "Application for Backend Engineer",
      },
      status: "pending" as const,
      error_message: null,
      sent_at: null,
    };

    const message = toUiMessage(
      apiMessage({
        role: "assistant",
        content: "**Done**",
        metadata: {
          schedule_proposal: proposal,
          connect_link: connectLink,
          browser_preview: null,
          job_application_draft: jobDraft,
        },
      }),
    );

    expect(message).toMatchObject({
      sender: "agent",
      text: "**Done**",
      scheduleProposal: proposal,
      jobApplicationDraft: jobDraft,
      connectCta: connectLink,
      browserPreview: undefined,
      scheduledRun: undefined,
    });
  });

  it("tolerates metadata missing from the response", () => {
    const message = toUiMessage(
      apiMessage({
        metadata: undefined as unknown as ApiChatMessage["metadata"],
      }),
    );
    expect(message.attachments).toBeUndefined();
    expect(message.scheduleProposal).toBeUndefined();
  });
});
