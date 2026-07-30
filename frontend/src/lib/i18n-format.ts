import { format, formatDistanceToNow, formatDistanceToNowStrict } from "date-fns";
import { ar, enUS } from "date-fns/locale";

function dateFnsLocale(locale: string) {
  return locale === "ar" ? ar : enUS;
}

function parseDate(value?: string | Date | null) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  if (!date) return fallback;
  return format(date, "PPP", { locale: dateFnsLocale(locale) });
}

export function formatDateTimeLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  if (!date) return fallback;
  return format(date, "PPP p", { locale: dateFnsLocale(locale) });
}

export function formatRelativeTimeLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  if (!date) return fallback;
  return formatDistanceToNow(date, { addSuffix: true, locale: dateFnsLocale(locale) });
}

export function formatRelativeTimeStrictLocalized(
  value: string | Date | null | undefined,
  locale: string,
  fallback: string,
) {
  const date = parseDate(value);
  if (!date) return fallback;
  return formatDistanceToNowStrict(date, { addSuffix: true, locale: dateFnsLocale(locale) });
}

export function formatNumberLocalized(value: number, locale: string) {
  return new Intl.NumberFormat(locale).format(value);
}
