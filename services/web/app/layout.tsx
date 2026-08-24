import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Procura | Medicine procurement operations",
  description: "Capture medicine requirements, compare supplier quotations, manage exceptions, and record procurement decisions."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
