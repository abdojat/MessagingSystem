"use client";

import { useEffect } from "react";

type LocaleDocumentAttrsProps = {
  locale: string;
  dir: "ltr" | "rtl";
};

export function LocaleDocumentAttrs({ locale, dir }: LocaleDocumentAttrsProps) {
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [dir, locale]);

  return null;
}
