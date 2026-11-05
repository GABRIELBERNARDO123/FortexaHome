import { CheckCircle2, Eye, ShieldCheck, XCircle } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Modal,
  PageHeader,
  Panel,
  Select,
  Skeleton,
  Textarea,
} from "../../components/ui";
import { useSupportAuth } from "../../context/SupportAuthContext";
import { useToast } from "../../context/ToastContext";
import { api, errorMessage } from "../../lib/api";
import { useApiData } from "../../lib/useApiData";
import type { PaginatedResponse, PrivacyRequest, PrivacyRequestDetail } from "../../types";
import { formatDateTime, Pager, StatusBadge } from "./shared";

type Action = "approve" | "reject" | null;

export default function SupportPrivacyPage() {
  const { auth } = useSupportAuth();
  const { notify } = useToast();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [action, setAction] = useState<Action>(null);
  const [justification, setJustification] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const canAct = auth?.permissions.includes("support:act");
  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: "25" });
    if (status) params.set("status", status);
    return params.toString();
  }, [page, status]);
  const list = useApiData<PaginatedResponse<PrivacyRequest>>(`/support/privacy/requests?${query}`);
  const detail = useApiData<PrivacyRequestDetail>(selected ? `/support/privacy/requests/${selected}` : null);

  const submitAction = async () => {
    if (!selected || !action) return;
    setSending(true);
    setActionError(null);
    try {
      await api(`/support/privacy/requests/${selected}/${action}`, {
        method: "POST",
        body: JSON.stringify({ justification }),
      });
      notify(action === "approve" ? "Solicitação aprovada e executada." : "Solicitação rejeitada com justificativa.");
      setAction(null);
      setJustification("");
      list.reload();
      detail.reload();
    } catch (caught) {
      setActionError(errorMessage(caught));
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="PRIVACIDADE"
        title="Solicitações de titulares"
        description="Acompanhe exclusões e demais pedidos de privacidade. Ações exigem justificativa e são auditadas."
      />
      <Panel className="section-panel">
        <div className="support-filters">
          <Select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }} aria-label="Filtrar status da solicitação">
            <option value="">Todos os status</option>
            <option value="awaiting_review">Aguardando análise</option>
            <option value="completed">Concluída</option>
            <option value="rejected">Rejeitada</option>
            <option value="cancelled">Cancelada</option>
          </Select>
        </div>
      </Panel>
      <Panel>
        {list.loading ? <Skeleton lines={8} /> : list.error ? <ErrorState message={list.error} onRetry={list.reload} /> : !list.data?.items.length ? (
          <EmptyState icon={ShieldCheck} title="Nenhuma solicitação" description="Pedidos de privacidade aparecerão aqui." />
        ) : (
          <div className="table-wrap">
            <table className="responsive-table">
              <thead><tr><th>Protocolo</th><th>Tipo</th><th>Escopo</th><th>Status</th><th>Criada</th><th>Ações</th></tr></thead>
              <tbody>
                {list.data.items.map((item) => (
                  <tr key={item.id}>
                    <td data-label="Protocolo"><strong className="mono-input">{item.protocol}</strong></td>
                    <td data-label="Tipo">{item.request_type}</td>
                    <td data-label="Escopo">{item.scope}</td>
                    <td data-label="Status"><StatusBadge status={item.status} /></td>
                    <td className="muted-cell" data-label="Criada">{formatDateTime(item.created_at)}</td>
                    <td data-label="Ações">
                      <div className="row-actions">
                        <Button variant="secondary" icon={Eye} onClick={() => setSelected(item.id)}>Detalhe</Button>
                        {canAct && ["submitted", "awaiting_review", "approved"].includes(item.status) ? (
                          <>
                            <Button variant="primary" icon={CheckCircle2} onClick={() => { setSelected(item.id); setAction("approve"); setJustification(""); setActionError(null); }}>Aprovar</Button>
                            <Button variant="secondary" icon={XCircle} onClick={() => { setSelected(item.id); setAction("reject"); setJustification(""); setActionError(null); }}>Rejeitar</Button>
                          </>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.data ? <Pager page={page} pageSize={25} total={list.data.total} onChange={setPage} /> : null}
      </Panel>

      <Modal
        open={Boolean(selected) && action === null}
        onClose={() => setSelected(null)}
        title="Detalhe da solicitação"
        subtitle="Dados minimizados, retenção e histórico de etapas."
      >
        {detail.loading ? <Skeleton lines={5} /> : detail.error || !detail.data ? <ErrorState message={detail.error || "Solicitação indisponível."} /> : (
          <div className="support-detail-list">
            <div><dt>Protocolo</dt><dd className="mono-input">{detail.data.protocol}</dd></div>
            <div><dt>Status</dt><dd><StatusBadge status={detail.data.status} /></dd></div>
            <div><dt>Escopo</dt><dd>{detail.data.scope}</dd></div>
            <div><dt>Resultado</dt><dd>{detail.data.result_summary || "—"}</dd></div>
            <div><dt>Justificativa</dt><dd>{detail.data.review_justification || "—"}</dd></div>
            <div><dt>Concluída</dt><dd>{formatDateTime(detail.data.completed_at)}</dd></div>
            <div><dt>Retenção</dt><dd>{detail.data.retention_summary ? JSON.stringify(detail.data.retention_summary) : "—"}</dd></div>
            <div><dt>Eventos</dt><dd>{detail.data.events.map((event) => `${event.event_type} (${event.actor_type})`).join(" · ")}</dd></div>
          </div>
        )}
      </Modal>

      <Modal
        open={action !== null}
        onClose={() => !sending && setAction(null)}
        title={action === "approve" ? "Aprovar solicitação" : "Rejeitar solicitação"}
        subtitle="A ação é registrada com operador, data, resultado e justificativa. Aprovar executa a exclusão/anonimização permitida pela política."
        footer={
          <>
            <Button variant="ghost" onClick={() => setAction(null)} disabled={sending}>Cancelar</Button>
            <Button variant="primary" onClick={() => void submitAction()} loading={sending} disabled={justification.trim().length < 10}>
              {action === "approve" ? "Aprovar e executar" : "Rejeitar"}
            </Button>
          </>
        }
      >
        <Field label="Justificativa" hint="Obrigatória, mínimo de 10 caracteres. Não inclua dados pessoais desnecessários.">
          <Textarea rows={4} maxLength={500} value={justification} onChange={(event) => setJustification(event.target.value)} />
        </Field>
        {actionError ? <div className="form-error" role="alert">{actionError}</div> : null}
        <div className="support-note">
          <Badge tone="warn">Ação auditada</Badge> O sistema bloqueia aprovação automática de tenant com outros usuários ativos.
        </div>
      </Modal>
    </>
  );
}
