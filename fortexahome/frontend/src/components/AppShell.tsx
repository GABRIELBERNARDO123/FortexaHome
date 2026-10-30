import {
  ArrowLeftRight,
  BarChart3,
  CreditCard,
  LayoutDashboard,
  LogOut,
  Menu,
  PieChart,
  Plus,
  ReceiptText,
  Settings,
  Target,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { greeting, initials } from "../lib/format";
import { Brand, Button, IconButton } from "./ui";

const NAV_ITEMS = [
  { to: "/", label: "Visão geral", icon: LayoutDashboard, end: true },
  { to: "/lancamentos", label: "Receitas e despesas", icon: ArrowLeftRight },
  { to: "/contas", label: "Contas a pagar", icon: ReceiptText },
  { to: "/cartoes", label: "Cartões de crédito", icon: CreditCard },
  { to: "/orcamento", label: "Orçamento familiar", icon: PieChart },
  { to: "/metas", label: "Metas financeiras", icon: Target },
  { to: "/relatorios", label: "Relatórios", icon: BarChart3 },
];

export function AppShell() {
  const { auth, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  if (!auth) return null;

  const firstName = auth.user.name.split(" ")[0];

  return (
    <div className="app">
      <div className={menuOpen ? "sidebar-overlay open" : "sidebar-overlay"} onClick={() => setMenuOpen(false)} />
      <aside id="app-sidebar" className={menuOpen ? "sidebar open" : "sidebar"}>
        <div className="sidebar-top">
          <Brand />
          <IconButton
            label="Fechar menu"
            icon={X}
            className="sidebar-close"
            onClick={() => setMenuOpen(false)}
          />
        </div>
        <div className="nav-label">MENU PRINCIPAL</div>
        <nav className="nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="nav-label">PREFERÊNCIAS</div>
        <nav className="nav">
          <NavLink to="/configuracoes" className={({ isActive }) => (isActive ? "active" : undefined)}>
            <Settings size={18} />
            <span>Configurações</span>
          </NavLink>
        </nav>
        <div className="sidebar-bottom">
          <b>Seu lar, suas conquistas.</b>
          <p>Pequenas escolhas hoje constroem um futuro financeiro mais tranquilo para toda a família.</p>
        </div>
        <div className="sidebar-user">
          <div className="avatar">{initials(auth.user.name)}</div>
          <div>
            <strong>{auth.user.name}</strong>
            <span>{auth.tenant.name}</span>
          </div>
          <IconButton label="Sair da conta" icon={LogOut} onClick={() => void logout()} />
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="welcome">
            <IconButton
              label="Abrir menu"
              icon={Menu}
              className="mobile-menu"
              aria-expanded={menuOpen}
              aria-controls="app-sidebar"
              onClick={() => setMenuOpen(true)}
            />
            <div>
              <small>SEU RESUMO FINANCEIRO</small>
              <h2>
                {greeting()}, {firstName}! <span aria-hidden="true">👋</span>
              </h2>
            </div>
          </div>
          <div className="top-actions">
            <Button variant="primary" icon={Plus} onClick={() => navigate("/lancamentos?novo=1")}>
              <span className="desktop-label">Novo lançamento</span>
              <span className="mobile-label">Novo</span>
            </Button>
          </div>
        </header>
        <div className="page">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
