"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { withAppBasePath } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  getLocalSettings,
  LOCAL_SETTINGS_UPDATED_EVENT,
  normalizePreferredName,
} from "@/core/settings/local";
import { cn } from "@/lib/utils";

let waved = false;

function timeOfDayGreeting() {
  const hour = new Date().getHours();
  if (hour < 12) {
    return "Good morning";
  }
  if (hour < 18) {
    return "Good afternoon";
  }
  return "Good evening";
}

function normalizeKamiwazaDisplayName(value: string | null | undefined) {
  const normalized = normalizePreferredName(value);
  if (!normalized || normalized.toLowerCase() === "admin admin") {
    return null;
  }
  return normalized.split(/\s+/)[0] ?? null;
}

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const [kamiwazaDisplayName, setKamiwazaDisplayName] = useState<string | null>(
    null,
  );
  const [preferredName, setPreferredName] = useState("");

  useEffect(() => {
    waved = true;
  }, []);

  useEffect(() => {
    function syncPreferredName() {
      setPreferredName(
        normalizePreferredName(
          getLocalSettings().personalization.preferredName,
        ),
      );
    }

    syncPreferredName();
    window.addEventListener("storage", syncPreferredName);
    window.addEventListener(LOCAL_SETTINGS_UPDATED_EVENT, syncPreferredName);
    return () => {
      window.removeEventListener("storage", syncPreferredName);
      window.removeEventListener(
        LOCAL_SETTINGS_UPDATED_EVENT,
        syncPreferredName,
      );
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetch(withAppBasePath("/api/session"), {
      cache: "no-store",
      credentials: "same-origin",
    })
      .then(async (response) => {
        if (!response.ok) {
          return null;
        }
        return (await response.json()) as {
          user?: { displayName?: string | null };
        };
      })
      .then((session) => {
        if (!cancelled) {
          setKamiwazaDisplayName(
            normalizeKamiwazaDisplayName(session?.user?.displayName),
          );
        }
      })
      .catch(() => {
        // Header personalization is opportunistic; keep the generic greeting.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const greeting = useMemo(() => {
    const displayName = preferredName || kamiwazaDisplayName;
    if (!displayName) {
      return `${timeOfDayGreeting()}.`;
    }
    return `${timeOfDayGreeting()}, ${displayName}.`;
  }, [kamiwazaDisplayName, preferredName]);

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-3 px-8 py-5 text-center",
        className,
      )}
    >
      <div className="text-2xl font-semibold tracking-normal md:text-3xl">
        {searchParams.get("mode") === "skill" ? (
          <span className="aurora-text">{t.welcome.createYourOwnSkill}</span>
        ) : (
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "dot-live inline-block size-2.5",
                !waved ? "animate-wave" : "",
                mode === "ultra" ? "shadow-[var(--kz-shadow-primary)]" : "",
              )}
            />
            <span className="text-[var(--kz-text)]">{greeting}</span>
          </div>
        )}
      </div>
      {searchParams.get("mode") === "skill" ? (
        <div className="max-w-xl text-sm leading-6 text-[var(--kz-text-3)]">
          {t.welcome.createYourOwnSkillDescription.includes("\n") ? (
            <pre className="font-sans whitespace-pre">
              {t.welcome.createYourOwnSkillDescription}
            </pre>
          ) : (
            <p>{t.welcome.createYourOwnSkillDescription}</p>
          )}
        </div>
      ) : (
        <div className="max-w-xl text-sm leading-6 text-[var(--kz-text-3)]">
          {t.welcome.description.includes("\n") ? (
            <pre className="font-sans whitespace-pre">
              {t.welcome.description}
            </pre>
          ) : (
            <p>{t.welcome.description}</p>
          )}
        </div>
      )}
    </div>
  );
}
