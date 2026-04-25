import type { Metadata } from "next";
import "@/index.css";

export const metadata: Metadata = {
  title: "ChatCore",
  description: "Multilingual role-based chat frontend",
};

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

