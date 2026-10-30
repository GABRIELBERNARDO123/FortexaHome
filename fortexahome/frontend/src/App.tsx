import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { FullPageLoading, ProtectedRoute } from "./components/ProtectedRoute";
import { useAuth } from "./context/AuthContext";
import AuthPage from "./pages/AuthPage";
import BudgetsPage from "./pages/BudgetsPage";
import BillsPage from "./pages/BillsPage";
import CardsPage from "./pages/CardsPage";
import DashboardPage from "./pages/DashboardPage";
import GoalsPage from "./pages/GoalsPage";
import ReportsPage from "./pages/ReportsPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import SettingsPage from "./pages/SettingsPage";
import TransactionsPage from "./pages/TransactionsPage";

export default function App() {
  const { status } = useAuth();

  return (
    <Routes>
      <Route
        path="/entrar"
        element={
          status === "loading" ? (
            <FullPageLoading />
          ) : status === "authenticated" ? (
            <Navigate to="/" replace />
          ) : (
            <AuthPage />
          )
        }
      />
      <Route
        path="/redefinir-senha"
        element={
          status === "authenticated" ? <Navigate to="/" replace /> : <ResetPasswordPage />
        }
      />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="lancamentos" element={<TransactionsPage />} />
        <Route path="contas" element={<BillsPage />} />
        <Route path="cartoes" element={<CardsPage />} />
        <Route path="orcamento" element={<BudgetsPage />} />
        <Route path="metas" element={<GoalsPage />} />
        <Route path="relatorios" element={<ReportsPage />} />
        <Route path="configuracoes" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to={status === "guest" ? "/entrar" : "/"} replace />} />
    </Routes>
  );
}
