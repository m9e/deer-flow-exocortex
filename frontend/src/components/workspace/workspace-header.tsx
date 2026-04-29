"use client";

import { MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  KamiwazaMark,
  KamiwazaWordmark,
} from "@/components/branding/kamiwaza-mark";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state } = useSidebar();
  const pathname = usePathname();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full items-center justify-center">
            <Link
              href="/workspace"
              aria-label="Kamiwaza Flow home"
              className="group-hover/workspace-header:hidden"
            >
              <KamiwazaMark />
            </Link>
            <SidebarTrigger className="hidden group-hover/workspace-header:flex" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 px-2">
            <Link
              href={
                env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                  ? "/"
                  : "/workspace"
              }
              aria-label="Kamiwaza Flow home"
              className="min-w-0 rounded-md focus-visible:ring-2 focus-visible:ring-[var(--kz-primary)] focus-visible:outline-none"
            >
              <KamiwazaWordmark />
            </Link>
            <SidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats/new"}
            asChild
            className="border border-[var(--kz-border-emerald)] bg-[var(--kz-primary-soft)] text-[var(--kz-primary-2)] shadow-[0_0_0_1px_rgba(16,185,129,0.08)] hover:bg-[rgba(16,185,129,0.16)] hover:text-[var(--kz-text)]"
          >
            <Link href="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
