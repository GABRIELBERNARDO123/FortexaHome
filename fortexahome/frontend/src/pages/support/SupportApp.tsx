import { Navigate, Route, Routes } from "react-router-dom";

import { FullPageLoading } from "../../components/ProtectedRoute";
import { SupportAuthProvider, useSupportAuth } from "../../context/SupportAuthContext";
import SupportAuditPage from "./SupportAuditPage";
import SupportDashboardPage from "./SupportDashboardPage";
import SupportLicensesPage from "./SupportLicensesPage";
import SupportLoginPage from "./SupportLoginPage";
import SupportOrderDetailPage from "./SupportOrderDetailPage";
import SupportOrdersPage from "./SupportOrdersPage";
import SupportOutboxPage from "./SupportOutboxPage";
import SupportPrivacyPage from "./SupportPrivacyPage";
import { SupportShell } from "./SupportShell";

function SupportLoginGate() {
  const { status } = useSupportAuth();
  if (status === "loading") return <FullPageLoading />;
  if (status === "authenticated") return <Navigate to="/backoffice" replace />;
  return <SupportLoginPage />;
}

function SupportProtected() {
  const { status } = useSupportAuth();
  if (status === "loading") return <FullPageLoading />;
  if (status !== "authenticated") return <Navigate to="/backoffice/login" replace />;
  return <SupportShell />;
}

export default function SupportApp() {
  return (
    <SupportAuthProvider>
      <Routes>
        <Route path="login" element={<SupportLoginGate />} />
        <Route element={<SupportProtected />}>
          <Route index element={<SupportDashboardPage />} />
          <Route path="pedidos" element={<SupportOrdersPage />} />
          <Route path="pedidos/:orderId" element={<SupportOrderDetailPage />} />
          <Route path="licencas" element={<SupportLicensesPage />} />
          <Route path="outbox" element={<SupportOutboxPage />} />
          <Route path="privacidade" element={<SupportPrivacyPage />} />
          <Route path="auditoria" element={<SupportAuditPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/backoffice" replace />} />
      </Routes>
    </SupportAuthProvider>
  );
}
