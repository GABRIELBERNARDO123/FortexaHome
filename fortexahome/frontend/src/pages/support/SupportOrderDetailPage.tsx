import { ArrowLeft, MailCheck, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Badge, Button, ErrorState, Field, Modal, PageHeader, Panel, Skeleton, Textarea } from "../../components/ui";
import { useSupportAuth } from "../../context/SupportAuthContext";
import { useToast } from "../../context/ToastContext";
import { api, errorMessage } from "../../lib/api";
import { useApiData } from "../../lib/useApiData";
import type { SupportOrderDetail } from "../../types";
import { StatusBadge, formatDateTime, moneyFromCents } from "./shared";

export default function SupportOrderDetailPage() {
  const { orderId } = useParams();
  const { auth } = useSupportAuth();
  const { notify } = useToast();
  const { data, loading, error, reload } = useApiData<SupportOrderDetail>(orderId ? `/support/orders/${orderId}` : null);
  const [open, setOpen] = useState(false);
  const [justification, setJustification] = useState("");
  const [sending, setSending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const canAct = auth?.permissions.includes("support:act");

  const sendInstructions = async () => {
    if (!orderId) return;
    setSending(true);
    setActionError(null);
    try {
      await api(`/support/orders/${orderId}/recovery-instructions`, {
        method: "POST",
        body: JSON.stringify({ justification }),
      });
      notify("Instruções de recuperação enfileiradas.");
      setOpen(false);
      setJustification("");
      reload();
    } catch (caught) {
      setActionError(errorMessage(caught));
    } finally {
      setSending(false);
    }
  };

  if (loading) return <Skeleton lines={10} />;
  if (error || !data) return <ErrorState message={error || "Pedido não encontrado."} onRetry={reload} />;
  return (
    <>
      <PageHeader
        eyebrow="DETALHE DO PEDIDO"
        title={data.order.transaction}
        description={`Pedido ${data.order.provider} · ${formatDateTime(data.order.created_at)}`}
        actions={
          <div className="page-actions">
            <Link to="/backoffice/pedidos" className="btn btn-ghost"><ArrowLeft size={15} /> Voltar</Link>
            <Button variant="secondary" icon={RefreshCw} onClick={reload}>Atualizar</Button>
            {canAct ? <Button variant="primary" icon={MailCheck} onClick={() => setOpen(true)}>Solicitar recuperação</Button> : null}
          </div>
        }
      />
      <div className="grid-main">
        <Panel title="Pedido" subtitle="Estado comercial atual">
          <dl className="support-detail-list">
            <div><dt>Transação</dt><dd className="mono-input">{data.order.transaction}</dd></div>
            <div><dt>Produto</dt><dd>{data.product.name}</dd></div>
            <div><dt>Valor interno</dt><dd>{moneyFromCents(data.order.amount_cents, data.order.currency)}</dd></div>
            <div><dt>Pedido</dt><dd><StatusBadge status={data.order.status} /></dd></div>
            <div><dt>Comprador</dt><dd>{data.order.buyer_email_masked || "—"}</dd></div>
            <div><dt>Criado em</dt><dd>{formatDateTime(data.order.created_at)}</dd></div>
            <div><dt>Última atualização</dt><dd>{formatDateTime(data.order.updated_at)}</dd></div>
          </dl>
        </Panel>
        <Panel title="Licença" subtitle="Vínculo de acesso">
          {data.license ? (
            <dl className="support-detail-list">
              <div><dt>Código mascarado</dt><dd>•••• {data.license.code_last4}</dd></div>
              <div><dt>Estado</dt><dd><StatusBadge status={data.license.status} /></dd></div>
              <div><dt>Tenant vinculado</dt><dd className="mono-input">{data.license.tenant_id || "Não ativada"}</dd></div>
              <div><dt>Emitida</dt><dd>{formatDateTime(data.license.issued_at)}</dd></div>
              <div><dt>Ativada</dt><dd>{formatDateTime(data.license.activated_at)}</dd></div>
              <div><dt>Revogada</dt><dd>{formatDateTime(data.license.revoked_at)}</dd></div>
            </dl>
          ) : <p className="muted">Nenhuma licença vinculada.</p>}
        </Panel>
      </div>
      <div className="grid-main">
        <Panel title="Eventos comerciais" subtitle="Histórico cronológico">
          {data.events.length === 0 ? <p className="muted">Nenhum evento registrado.</p> : (
            <div className="support-timeline">
              {data.events.map((event, index) => (
                <div className="support-timeline-item" key={`${event.event_type}-${index}`}>
                  <span className="support-timeline-dot" />
                  <div>
                    <strong>{event.event_type}</strong>
                    <small>{formatDateTime(event.provider_event_created_at || event.processed_at)} · prioridade {event.state_priority}</small>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
        <Panel title="Entregas" subtitle="Transactional outbox relacionada">
          {data.deliveries.length === 0 ? <p className="muted">Nenhuma mensagem de entrega.</p> : (
            <div className="support-delivery-list">
              {data.deliveries.map((delivery) => (
                <div className="support-delivery" key={delivery.id}>
                  <div className="support-delivery-head">
                    <strong>{delivery.event_type}</strong>
                    <StatusBadge status={delivery.status} />
                  </div>
                  <small>
                    {delivery.attempt_count}/{delivery.max_attempts} tentativa(s) · criada {formatDateTime(delivery.created_at)}
                  </small>
                  {delivery.last_error ? <span className="support-error">Erro: {delivery.last_error}</span> : null}
                  {delivery.status === "dead" ? (
                    <span className="support-note">Dead letter: recuperação manual somente pelo procedimento de host documentado.</span>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
      <Modal
        open={open}
        onClose={() => !sending && setOpen(false)}
        title="Solicitar instruções de recuperação"
        subtitle="Um e-mail será enviado ao comprador com orientações seguras. O código da licença não é revelado."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={sending}>Cancelar</Button>
            <Button variant="primary" onClick={() => void sendInstructions()} loading={sending} disabled={justification.trim().length < 10}>Enviar instruções</Button>
          </>
        }
      >
        <Field label="Justificativa" hint="Obrigatória, mínimo de 10 caracteres. Fica registrada na auditoria.">
          <Textarea rows={4} maxLength={500} value={justification} onChange={(event) => setJustification(event.target.value)} placeholder="Ex.: Cliente confirmou por telefone que perdeu o e-mail original." />
        </Field>
        {actionError ? <div className="form-error" role="alert">{actionError}</div> : null}
        <div className="support-note">
          <Badge tone="warn">Ação auditada</Badge> A operação não altera valores, não reativa licenças e não expõe tokens ou payloads.
        </div>
      </Modal>
    </>
  );
}
