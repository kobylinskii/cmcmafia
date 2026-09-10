import { AdminShell } from "@/components/admin/admin-shell";

export default function AdminDashboardLayout({ children }: { children: React.ReactNode }) {
  // admin-ui -- единственная точка, где панель поднимает размер мелкого текста
  // относительно публичного сайта, см. .admin-ui в app/globals.css.
  return (
    <div className="admin-ui">
      <AdminShell>{children}</AdminShell>
    </div>
  );
}
