import { getRequestConfig } from "next-intl/server";
import { defaultLocale, isValidLocale } from "@/config/i18n.config";

export default getRequestConfig(
  async ({ requestLocale }: { requestLocale: Promise<string | undefined> }) => {
  const candidateLocale = await requestLocale;
  const locale = candidateLocale && isValidLocale(candidateLocale)
    ? candidateLocale
    : defaultLocale;

  return {
    locale,
    messages: (await import(`../../locales/${locale}.json`)).default,
  };
});
