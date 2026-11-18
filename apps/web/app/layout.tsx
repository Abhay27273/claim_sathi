import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClaimSaathi",
  description: "Turn a rejected health-insurance claim into a rule-cited escalation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
