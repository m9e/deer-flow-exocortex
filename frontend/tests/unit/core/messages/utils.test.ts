import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  extractContentFromMessage,
  groupMessages,
  hasContent,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";

function message(overrides: Partial<Message>): Message {
  return {
    id: "message-id",
    type: "human",
    content: "hello",
    ...overrides,
  } as unknown as Message;
}

test("hides backend-marked internal messages", () => {
  const hidden = message({
    additional_kwargs: { hide_from_ui: true },
    content: "<system_reminder>internal</system_reminder>",
  });

  expect(isHiddenFromUIMessage(hidden)).toBe(true);
  expect(groupMessages([hidden], (group) => group.type)).toEqual([]);
});

test("hides legacy todo reminder messages by name", () => {
  const messages = [
    message({
      id: "summary",
      name: "conversation_summary",
      content: "Here is a summary of the conversation to date:\n\ninternal",
    }),
    message({
      id: "todo-1",
      name: "todo_reminder",
      content: "<system_reminder>internal</system_reminder>",
    }),
    message({
      id: "todo-2",
      name: "todo_completion_reminder",
      content: "<system_reminder>internal</system_reminder>",
    }),
    message({ id: "visible", content: "visible" }),
  ];

  expect(groupMessages(messages, (group) => group.type)).toEqual(["human"]);
});

test("strips echoed system reminder blocks from assistant content", () => {
  const echoed = message({
    type: "ai",
    content:
      "The provider is unavailable.\n\n<system_reminder>Do not show this.</system_reminder>",
  });

  expect(extractContentFromMessage(echoed)).toBe("The provider is unavailable.");
  expect(hasContent(echoed)).toBe(true);
  expect(groupMessages([echoed], (group) => group.type)).toEqual([
    "assistant",
  ]);
});

test("does not render assistant messages containing only an echoed system reminder", () => {
  const echoed = message({
    type: "ai",
    content: "<system_reminder>Do not show this.</system_reminder>",
  });

  expect(extractContentFromMessage(echoed)).toBe("");
  expect(hasContent(echoed)).toBe(false);
  expect(groupMessages([echoed], (group) => group.type)).toEqual([]);
});
