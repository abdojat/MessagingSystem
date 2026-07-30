import { format, formatDistanceToNow, formatDistanceToNowStrict } from "date-fns";
import { ar, enUS } from "date-fns/locale";

// Selects the date-fns locale used for formatting; frontend components and services use it as a shared utility.
function dateFnsLocale(locale: string) {
  return locale === "ar" ? ar : enUS;
}

// Parses date; frontend components and services use it as a shared utility.
function parseDate(value?: string | Date | null) {
  // Return early when `!value` because the remaining work is not applicable.
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

// Formats date localized; frontend components and services use it as a shared utility.
export function formatDateLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  // Return early when `!date` because the remaining work is not applicable.
  if (!date) return fallback;
  return format(date, "PPP", { locale: dateFnsLocale(locale) });
}

// Formats date time localized; frontend components and services use it as a shared utility.
export function formatDateTimeLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  // Return early when `!date` because the remaining work is not applicable.
  if (!date) return fallback;
  return format(date, "PPP p", { locale: dateFnsLocale(locale) });
}

// Formats relative time localized; frontend components and services use it as a shared utility.
export function formatRelativeTimeLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  // Return early when `!date` because the remaining work is not applicable.
  if (!date) return fallback;
  return formatDistanceToNow(date, { addSuffix: true, locale: dateFnsLocale(locale) });
}

// Formats relative time strict localized; frontend components and services use it as a shared utility.
export function formatRelativeTimeStrictLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  // Return early when `!date` because the remaining work is not applicable.
  if (!date) return fallback;
  return formatDistanceToNowStrict(date, { addSuffix: true, locale: dateFnsLocale(locale) });
}

// Formats number localized; frontend components and services use it as a shared utility.
export function formatNumberLocalized(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value);
}
