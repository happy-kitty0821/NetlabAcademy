import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: {
    default: "NetLab Academy",
    template: "%s — NetLab Academy",
  },
  description:
    "Networking education platform for CCNA and CCNP learners. " +
    "Practice labs, examinations and a software network simulator.",
  keywords: ["CCNA", "CCNP", "networking", "simulation", "labs", "education"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
