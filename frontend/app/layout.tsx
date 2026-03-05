import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Channels Frontend",
  description: "Blank Next.js App Router frontend",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
