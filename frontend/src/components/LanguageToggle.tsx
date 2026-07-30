"use client";

import { Languages } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { locales } from "@/config/i18n.config";
import { cn } from "@/lib/utils";

type LanguageToggleProps = {
  className?: string;
};

function replaceLocaleInPath(pathname: string, nextLocale: string) {
  const segments = pathname.split("/");
  const currentLocale = segments[1];

  if (locales.includes(currentLocale as (typeof locales)[number])) {
    segments[1] = nextLocale;
    return segments.join("/") || `/${nextLocale}`;
  }

  return `/${nextLocale}${pathname === "/" ? "" : pathname}`;
}

export function LanguageToggle({ className }: LanguageToggleProps) {
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const t = useTranslations("common.language");
  const nextLocale = locale === "ar" ? "en" : "ar";

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={cn("rounded-xl", className)}
      onClick={() => router.push(replaceLocaleInPath(pathname, nextLocale))}
      aria-label={t("switchTo", { locale: t(`names.${nextLocale}`) })}
      title={t("switchTo", { locale: t(`names.${nextLocale}`) })}
    >
      <Languages className="h-4 w-4" />
      <span className="sr-only">{t("current", { locale: t(`names.${locale}`) })}</span>
    </Button>
  );
}
