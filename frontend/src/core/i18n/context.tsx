"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import type { Locale } from "@/core/i18n";
import { setLocaleInCookie } from "@/core/i18n/cookies";

export interface I18nContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

export const I18nContext = createContext<I18nContextType | null>(null);

export function I18nProvider({
  children,
  initialLocale,
}: {
  children: ReactNode;
  initialLocale: Locale;
}) {
  const [locale, setLocale] = useState<Locale>(initialLocale);

  const handleSetLocale = (newLocale: Locale) => {
    setLocale(newLocale);
    setLocaleInCookie(newLocale);
  };

  return (
    <I18nContext.Provider value={{ locale, setLocale: handleSetLocale }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18nContext() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return context;
}
