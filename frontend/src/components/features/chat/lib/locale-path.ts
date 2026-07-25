"use client";

import { useParams } from "next/navigation";
import { useCallback } from "react";

export function useLocalePath() {
  const params = useParams<{ locale?: string | string[] }>();
  const rawLocale = params?.locale;
  const locale = Array.isArray(rawLocale) ? rawLocale[0] : rawLocale;

  return useCallback(
    (path: string) => {
      const normalizedPath = path.startsWith("/") ? path : `/${path}`;
      return locale ? `/${locale}${normalizedPath}` : normalizedPath;
    },
    [locale],
  );
}
