import { redirect } from "next/navigation";
import { defaultLocale } from "@/config/i18n.config";

// Renders the root page; Next.js invokes it while routing and rendering the application.
export default function RootPage() {
  redirect(`/${defaultLocale}`);
}

