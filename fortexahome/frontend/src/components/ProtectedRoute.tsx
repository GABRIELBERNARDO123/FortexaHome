import { ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { Brand, Button, Spinner } from "./ui";

export function FullPageLoading() {
  return (
    <div className="auth-loading">
      <Brand />
      <Spinner label="Preparando sua casa financeira..." />
    </div>
  );
}

function LicenseBlocked() {
  const { blockedMessage, logout } = useAuth();
  return (
    <div className="auth-loading">
      <div className="blocked-card">
        <div className="empty-icon">
          <ShieldAlert size={28} />
        </div>
        <h1>Acesso temporariamente bloqueado</h1>
        <p>{blockedMessage || "Sua licença precisa ser regularizada para continuar."}</p>
        <p className="muted">
          Entre em contato com o suporte FortexaHome informando o e-mail da conta. Seus dados continuam seguros.
        </p>
        <Button variant="primary" onClick={() => void logout()}>
          Sair desta conta
        </Button>
      </div>
    </div>
  );
}

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <FullPageLoading />;
  if (status === "blocked") return <LicenseBlocked />;
  if (status === "guest") {
    return <Navigate to="/entrar" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
