export const locales = ["en", "ar"] as const;

export type AppLocale = (typeof locales)[number];

export const defaultLocale: AppLocale = "en";

// Determines whether valid locale; the frontend application uses it in its client workflow.
export function isValidLocale(locale: string): locale is AppLocale {
  return locales.includes(locale as AppLocale);
}

