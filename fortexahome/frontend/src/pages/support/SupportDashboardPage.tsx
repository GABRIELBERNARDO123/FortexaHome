import { AlertTriangle, CalendarClock, CreditCard, KeyRound, Mail } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorState, PageHeader, Panel, Skeleton, StatCard } from "../../components/ui";
import { useApiData } from "../../lib/useApiData";
import type { SupportDashboard } from "../../types";

export default function SupportDashboardPage() {
  const { data, loading, error, reload } = useApiData<SupportDashboard>("/support/dashboard");
  if (loading) return <Skeleton lines={8} />;
  if (error || !data) return <ErrorState message={error || "Dashboard indisponível."} onRetry={reload} />;
  const totalOrders = Object.values(data.orders).reduce((sum, value) => sum + value, 0);
  const activeLicenses = data.licenses.active ?? 0;
  const pendingOutbox = (data.outbox.pending ?? 0) + (data.outbox.processing ?? 0);
  return (
    <>
      <PageHeader
        eyebrow="OPERAÇÃO"
        title="Visão geral do suporte"
        description="Panorama de pedidos, licenças e entregas em toda a operação FortexaHome."
      />
      <div className="stats-grid">
        <StatCard label="Pedidos" value={String(totalOrders)} icon={CreditCard} tone="brand" footnote={`${data.orders.paid ?? 0} pagos`} />
        <StatCard label="Licenças ativas" value={String(activeLicenses)} icon={KeyRound} tone="positive" footnote={`${data.licenses.pending ?? 0} pendentes`} />
        <StatCard label="Entregas na fila" value={String(pendingOutbox)} icon={Mail} tone="neutral" footnote={`${data.outbox.sent ?? 0} enviadas`} />
        <StatCard label="Dead letters" value={String(data.dead_letters)} icon={AlertTriangle} tone={data.dead_letters ? "negative" : "positive"} footnote="Requerem análise operacional" />
      </div>
      <div className="grid-main">
        <Panel title="Pedidos por estado" subtitle="Distribuição comercial atual">
          <div className="support-count-list">
            {Object.entries(data.orders).sort().map(([status, count]) => (
              <Link to={`/backoffice/pedidos?status=${encodeURIComponent(status)}`} className="support-count-row" key={status}>
                <span><CalendarClock size={15} /> {status}</span>
                <b>{count}</b>
              </Link>
            ))}
            {Object.keys(data.orders).length === 0 ? <p className="muted">Nenhum pedido registrado.</p> : null}
          </div>
        </Panel>
        <Panel title="Licenças e outbox" subtitle="Estados que exigem atenção">
          <div className="support-count-list">
            {Object.entries(data.licenses).sort().map(([status, count]) => (
              <Link to={`/backoffice/licencas?status=${encodeURIComponent(status)}`} className="support-count-row" key={status}>
                <span><KeyRound size={15} /> licença {status}</span>
                <b>{count}</b>
              </Link>
            ))}
            {Object.entries(data.outbox).sort().map(([status, count]) => (
              <Link to={`/backoffice/outbox?status=${encodeURIComponent(status)}`} className="support-count-row" key={`o-${status}`}>
                <span><Mail size={15} /> entrega {status}</span>
                <b>{count}</b>
              </Link>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}
