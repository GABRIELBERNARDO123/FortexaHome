import { KeyRound, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton } from "../../components/ui";
import { useApiData } from "../../lib/useApiData";
import type { PaginatedResponse, SupportLicenseItem } from "../../types";
import { Pager, StatusBadge, formatDateTime } from "./shared";

export default function SupportLicensesPage() {
  const [transaction, setTransaction] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (transaction.trim()) params.set("transaction", transaction.trim());
    if (status) params.set("status", status);
    return params.toString();
  }, [transaction, status, page]);
  const { data, loading, error, reload } = useApiData<PaginatedResponse<SupportLicenseItem>>(`/support/licenses?${query}`);
  useEffect(() => { setPage(1); }, [transaction, status]);
  return (
    <>
      <PageHeader eyebrow="LICENÇAS" title="Licenças" description="Códigos mascarados, estado, pedido e tenant vinculado. Hashes e segredos nunca são exibidos." />
      <Panel className="section-panel">
        <div className="support-filters">
          <div className="search-box"><Search size={16} /><Input value={transaction} onChange={(event) => setTransaction(event.target.value)} placeholder="Transação..." aria-label="Buscar por transação" /></div>
          <Select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filtrar estado da licença">
            <option value="">Todas</option>
            <option value="pending">Pendente</option>
            <option value="active">Ativa</option>
            <option value="suspended">Suspensa</option>
            <option value="cancelled">Cancelada</option>
            <option value="expired">Expirada</option>
          </Select>
        </div>
      </Panel>
      <Panel>
        {loading ? <Skeleton lines={8} /> : error ? <ErrorState message={error} onRetry={reload} /> : !data?.items.length ? (
          <EmptyState icon={KeyRound} title="Nenhuma licença encontrada" description="Ajuste os filtros ou pesquise outra transação." />
        ) : (
          <div className="table-wrap">
            <table className="responsive-table">
              <thead><tr><th>Código</th><th>Produto</th><th>Estado</th><th>Pedido</th><th>Tenant</th><th>Emitida</th><th>Ativada</th></tr></thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td data-label="Código"><span className="mono-input">•••• {item.code_last4}</span></td>
                    <td className="muted-cell" data-label="Produto">{item.product_name}</td>
                    <td data-label="Estado"><StatusBadge status={item.status} /></td>
                    <td className="muted-cell mono-input" data-label="Pedido">{item.transaction || "—"}</td>
                    <td className="muted-cell mono-input" data-label="Tenant">{item.tenant_id || "—"}</td>
                    <td className="muted-cell" data-label="Emitida">{formatDateTime(item.issued_at)}</td>
                    <td className="muted-cell" data-label="Ativada">{formatDateTime(item.activated_at)}</td>
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
