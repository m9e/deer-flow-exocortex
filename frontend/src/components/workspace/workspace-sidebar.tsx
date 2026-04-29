"use client";

import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";

import { RecentChatList } from "./recent-chat-list";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  const { open: isSidebarOpen } = useSidebar();
  return (
    <>
      <Sidebar
        variant="sidebar"
        collapsible="icon"
        className="border-r border-[var(--kz-border-soft)] bg-[var(--kz-sidebar)]"
        {...props}
      >
        <SidebarHeader className="border-b border-[var(--kz-border-soft)] px-2 py-1">
          <WorkspaceHeader />
        </SidebarHeader>
        <SidebarContent className="gap-1 px-1 py-2">
          <WorkspaceNavChatList />
          {isSidebarOpen && <RecentChatList />}
        </SidebarContent>
        <SidebarFooter className="border-t border-[var(--kz-border-soft)] p-2">
          <WorkspaceNavMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
    </>
  );
}
