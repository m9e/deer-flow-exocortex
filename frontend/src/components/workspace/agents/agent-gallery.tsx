"use client";

import { BotIcon, PlusIcon } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useAgents } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";

import { AgentCard } from "./agent-card";

export function AgentGallery() {
  const { t } = useI18n();
  const { agents, isLoading } = useAgents();
  const router = useRouter();

  const handleNewAgent = () => {
    router.push("/workspace/agents/new");
  };

  return (
    <div className="flex size-full flex-col bg-[var(--kz-bg)]">
      {/* Page header */}
      <div className="flex items-center justify-between border-b border-[var(--kz-border-soft)] bg-[rgba(11,18,32,0.78)] px-6 py-4 backdrop-blur-sm">
        <div>
          <h1 className="text-xl font-semibold text-[var(--kz-text)]">
            {t.agents.title}
          </h1>
          <p className="mt-0.5 text-sm text-[var(--kz-text-3)]">
            {t.agents.description}
          </p>
        </div>
        <Button className="rounded-full" onClick={handleNewAgent}>
          <PlusIcon className="mr-1.5 h-4 w-4" />
          {t.agents.newAgent}
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex h-40 items-center justify-center text-sm text-[var(--kz-text-3)]">
            {t.common.loading}
          </div>
        ) : agents.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-[var(--kz-r)] bg-[var(--kz-primary-soft)] text-[var(--kz-primary-2)]">
              <BotIcon className="h-7 w-7" />
            </div>
            <div>
              <p className="font-medium text-[var(--kz-text)]">
                {t.agents.emptyTitle}
              </p>
              <p className="mt-1 text-sm text-[var(--kz-text-3)]">
                {t.agents.emptyDescription}
              </p>
            </div>
            <Button
              variant="outline"
              className="mt-2 rounded-full border-[var(--kz-border-emerald)] text-[var(--kz-primary-2)]"
              onClick={handleNewAgent}
            >
              <PlusIcon className="mr-1.5 h-4 w-4" />
              {t.agents.newAgent}
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {agents.map((agent) => (
              <AgentCard key={agent.name} agent={agent} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
