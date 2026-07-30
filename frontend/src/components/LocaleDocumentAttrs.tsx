"use client";

import { useEffect } from "react";

type LocaleDocumentAttrsProps = {
  locale: string;
  dir: "ltr" | "rtl";
};

// Renders the locale document attrs component; parent React views use it to render or control the interface.
export function LocaleDocumentAttrs({ locale, dir }: LocaleDocumentAttrsProps) {
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [dir, locale]);

  return null;
}
