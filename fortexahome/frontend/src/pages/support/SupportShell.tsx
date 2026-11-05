import { ClipboardList, KeyRound, LayoutDashboard, LogOut, Mail, ScrollText, ShieldCheck, UserRoundCog } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { Brand, IconButton } from "../../components/ui";
import { useSupportAuth } from "../../context/SupportAuthContext";

const ITEMS = [
  { to: "/backoffice", label: "Visão geral", icon: LayoutDashboard, end: true },
  { to: "/backoffice/pedidos", label: "Pedidos", icon: ClipboardList },
  { to: "/backoffice/licencas", label: "Licenças", icon: KeyRound },
  { to: "/backoffice/outbox", label: "Outbox", icon: Mail },
  { to: "/backoffice/privacidade", label: "Privacidade", icon: UserRoundCog },
  { to: "/backoffice/auditoria", label: "Auditoria", icon: ScrollText },
];

export function SupportShell() {
  const { auth, logout } = useSupportAuth();
  if (!auth) return null;
  return (
    <div className="support-app">
      <header className="support-header">
        <div className="support-header-inner">
          <div className="support-brand">
            <Brand compact />
            <span className="support-badge"><ShieldCheck size={13} /> Suporte</span>
          </div>
          <nav className="support-nav" aria-label="Navegação do suporte">
            {ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? "active" : undefined)}
              >
                <item.icon size={16} />
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="support-user">
            <div>
              <strong>{auth.operator.name}</strong>
              <span>{auth.operator.email} · {auth.operator.role === "support_operator" ? "Operador" : "Leitura"}</span>
            </div>
            <IconButton label="Sair do suporte" icon={LogOut} onClick={() => void logout()} />
          </div>
        </div>
      </header>
      <main className="support-main">
        <Outlet />
      </main>
    </div>
  );
}
