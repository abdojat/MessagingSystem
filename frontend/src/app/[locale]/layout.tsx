import { NextIntlClientProvider } from "next-intl";
import { getMessages, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { LocaleDocumentAttrs } from "@/components/LocaleDocumentAttrs";
import { isValidLocale } from "@/config/i18n.config";

interface LocaleLayoutProps {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}

// Renders the locale layout; Next.js invokes it while routing and rendering the application.
export default async function LocaleLayout({
  children,
  params,
}: LocaleLayoutProps) {
  const { locale } = await params;

  // Run this conditional step only when `!isValidLocale(locale)` is true.
  if (!isValidLocale(locale)) {
    notFound();
  }

  setRequestLocale(locale);

  const messages = await getMessages({ locale });
  const isRtl = locale === "ar";

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <LocaleDocumentAttrs locale={locale} dir={isRtl ? "rtl" : "ltr"} />
      <div dir={isRtl ? "rtl" : "ltr"}>{children}</div>
    </NextIntlClientProvider>
  );
}
