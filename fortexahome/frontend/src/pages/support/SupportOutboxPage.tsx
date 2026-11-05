import { Mail, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton } from "../../components/ui";
import { useApiData } from "../../lib/useApiData";
import type { PaginatedResponse, SupportOutboxItem } from "../../types";
import { Pager, StatusBadge, formatDateTime } from "./shared";

export default function SupportOutboxPage() {
  const [transaction, setTransaction] = useState("");
  const [status, setStatus] = useState("");
  const [eventType, setEventType] = useState("");
  const [page, setPage] = useState(1);
  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (transaction.trim()) params.set("transaction", transaction.trim());
    if (status) params.set("status", status);
    if (eventType) params.set("event_type", eventType);
    return params.toString();
  }, [transaction, status, eventType, page]);
  const { data, loading, error, reload } = useApiData<PaginatedResponse<SupportOutboxItem>>(`/support/outbox?${query}`);
  useEffect(() => { setPage(1); }, [transaction, status, eventType]);
  return (
    <>
      <PageHeader eyebrow="ENTREGAS" title="Transactional outbox" description="Metadados de envio. Payloads criptografados e descriptografados nunca são exibidos." />
      <Panel className="section-panel">
        <div className="support-filters">
          <div className="search-box"><Search size={16} /><Input value={transaction} onChange={(event) => setTransaction(event.target.value)} placeholder="Transação..." aria-label="Buscar por transação" /></div>
          <Select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filtrar estado">
            <option value="">Todos os estados</option>
            {["pending", "processing", "sent", "dead", "cancelled"].map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
          <Select value={eventType} onChange={(event) => setEventType(event.target.value)} aria-label="Filtrar tipo de evento">
            <option value="">Todos os eventos</option>
            {["license_delivery", "activation_verification", "password_reset", "license_recovery_instructions"].map((item) => <option key={item} value={item}>{item}</option>)}
          </Select>
        </div>
        <p className="support-note">Mensagens <strong>dead</strong> exigem análise e recuperação manual pelo procedimento de host documentado. Não há requeue genérico na interface.</p>
      </Panel>
      <Panel>
        {loading ? <Skeleton lines={8} /> : error ? <ErrorState message={error} onRetry={reload} /> : !data?.items.length ? (
          <EmptyState icon={Mail} title="Nenhuma mensagem encontrada" description="Ajuste os filtros ou pesquise outra transação." />
        ) : (
          <div className="table-wrap">
            <table className="responsive-table">
              <thead><tr><th>Evento</th><th>Estado</th><th>Pedido</th><th>Tentativas</th><th>Próxima</th><th>Processada</th><th>Erro</th></tr></thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td data-label="Evento"><strong>{item.event_type}</strong><small className="row-note">{formatDateTime(item.created_at)}</small></td>
                    <td data-label="Estado"><StatusBadge status={item.status} /></td>
                    <td className="muted-cell mono-input" data-label="Pedido">{item.transaction || item.aggregate_id || "—"}</td>
                    <td className="muted-cell" data-label="Tentativas">{item.attempt_count}/{item.max_attempts}</td>
                    <td className="muted-cell" data-label="Próxima">{formatDateTime(item.next_attempt_at)}</td>
                    <td className="muted-cell" data-label="Processada">{formatDateTime(item.processed_at || item.sent_at)}</td>
                    <td className="muted-cell" data-label="Erro">{item.last_error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data ? <Pager page={page} pageSize={25} total={data.total} onChange={setPage} /> : null}
      </Panel>
    </>
  );
}
