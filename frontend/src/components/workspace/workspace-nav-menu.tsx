"use client";

import {
  ChevronsUpDown,
  GlobeIcon,
  InfoIcon,
  MailIcon,
  Settings2Icon,
  SettingsIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsDialog } from "./settings";

function NavMenuButtonContent({
  isSidebarOpen,
  t,
}: {
  isSidebarOpen: boolean;
  t: ReturnType<typeof useI18n>["t"];
}) {
  return isSidebarOpen ? (
    <div className="flex w-full items-center gap-2 text-left text-sm text-[var(--kz-text-3)]">
      <div className="flex size-7 items-center justify-center rounded-full bg-[var(--kz-primary-soft)] text-[var(--kz-primary-2)]">
        <SettingsIcon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium text-[var(--kz-text-2)]">
          {t.workspace.settingsAndMore}
        </div>
        <div className="truncate text-[10px] text-[var(--kz-text-4)]">
          kamiwaza.team
        </div>
      </div>
      <ChevronsUpDown className="ml-auto size-4 text-[var(--kz-text-4)]" />
    </div>
  ) : (
    <div className="flex size-full items-center justify-center">
      <SettingsIcon className="size-4 text-[var(--kz-text-3)]" />
    </div>
  );
}

export function WorkspaceNavMenu() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDefaultSection, setSettingsDefaultSection] = useState<
    "appearance" | "memory" | "tools" | "skills" | "notification" | "about"
  >("appearance");
  const [mounted, setMounted] = useState(false);
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <>
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        defaultSection={settingsDefaultSection}
      />
      <SidebarMenu className="w-full">
        <SidebarMenuItem>
          {mounted ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton
                  size="lg"
                  className="data-[state=open]:text-sidebar-accent-foreground h-12 rounded-[var(--kz-r)] border border-transparent data-[state=open]:border-[var(--kz-border-emerald)] data-[state=open]:bg-[var(--kz-primary-soft)]"
                >
                  <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-[var(--kz-r)] border-[var(--kz-border)] bg-[var(--kz-surface)]"
                align="end"
                sideOffset={4}
              >
                <DropdownMenuGroup>
                  <DropdownMenuItem
                    onClick={() => {
                      setSettingsDefaultSection("appearance");
                      setSettingsOpen(true);
                    }}
                  >
                    <Settings2Icon />
                    {t.common.settings}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <a
                    href="https://kamiwaza.ai/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <DropdownMenuItem>
                      <GlobeIcon />
                      {t.workspace.officialWebsite}
                    </DropdownMenuItem>
                  </a>
                  <a href="mailto:support@kamiwaza.ai">
                    <DropdownMenuItem>
                      <MailIcon />
                      {t.workspace.contactUs}
                    </DropdownMenuItem>
                  </a>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={() => {
                    setSettingsDefaultSection("about");
                    setSettingsOpen(true);
                  }}
                >
                  <InfoIcon />
                  {t.workspace.about}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <SidebarMenuButton size="lg" className="pointer-events-none">
              <NavMenuButtonContent isSidebarOpen={isSidebarOpen} t={t} />
            </SidebarMenuButton>
          )}
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
