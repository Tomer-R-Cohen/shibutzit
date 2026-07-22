import type { Metadata } from "next";
import { Rubik } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";

const rubik = Rubik({
  subsets: ["hebrew", "latin"],
  variable: "--font-rubik",
});

export const metadata: Metadata = {
  title: "שיבוץ תלמידות לכיתות ז'",
  description: "מערכת שיבוץ מאוזן לכיתות ז'",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html dir="rtl" lang="he" className={`${rubik.variable} h-full antialiased`}>
      <body
        className="min-h-full bg-slate-50 font-sans text-slate-900 dark:bg-slate-950 dark:text-slate-100"
        suppressHydrationWarning
      >
        {children}
        <Toaster position="top-center" richColors dir="rtl" />
      </body>
    </html>
  );
}
