import type { Metadata } from "next";
import { UserProvider } from "@/lib/user-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Friendly — Discover Your People",
  description: "Find friends with shared passions through your social graph. Skip the small talk.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body className="min-h-screen antialiased">
        <UserProvider>
          {children}
        </UserProvider>
      </body>
    </html>
  );
}
