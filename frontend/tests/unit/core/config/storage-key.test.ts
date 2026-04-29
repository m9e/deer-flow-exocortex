import { afterEach, expect, test, vi } from "vitest";

import {
  getAppCookiePath,
  getAppStorageKey,
  withAppBasePath,
} from "@/core/config";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("scopes browser storage keys by App Garden runtime path", () => {
  vi.stubGlobal("window", {
    location: {
      pathname: "/runtime/apps/deer-flow-uat-db9bd5cc/workspace/chats/new",
    },
  });

  expect(getAppStorageKey("deerflow.local-settings")).toBe(
    "deerflow:/runtime/apps/deer-flow-uat-db9bd5cc:deerflow.local-settings",
  );
  expect(withAppBasePath("/workspace/chats/thread-1")).toBe(
    "/runtime/apps/deer-flow-uat-db9bd5cc/workspace/chats/thread-1",
  );
  expect(getAppCookiePath()).toBe("/runtime/apps/deer-flow-uat-db9bd5cc");
});

test("uses root storage namespace outside App Garden path routing", () => {
  vi.stubGlobal("window", {
    location: {
      pathname: "/workspace/chats/new",
    },
  });

  expect(getAppStorageKey("deerflow.local-settings")).toBe(
    "deerflow:/:deerflow.local-settings",
  );
  expect(withAppBasePath("/workspace/chats/thread-1")).toBe(
    "/workspace/chats/thread-1",
  );
  expect(getAppCookiePath()).toBe("/");
});
