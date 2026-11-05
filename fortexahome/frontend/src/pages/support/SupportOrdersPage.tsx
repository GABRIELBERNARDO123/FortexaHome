import { Eye, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton } from "../../components/ui";
import { useApiData } from "../../lib/useApiData";
import type { PaginatedResponse, SupportOrderListItem } from "../../types";
import { Pager, StatusBadge, formatDateTime } from "./shared";

export default function SupportOrdersPage() {
  const [params, setParams] = useSearchParams();
  const [transaction, setTransaction] = useState("");
  const [status, setStatus] = useState(params.get("status") || "");
  const [licenseStatus, setLicenseStatus] = useState("");
  const [page, setPage] = useState(1);
  const query = useMemo(() => {
    const search = new URLSearchParams({ page: String(page), page_size: "25" });
    if (transaction.trim()) search.set("transaction", transaction.trim());
    if (status) search.set("status", status);
    if (licenseStatus) search.set("license_status", licenseStatus);
    return search.toString();
  }, [transaction, status, licenseStatus, page]);
  const { data, loading, error, reload } = useApiData<PaginatedResponse<SupportOrderListItem>>(`/support/orders?${query}`);
  useEffect(() => { setPage(1); }, [transaction, status, licenseStatus]);
  const updateStatus = (value: string) => {
    setStatus(value);
    const next = new URLSearchParams(params);
    if (value) next.set("status", value); else next.delete("status");
    setParams(next, { replace: true });
  };
  return (
    <>
      <PageHeader eyebrow="PEDIDOS" title="Pedidos e licenças" description="Consulte compras, estados e entregas por transação, produto ou situação." />
      <Panel className="section-panel">
        <div className="support-filters">
          <div className="search-box">
            <Search size={16} />
            <Input value={transaction} onChange={(event) => setTransaction(event.target.value)} placeholder="Transação Hotmart..." aria-label="Buscar transação" />
          </div>
          <Select value={status} onChange={(event) => updateStatus(event.target.value)} aria-label="Filtrar estado do pedido">
            <option value="">Todos os pedidos</option>
            <option value="pending">Pendente</option>
            <option value="paid">Pago</option>
            <option value="refunded">Reembolsado</option>
            <option value="chargeback">Chargeback</option>
            <option value="cancelled">Cancelado</option>
          </Select>
          <Select value={licenseStatus} onChange={(event) => setLicenseStatus(event.target.value)} aria-label="Filtrar estado da licença">
            <option value="">Todas as licenças</option>
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
          <EmptyState icon={Search} title="Nenhum pedido encontrado" description="Ajuste os filtros ou pesquise outra transação." />
        ) : (
          <div className="table-wrap">
            <table className="responsive-table">
              <thead><tr><th>Transação</th><th>Produto</th><th>Pedido</th><th>Licença</th><th>Entrega</th><th>Criado</th><th>Ações</th></tr></thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td data-label="Transação"><div className="table-title mono-input">{item.transaction}</div><small className="row-note">{item.provider}</small></td>
                    <td className="muted-cell" data-label="Produto">{item.product_name}</td>
                    <td data-label="Pedido"><StatusBadge status={item.status} /></td>
                    <td data-label="Licença"><StatusBadge status={item.license_status} /></td>
                    <td data-label="Entrega"><StatusBadge status={item.delivery_status} /></td>
                    <td className="muted-cell" data-label="Criado">{formatDateTime(item.created_at)}</td>
                    <td data-label="Ações"><Link to={`/backoffice/pedidos/${item.id}`} className="btn btn-secondary btn-compact"><Eye size={14} /> Ver</Link></td>
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
