import { defineRouting } from "next-intl/routing";
import { defaultLocale, locales } from "@/config/i18n.config";

export const routing = defineRouting({
  locales: [...locales],
  defaultLocale,
  localePrefix: "always",
});

