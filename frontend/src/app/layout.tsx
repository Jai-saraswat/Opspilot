import type { Metadata, Viewport } from "next";
import "./globals.css";

import { AuthProvider } from "@/providers/auth-provider";

export const metadata: Metadata = {
  title: {
    default: "OpsPilot — Operations Management",
    template: "%s | OpsPilot",
  },
  description:
    "A centralized workspace to coordinate operational work, manage teams, track approvals, and maintain a reliable activity history.",
  applicationName: "OpsPilot",
  robots: {
    index: false,
    follow: false,
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#09090b",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}