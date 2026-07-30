import type { Metadata } from "next";
import "@/index.css";

export const metadata: Metadata = {
  title: "ChatCore",
  description: "Multilingual role-based chat frontend",
};

// Renders the root layout; Next.js invokes it while routing and rendering the application.
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}

