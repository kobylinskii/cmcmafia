import { AdminShell } from "@/components/admin/admin-shell";

export default function AdminDashboardLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
