import { ChevronUpIcon, ListTodoIcon } from "lucide-react";
import { useState } from "react";

import type { Todo } from "@/core/todos";
import { cn } from "@/lib/utils";

import {
  QueueItem,
  QueueItemContent,
  QueueItemIndicator,
  QueueList,
} from "../ai-elements/queue";

export function TodoList({
  className,
  todos,
  collapsed: controlledCollapsed,
  hidden = false,
  onToggle,
}: {
  className?: string;
  todos: Todo[];
  collapsed?: boolean;
  hidden?: boolean;
  onToggle?: () => void;
}) {
  const [internalCollapsed, setInternalCollapsed] = useState(true);
  const isControlled = controlledCollapsed !== undefined;
  const collapsed = isControlled ? controlledCollapsed : internalCollapsed;

  const handleToggle = () => {
    if (isControlled) {
      onToggle?.();
    } else {
      setInternalCollapsed((prev) => !prev);
    }
  };

  return (
    <div
      className={cn(
        "flex h-fit w-full origin-bottom translate-y-4 flex-col overflow-hidden rounded-t-xl border border-b-0 border-[var(--kz-border-soft)] bg-[rgba(15,23,42,0.92)] backdrop-blur-sm transition-all duration-200 ease-out",
        hidden ? "pointer-events-none translate-y-8 opacity-0" : "",
        className,
      )}
    >
      <header
        className={cn(
          "flex min-h-8 shrink-0 cursor-pointer items-center justify-between border-b border-[var(--kz-border-soft)] px-4 text-sm transition-all duration-300 ease-out",
        )}
        onClick={handleToggle}
      >
        <div className="text-[var(--kz-text-3)]">
          <div className="flex items-center justify-center gap-2">
            <ListTodoIcon className="size-4" />
            <div>To-dos</div>
          </div>
        </div>
        <div>
          <ChevronUpIcon
            className={cn(
              "size-4 text-[var(--kz-text-4)] transition-transform duration-300 ease-out",
              collapsed ? "" : "rotate-180",
            )}
          />
        </div>
      </header>
      <main
        className={cn(
          "flex grow px-2 transition-all duration-300 ease-out",
          collapsed ? "h-0 pb-3" : "h-28 pb-4",
        )}
      >
        <QueueList className="mt-0 w-full rounded-t-xl bg-[var(--kz-well)]">
          {todos.map((todo, i) => (
            <QueueItem key={i + (todo.content ?? "")}>
              <div className="flex items-center gap-2">
                <QueueItemIndicator
                  className={
                    todo.status === "in_progress"
                      ? "border-[var(--kz-primary-2)] bg-[var(--kz-primary-soft)]"
                      : ""
                  }
                  completed={todo.status === "completed"}
                />
                <QueueItemContent
                  className={
                    todo.status === "in_progress"
                      ? "text-[var(--kz-primary-2)]"
                      : "text-[var(--kz-text-2)]"
                  }
                  completed={todo.status === "completed"}
                >
                  {todo.content}
                </QueueItemContent>
              </div>
            </QueueItem>
          ))}
        </QueueList>
      </main>
    </div>
  );
}
