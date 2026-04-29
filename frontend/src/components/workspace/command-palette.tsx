"use client";

import {
  BotIcon,
  KeyboardIcon,
  MessageSquarePlusIcon,
  SearchIcon,
  SettingsIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import { useGlobalShortcuts } from "@/hooks/use-global-shortcuts";

import { SettingsDialog } from "./settings";

export function CommandPalette() {
  const { t } = useI18n();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isMac, setIsMac] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Radix components use an internal id counter (useId). Rendering them during
  // SSR can produce ids that disagree with the post-hydration client render,
  // which surfaces as the `radix-_R_…` hydration mismatch. Defer to the client
  // to skip the mismatch entirely.
  useEffect(() => {
    setMounted(true);
  }, []);

  const handleNewChat = useCallback(() => {
    router.push("/workspace/chats/new");
    setOpen(false);
  }, [router]);

  const handleOpenSettings = useCallback(() => {
    setOpen(false);
    setSettingsOpen(true);
  }, []);

  const handleShowShortcuts = useCallback(() => {
    setOpen(false);
    setShortcutsOpen(true);
  }, []);

  const shortcuts = useMemo(
    () => [
      { key: "k", meta: true, action: () => setOpen((o) => !o) },
      { key: "n", meta: true, shift: true, action: handleNewChat },
      { key: ",", meta: true, action: handleOpenSettings },
      { key: "/", meta: true, action: handleShowShortcuts },
    ],
    [handleNewChat, handleOpenSettings, handleShowShortcuts],
  );

  useGlobalShortcuts(shortcuts);

  useEffect(() => {
    setIsMac(navigator.userAgent.includes("Mac"));
  }, []);
  const metaKey = isMac ? "⌘" : "Ctrl+";
  const shiftKey = isMac ? "⇧" : "Shift+";

  // Keyboard shortcuts (above) register on every render, including SSR-noop;
  // only the Radix-backed dialogs need to be client-only.
  if (!mounted) {
    return null;
  }

  return (
    <>
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        className="flux-border overflow-hidden rounded-[var(--kz-r-lg)] border-[var(--kz-border)] bg-[var(--kz-surface)] shadow-[var(--kz-shadow-hero)] sm:max-w-2xl"
      >
        <div className="border-b border-[var(--kz-border-soft)] px-2 pt-2">
          <div className="eyebrow-muted px-2 py-1">Command</div>
          <CommandInput
            className="text-[var(--kz-text)]"
            placeholder={t.shortcuts.searchActions}
          />
        </div>
        <CommandList className="max-h-[420px] p-2">
          <CommandEmpty>{t.shortcuts.noResults}</CommandEmpty>
          <CommandGroup heading="Suggested">
            <CommandItem
              className="rounded-[var(--kz-r-sm)] py-3"
              onSelect={handleNewChat}
            >
              <MessageSquarePlusIcon className="mr-2 h-4 w-4 text-[var(--kz-primary-2)]" />
              {t.sidebar.newChat}
              <CommandShortcut>
                {metaKey}
                {shiftKey}N
              </CommandShortcut>
            </CommandItem>
            <CommandItem
              className="rounded-[var(--kz-r-sm)] py-3"
              onSelect={handleOpenSettings}
            >
              <SettingsIcon className="mr-2 h-4 w-4 text-[var(--kz-text-3)]" />
              {t.common.settings}
              <CommandShortcut>{metaKey},</CommandShortcut>
            </CommandItem>
          </CommandGroup>
          <CommandGroup heading="Workspace">
            <CommandItem
              className="rounded-[var(--kz-r-sm)] py-3"
              onSelect={handleShowShortcuts}
            >
              <KeyboardIcon className="mr-2 h-4 w-4 text-[var(--kz-text-3)]" />
              {t.shortcuts.keyboardShortcuts}
              <CommandShortcut>{metaKey}/</CommandShortcut>
            </CommandItem>
            <CommandItem
              className="rounded-[var(--kz-r-sm)] py-3"
              onSelect={() => {
                router.push("/workspace/agents");
                setOpen(false);
              }}
            >
              <BotIcon className="mr-2 h-4 w-4 text-[var(--kz-text-3)]" />
              {t.sidebar.agents}
              <CommandShortcut>@</CommandShortcut>
            </CommandItem>
            <CommandItem
              className="rounded-[var(--kz-r-sm)] py-3"
              onSelect={() => {
                router.push("/workspace/chats");
                setOpen(false);
              }}
            >
              <SearchIcon className="mr-2 h-4 w-4 text-[var(--kz-text-3)]" />
              {t.sidebar.chats}
              <CommandShortcut>#</CommandShortcut>
            </CommandItem>
          </CommandGroup>
        </CommandList>
        <div className="flex items-center justify-between border-t border-[var(--kz-border-soft)] px-4 py-2 text-[11px] text-[var(--kz-text-4)]">
          <span>Use sigils: &gt; actions, @ agents, # chats</span>
          <span className="font-mono">{metaKey}K</span>
        </div>
      </CommandDialog>

      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.shortcuts.keyboardShortcuts}</DialogTitle>
            <DialogDescription>
              {t.shortcuts.keyboardShortcutsDescription}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            {[
              { keys: `${metaKey}K`, label: t.shortcuts.openCommandPalette },
              { keys: `${metaKey}${shiftKey}N`, label: t.sidebar.newChat },
              { keys: `${metaKey}B`, label: t.shortcuts.toggleSidebar },
              { keys: `${metaKey},`, label: t.common.settings },
              {
                keys: `${metaKey}/`,
                label: t.shortcuts.keyboardShortcuts,
              },
            ].map(({ keys, label }) => (
              <div key={keys} className="flex items-center justify-between">
                <span className="text-muted-foreground">{label}</span>
                <kbd className="bg-muted text-muted-foreground rounded px-2 py-0.5 font-mono text-xs">
                  {keys}
                </kbd>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
