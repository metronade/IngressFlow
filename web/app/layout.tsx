import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "IngressFlow",
  description: "Media ingest for public broadcasting stations",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-neutral-950 text-neutral-100">{children}</body>
    </html>
  );
}
