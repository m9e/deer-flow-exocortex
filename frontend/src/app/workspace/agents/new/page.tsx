"use client";

import {
  ArrowLeftIcon,
  BotIcon,
  CheckCircleIcon,
  CheckIcon,
  InfoIcon,
  MoreHorizontalIcon,
  SaveIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import {
  PromptInputProvider,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { InputBox } from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import type { Agent } from "@/core/agents";
import {
  AgentNameCheckError,
  checkAgentName,
  createAgent,
  getAgent,
} from "@/core/agents/api";
import { getAppStorageKey } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import type { AgentThreadContext } from "@/core/threads";
import { useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

type Step = "name" | "chat";
type SetupAgentStatus = "idle" | "requested" | "completed";

type InputBoxContext = Omit<
  AgentThreadContext,
  "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
> & {
  mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
};

const NAME_RE = /^[A-Za-z0-9-]+$/;
const SAVE_HINT_STORAGE_KEY = "deerflow.agent-create.save-hint-seen";
const AGENT_READ_RETRY_DELAYS_MS = [200, 500, 1_000, 2_000];

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function getAgentWithRetry(agentName: string) {
  for (const delay of [0, ...AGENT_READ_RETRY_DELAYS_MS]) {
    if (delay > 0) {
      await wait(delay);
    }

    try {
      return await getAgent(agentName);
    } catch {
      // Retry until the write settles or the attempts are exhausted.
    }
  }

  return null;
}

function getCreateAgentErrorMessage(
  error: unknown,
  networkErrorMessage: string,
  fallbackMessage: string,
) {
  if (error instanceof TypeError && error.message === "Failed to fetch") {
    return networkErrorMessage;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallbackMessage;
}

export default function NewAgentPage() {
  const { t } = useI18n();
  const router = useRouter();

  const [step, setStep] = useState<Step>("name");
  const [nameInput, setNameInput] = useState("");
  const [nameError, setNameError] = useState("");
  const [isCheckingName, setIsCheckingName] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [agentName, setAgentName] = useState("");
  const [pendingBootstrapAgentName, setPendingBootstrapAgentName] = useState<
    string | null
  >(null);
  const bootstrapRequestedRef = useRef<string | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [showSaveHint, setShowSaveHint] = useState(false);
  const [setupAgentStatus, setSetupAgentStatus] =
    useState<SetupAgentStatus>("idle");

  // Track mode, model_name, reasoning_effort, is_bootstrap — so the model
  // picker in both the name step and the chat-step InputBox feeds the same
  // configurable forwarded to the lead_agent run.
  const [inputContext, setInputContext] = useState<InputBoxContext>({
    mode: "flash",
    reasoning_effort: "minimal",
    is_bootstrap: true,
  });

  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();

  // On first load of models, pre-select the first one so the name-step bootstrap
  // call has a concrete model_name and the user can swap it before Continue.
  useEffect(() => {
    if (models.length === 0 || inputContext.model_name) return;
    setInputContext((prev) => ({ ...prev, model_name: models[0]!.name }));
  }, [models, inputContext.model_name]);

  const selectedModel = useMemo(
    () =>
      models.find((m) => m.name === inputContext.model_name) ?? models[0],
    [inputContext.model_name, models],
  );

  const threadId = useMemo(() => uuid(), []);

  const [thread, sendMessage] = useThreadStream({
    threadId: step === "chat" ? threadId : undefined,
    context: inputContext,
    onFinish() {
      if (!agent && setupAgentStatus === "requested") {
        setSetupAgentStatus("idle");
      }
    },
    onToolEnd({ name }) {
      if (name !== "setup_agent" || !agentName) return;
      setSetupAgentStatus("completed");
      void getAgentWithRetry(agentName).then((fetched) => {
        if (fetched) {
          setAgent(fetched);
          return;
        }

        toast.error(t.agents.agentCreatedPendingRefresh);
      });
    },
  });

  useEffect(() => {
    if (typeof window === "undefined" || step !== "chat") {
      return;
    }
    const storageKey = getAppStorageKey(SAVE_HINT_STORAGE_KEY);
    if (window.localStorage.getItem(storageKey) === "1") {
      return;
    }
    setShowSaveHint(true);
    window.localStorage.setItem(storageKey, "1");
  }, [step]);

  useEffect(() => {
    if (step !== "chat" || !pendingBootstrapAgentName) {
      return;
    }
    if (bootstrapRequestedRef.current === pendingBootstrapAgentName) {
      return;
    }

    const bootstrapAgentName = pendingBootstrapAgentName;
    bootstrapRequestedRef.current = bootstrapAgentName;
    setPendingBootstrapAgentName(null);

    // Wait until the chat step has committed so the initial bootstrap send
    // doesn't race the hook's thread switch reset and disappear from the UI.
    void sendMessage(
      threadId,
      {
        text: t.agents.nameStepBootstrapMessage.replace(
          "{name}",
          bootstrapAgentName,
        ),
        files: [],
      },
      { agent_name: bootstrapAgentName },
    ).catch((error) => {
      toast.error(error instanceof Error ? error.message : String(error));
    });
  }, [
    pendingBootstrapAgentName,
    sendMessage,
    step,
    t.agents.nameStepBootstrapMessage,
    threadId,
  ]);

  const handleConfirmName = useCallback(async () => {
    const trimmed = nameInput.trim();
    if (!trimmed) return;
    if (!NAME_RE.test(trimmed)) {
      setNameError(t.agents.nameStepInvalidError);
      return;
    }

    setNameError("");
    setIsCheckingName(true);
    try {
      const result = await checkAgentName(trimmed);
      if (!result.available) {
        setNameError(t.agents.nameStepAlreadyExistsError);
        return;
      }
    } catch (err) {
      if (
        err instanceof AgentNameCheckError &&
        err.reason === "backend_unreachable"
      ) {
        setNameError(t.agents.nameStepNetworkError);
      } else {
        setNameError(t.agents.nameStepCheckError);
      }
      return;
    } finally {
      setIsCheckingName(false);
    }

    setIsCreatingAgent(true);
    try {
      await createAgent({
        name: trimmed,
        description: "",
        soul: "",
      });
    } catch (err) {
      setNameError(
        getCreateAgentErrorMessage(
          err,
          t.agents.nameStepNetworkError,
          t.agents.nameStepCheckError,
        ),
      );
      return;
    } finally {
      setIsCreatingAgent(false);
    }

    setAgentName(trimmed);
    bootstrapRequestedRef.current = null;
    setInputContext((prev) => ({ ...prev, agent_name: trimmed }));
    setPendingBootstrapAgentName(trimmed);
    setStep("chat");
  }, [
    nameInput,
    t.agents.nameStepAlreadyExistsError,
    t.agents.nameStepNetworkError,
    t.agents.nameStepCheckError,
    t.agents.nameStepInvalidError,
  ]);

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !isIMEComposing(e)) {
      e.preventDefault();
      void handleConfirmName();
    }
  };

  const handleChatSubmit = useCallback(
    async (message: PromptInputMessage) => {
      const trimmed = (message.text ?? "").trim();
      if (!trimmed || thread.isLoading) return;
      await sendMessage(
        threadId,
        { text: trimmed, files: message.files ?? [] },
        { agent_name: agentName },
      );
    },
    [agentName, sendMessage, thread.isLoading, threadId],
  );

  const handleSaveAgent = useCallback(async () => {
    if (
      !agentName ||
      agent ||
      thread.isLoading ||
      setupAgentStatus !== "idle"
    ) {
      return;
    }

    setSetupAgentStatus("requested");
    setShowSaveHint(false);
    try {
      await sendMessage(
        threadId,
        { text: t.agents.saveCommandMessage, files: [] },
        { agent_name: agentName },
        { additionalKwargs: { hide_from_ui: true } },
      );
      toast.success(t.agents.saveRequested);
    } catch (error) {
      setSetupAgentStatus("idle");
      toast.error(error instanceof Error ? error.message : String(error));
    }
  }, [
    agent,
    agentName,
    sendMessage,
    setupAgentStatus,
    t.agents.saveCommandMessage,
    t.agents.saveRequested,
    thread.isLoading,
    threadId,
  ]);

  const header = (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => router.push("/workspace/agents")}
        >
          <ArrowLeftIcon className="h-4 w-4" />
        </Button>
        <h1 className="text-sm font-semibold">{t.agents.createPageTitle}</h1>
      </div>

      {step === "chat" ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t.agents.more}>
              <MoreHorizontalIcon className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              onSelect={() => void handleSaveAgent()}
              disabled={
                !!agent || thread.isLoading || setupAgentStatus !== "idle"
              }
            >
              <SaveIcon className="h-4 w-4" />
              {setupAgentStatus === "requested"
                ? t.agents.saving
                : t.agents.save}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </header>
  );

  if (step === "name") {
    return (
      <div className="flex size-full flex-col">
        {header}
        <main className="flex flex-1 flex-col items-center justify-center px-4">
          <div className="w-full max-w-sm space-y-8">
            <div className="space-y-3 text-center">
              <div className="bg-primary/10 mx-auto flex h-14 w-14 items-center justify-center rounded-full">
                <BotIcon className="text-primary h-7 w-7" />
              </div>
              <div className="space-y-1">
                <h2 className="text-xl font-semibold">
                  {t.agents.nameStepTitle}
                </h2>
                <p className="text-muted-foreground text-sm">
                  {t.agents.nameStepHint}
                </p>
              </div>
            </div>

            <div className="space-y-3">
              <Input
                autoFocus
                type="text"
                name="agent-name"
                placeholder={t.agents.nameStepPlaceholder}
                value={nameInput}
                onChange={(e) => {
                  setNameInput(e.target.value);
                  setNameError("");
                }}
                onKeyDown={handleNameKeyDown}
                className={cn(nameError && "border-destructive")}
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
                data-1p-ignore
                data-lpignore="true"
                data-bwignore
                data-form-type="other"
              />
              {nameError ? (
                <p className="text-destructive text-sm">{nameError}</p>
              ) : null}
              {models.length > 0 && (
                <div className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs">
                  <span className="text-muted-foreground">
                    {t.inputBox.searchModels ?? "Model"}
                  </span>
                  <ModelSelector
                    open={modelDialogOpen}
                    onOpenChange={setModelDialogOpen}
                  >
                    <ModelSelectorTrigger asChild>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-auto px-2 py-1 text-xs font-normal"
                      >
                        <ModelSelectorName>
                          {selectedModel?.display_name ?? "Select…"}
                        </ModelSelectorName>
                      </Button>
                    </ModelSelectorTrigger>
                    <ModelSelectorContent>
                      <ModelSelectorInput
                        placeholder={t.inputBox.searchModels}
                      />
                      <ModelSelectorList>
                        {models.map((m) => (
                          <ModelSelectorItem
                            key={m.name}
                            value={m.name}
                            onSelect={() => {
                              setInputContext((prev) => ({
                                ...prev,
                                model_name: m.name,
                              }));
                              setModelDialogOpen(false);
                            }}
                          >
                            <div className="flex min-w-0 flex-1 flex-col">
                              <ModelSelectorName>
                                {m.display_name}
                              </ModelSelectorName>
                              <span className="text-muted-foreground truncate text-[10px]">
                                {m.model}
                              </span>
                            </div>
                            {m.name === inputContext.model_name ? (
                              <CheckIcon className="ml-auto size-4" />
                            ) : (
                              <div className="ml-auto size-4" />
                            )}
                          </ModelSelectorItem>
                        ))}
                      </ModelSelectorList>
                    </ModelSelectorContent>
                  </ModelSelector>
                </div>
              )}
              <Button
                className="w-full"
                onClick={() => void handleConfirmName()}
                disabled={
                  !nameInput.trim() || isCheckingName || isCreatingAgent
                }
              >
                {t.agents.nameStepContinue}
              </Button>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <ThreadContext.Provider value={{ thread }}>
      <ArtifactsProvider>
        <PromptInputProvider>
        <div className="flex size-full flex-col">
          {header}

          <main className="flex min-h-0 flex-1 flex-col">
            {showSaveHint ? (
              <div className="px-4 pt-4">
                <div className="mx-auto w-full max-w-(--container-width-md)">
                  <Alert>
                    <InfoIcon className="h-4 w-4" />
                    <AlertDescription>{t.agents.saveHint}</AlertDescription>
                  </Alert>
                </div>
              </div>
            ) : null}

            <div className="flex min-h-0 flex-1 justify-center">
              <MessageList
                className={cn("size-full", showSaveHint ? "pt-4" : "pt-10")}
                threadId={threadId}
                thread={thread}
              />
            </div>

            <div className="bg-background flex shrink-0 justify-center border-t px-4 py-4">
              <div className="w-full max-w-(--container-width-md)">
                {agent ? (
                  <div className="flex flex-col items-center gap-4 rounded-2xl border py-8 text-center">
                    <CheckCircleIcon className="text-primary h-10 w-10" />
                    <p className="font-semibold">{t.agents.agentCreated}</p>
                    <div className="flex gap-2">
                      <Button
                        onClick={() =>
                          router.push(
                            `/workspace/agents/${agentName}/chats/new`,
                          )
                        }
                      >
                        {t.agents.startChatting}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => router.push("/workspace/agents")}
                      >
                        {t.agents.backToGallery}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <InputBox
                    threadId={threadId}
                    context={inputContext}
                    onContextChange={setInputContext}
                    status={thread.isLoading ? "streaming" : "ready"}
                    disabled={thread.isLoading}
                    autoFocus
                    onSubmit={(msg: PromptInputMessage) =>
                      void handleChatSubmit(msg)
                    }
                  />
                )}
              </div>
            </div>
          </main>
        </div>
        </PromptInputProvider>
      </ArtifactsProvider>
    </ThreadContext.Provider>
  );
}
