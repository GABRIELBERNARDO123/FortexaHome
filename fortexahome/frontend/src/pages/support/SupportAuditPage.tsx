import { ScrollText } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorState, PageHeader, Panel, Skeleton } from "../../components/ui";
import { useApiData } from "../../lib/useApiData";
import type { PaginatedResponse, SupportAuditItem } from "../../types";
import { Pager, StatusBadge, formatDateTime } from "./shared";

export default function SupportAuditPage() {
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useApiData<PaginatedResponse<SupportAuditItem>>(`/support/audit?page=${page}&page_size=25`);
  return (
    <>
      <PageHeader eyebrow="AUDITORIA" title="Trilha de auditoria" description="Registro append-only das ações administrativas sensíveis. Não editável pela interface." />
      <Panel>
        {loading ? <Skeleton lines={8} /> : error ? <ErrorState message={error} onRetry={reload} /> : !data?.items.length ? (
          <EmptyState icon={ScrollText} title="Nenhuma ação registrada" description="As operações sensíveis do suporte aparecerão aqui." />
        ) : (
          <div className="table-wrap">
            <table className="responsive-table">
              <thead><tr><th>Data</th><th>Operador</th><th>Operação</th><th>Resultado</th><th>Pedido</th><th>Justificativa</th></tr></thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td className="muted-cell" data-label="Data">{formatDateTime(item.created_at)}</td>
                    <td className="muted-cell" data-label="Operador">{item.operator_masked || "—"}</td>
                    <td data-label="Operação"><strong>{item.operation}</strong></td>
                    <td data-label="Resultado"><StatusBadge status={item.result} /></td>
                    <td className="muted-cell mono-input" data-label="Pedido">{item.order_id || "—"}</td>
                    <td className="muted-cell" data-label="Justificativa">{item.justification || "—"}</td>
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
