import type { Metadata } from "next";
import { UsersAdmin } from "@/components/admin/UsersAdmin";

export const metadata: Metadata = { title: "User Management" };

export default function UsersPage() {
  return (
    <div className="max-w-5xl mx-auto">
      <UsersAdmin />
    </div>
  );
}
