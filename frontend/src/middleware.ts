import createMiddleware from "next-intl/middleware";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { routing } from "@/config/i18n/routing";

const handleI18nRouting = createMiddleware(routing);

const AUTH_REQUIRED_PREFIXES = ["/app", "/profile", "/settings"];
const ADMIN_ONLY_PREFIXES = ["/admin", "/app/admin"];

function normalizeLocalePath(pathname: string): {
  locale: string;
  routePath: string;
} {
  const segments = pathname.split("/");
  const localeSegment = segments[1];

  if (routing.locales.includes(localeSegment as (typeof routing.locales)[number])) {
    const routePath = `/${segments.slice(2).join("/")}`.replace(/\/+$/, "") || "/";
    return { locale: localeSegment, routePath };
  }

  return { locale: routing.defaultLocale, routePath: pathname };
}

function hasMatchingPrefix(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export default function middleware(request: NextRequest) {
  const i18nResponse = handleI18nRouting(request);

  const redirectTarget = i18nResponse.headers.get("location");
  if (redirectTarget) {
    return i18nResponse;
  }

  const { locale, routePath } = normalizeLocalePath(request.nextUrl.pathname);
  const accessToken = request.cookies.get("chat_access_token")?.value;
  const role = request.cookies.get("chat_user_role")?.value ?? "member";

  if (hasMatchingPrefix(routePath, AUTH_REQUIRED_PREFIXES) && !accessToken) {
    const loginUrl = new URL(`/${locale}/login`, request.url);
    loginUrl.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (hasMatchingPrefix(routePath, ADMIN_ONLY_PREFIXES) && role !== "superadmin") {
    return NextResponse.redirect(new URL(`/${locale}/app`, request.url));
  }

  return i18nResponse;
}

export const config = {
  matcher: ["/((?!api|trpc|_next|_vercel|.*\\..*).*)"],
};
