import {
  CalendarClock,
  CheckCircle2,
  CircleDollarSign,
  Pencil,
  Plus,
  ReceiptText,
  RotateCw,
  Trash2,
  Undo2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  IconButton,
  Input,
  Modal,
  MonthNav,
  PageHeader,
  Panel,
  Select,
  Skeleton,
  StatCard,
  Textarea,
} from "../components/ui";
import { useToast } from "../context/ToastContext";
import { api, errorMessage, idempotencyHeaders, newIdempotencyKey } from "../lib/api";
import {
  centsToApiDecimal,
  currentMonth,
  dateLabel,
  money,
  monthBounds,
  number,
  parseBRLAmountToCents,
  todayISO,
} from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type { Bill, Category } from "../types";

interface BillForm {
  id?: string;
  name: string;
  amount: string;
  due_on: string;
  category_id: string;
  recurrence: "none" | "monthly";
  notes: string;
}

function emptyForm(): BillForm {
  return {
    name: "",
    amount: "",
    due_on: todayISO(),
    category_id: "",
    recurrence: "none",
    notes: "",
  };
}

export default function BillsPage() {
  const { notify } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [month, setMonth] = useState(currentMonth());
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Bill | null>(null);
  const [form, setForm] = useState<BillForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Bill | null>(null);
  const [actionId, setActionId] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const createIdempotencyKey = useRef<string | null>(null);
  const actionIdempotencyKeys = useRef<Record<string, string>>({});

  const bounds = monthBounds(month);
  const bills = useApiData<Bill[]>(`/bills?start=${bounds.start}&end=${bounds.end}`);
  const categories = useApiData<Category[]>("/categories?kind=expense");

  const stats = useMemo(() => {
    const rows = bills.data || [];
    const pending = rows.filter((bill) => bill.status === "pending");
    const paid = rows.filter((bill) => bill.status === "paid");
    return {
      pendingTotal: pending.reduce((sum, bill) => sum + number(bill.amount), 0),
      paidTotal: paid.reduce((sum, bill) => sum + number(bill.amount), 0),
      overdue: pending.filter((bill) => bill.is_overdue).length,
      pending: pending.length,
      paid: paid.length,
    };
  }, [bills.data]);

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setFormError(null);
    createIdempotencyKey.current = null;
    setModalOpen(true);
  };

  useEffect(() => {
    if (searchParams.get("novo") === "1") {
      openCreate();
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openEdit = (bill: Bill) => {
    setEditing(bill);
    setForm({
      id: bill.id,
      name: bill.name,
      amount: bill.amount,
      due_on: bill.due_on,
      category_id: bill.category_id || "",
      recurrence: bill.recurrence,
      notes: bill.notes || "",
    });
    setFormError(null);
    setModalOpen(true);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const amountCents = parseBRLAmountToCents(form.amount);
    if (amountCents === null) {
      setFormError("Informe um valor maior que zero. Use vírgula para centavos. Ex.: 1.500,00");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        amount: centsToApiDecimal(amountCents),
        due_on: form.due_on,
        category_id: form.category_id || null,
        recurrence: form.recurrence,
        notes: form.notes.trim() || null,
      };
      if (editing) {
        await api(`/bills/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        notify("Conta atualizada.");
      } else {
        const key = createIdempotencyKey.current ?? newIdempotencyKey();
        createIdempotencyKey.current = key;
        await api("/bills", {
          method: "POST",
          body: JSON.stringify(payload),
          headers: idempotencyHeaders(key),
        });
        createIdempotencyKey.current = null;
        notify("Conta adicionada à agenda.");
      }
      setModalOpen(false);
      setEditing(null);
      bills.reload();
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const togglePaid = async (bill: Bill) => {
    setActionId(bill.id);
    const action = bill.status === "paid" ? "unpay" : "pay";
    const keyName = `${bill.id}:${action}`;
    const key = actionIdempotencyKeys.current[keyName] ?? newIdempotencyKey();
    actionIdempotencyKeys.current[keyName] = key;
    try {
      if (action === "unpay") {
        await api(`/bills/${bill.id}/unpay`, {
          method: "POST",
          headers: idempotencyHeaders(key),
        });
        notify("Pagamento desfeito. A despesa vinculada foi removida.");
      } else {
        await api(`/bills/${bill.id}/pay`, {
          method: "POST",
          headers: idempotencyHeaders(key),
        });
        notify("Conta marcada como paga e despesa registrada.");
      }
      delete actionIdempotencyKeys.current[keyName];
      bills.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setActionId(null);
    }
  };

  const createRecurrence = async (bill: Bill) => {
    setActionId(bill.id);
    try {
      await api(`/bills/${bill.id}/recurrence`, { method: "POST" });
      notify("Próxima conta recorrente criada.");
      bills.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setActionId(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteLoading(true);
    try {
      await api(`/bills/${deleting.id}`, { method: "DELETE" });
      notify("Conta excluída.");
      setDeleting(null);
      bills.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="ORGANIZAÇÃO"
        title="Contas a pagar"
        description="Visualize vencimentos e acompanhe o que já foi pago."
        actions={
          <>
            <MonthNav month={month} onChange={setMonth} />
            <Button variant="primary" icon={Plus} onClick={openCreate}>
              Nova conta
            </Button>
          </>
        }
      />

      <div className="stats-grid">
        <StatCard
          label="A pagar no mês"
          value={money(stats.pendingTotal)}
          icon={CalendarClock}
          tone={stats.overdue ? "negative" : "brand"}
          footnote={`${stats.pending} conta(s) pendente(s)`}
        />
        <StatCard
          label="Já pago no mês"
          value={money(stats.paidTotal)}
          icon={CheckCircle2}
          tone="positive"
          footnote={`${stats.paid} conta(s) quitada(s)`}
        />
        <StatCard
          label="Vencidas"
          value={String(stats.overdue)}
          icon={ReceiptText}
          tone={stats.overdue ? "negative" : "neutral"}
          footnote={stats.overdue ? "Priorize estas contas" : "Nenhuma conta atrasada"}
        />
        <StatCard
          label="Total do mês"
          value={money(stats.pendingTotal + stats.paidTotal)}
          icon={CircleDollarSign}
          tone="neutral"
          footnote="Pendentes + pagas"
        />
      </div>

      <Panel>
        {bills.loading ? (
          <Skeleton lines={7} />
        ) : bills.error ? (
          <ErrorState message={bills.error} onRetry={bills.reload} />
        ) : !bills.data?.length ? (
          <EmptyState
            icon={ReceiptText}
            title="Nenhuma conta neste mês"
            description="Cadastre aluguel, energia, internet e outras contas para nunca perder um vencimento."
            action={
              <Button variant="primary" icon={Plus} onClick={openCreate}>
                Cadastrar conta
              </Button>
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="responsive-table">
              <thead>
                <tr>
                  <th>Conta</th>
                  <th>Vencimento</th>
                  <th>Categoria</th>
                  <th>Recorrência</th>
                  <th className="align-right">Valor</th>
                  <th>Status</th>
                  <th className="align-right">Ações</th>
                </tr>
              </thead>
              <tbody>
                {bills.data.map((bill) => (
                  <tr key={bill.id}>
                    <td data-label="Conta">
                      <div className="table-title">{bill.name}</div>
                      {bill.notes ? <small className="row-note">{bill.notes}</small> : null}
                    </td>
                    <td className="muted-cell" data-label="Vencimento">{dateLabel(bill.due_on)}</td>
                    <td className="muted-cell" data-label="Categoria">{bill.category_name || "Sem categoria"}</td>
                    <td className="muted-cell" data-label="Recorrência">{bill.recurrence === "monthly" ? "Mensal" : "Única"}</td>
                    <td className="align-right amount" data-label="Valor">{money(bill.amount)}</td>
                    <td data-label="Status">
                      {bill.status === "paid" ? (
                        <Badge tone="good">Paga</Badge>
                      ) : bill.is_overdue ? (
                        <Badge tone="bad">Vencida</Badge>
                      ) : (
                        <Badge tone="warn">A vencer</Badge>
                      )}
                    </td>
                    <td data-label="Ações">
                      <div className="row-actions">
                        <Button
                          variant={bill.status === "paid" ? "ghost" : "secondary"}
                          className="btn-compact"
                          loading={actionId === bill.id}
                          icon={bill.status === "paid" ? Undo2 : CheckCircle2}
                          onClick={() => void togglePaid(bill)}
                        >
                          {bill.status === "paid" ? "Desfazer" : "Pagar"}
                        </Button>
                        {bill.recurrence === "monthly" ? (
                          <IconButton
                            label="Gerar próxima recorrência"
                            icon={RotateCw}
                            onClick={() => void createRecurrence(bill)}
                            disabled={actionId === bill.id}
                          />
                        ) : null}
                        <IconButton label="Editar conta" icon={Pencil} onClick={() => openEdit(bill)} />
                        <IconButton
                          label="Excluir conta"
                          icon={Trash2}
                          className="danger-icon"
                          onClick={() => setDeleting(bill)}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Modal
        open={modalOpen}
        onClose={() => !saving && setModalOpen(false)}
        title={editing ? "Editar conta" : "Nova conta a pagar"}
        subtitle="Organize o vencimento e receba o valor no fluxo ao marcar como paga."
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)} disabled={saving}>
              Cancelar
            </Button>
            <Button variant="primary" type="submit" form="bill-form" loading={saving}>
              {editing ? "Salvar alterações" : "Adicionar conta"}
            </Button>
          </>
        }
      >
        <form id="bill-form" onSubmit={submit} className="form-stack">
          <div className="form-grid">
            <Field label="Nome da conta" className="span-2">
              <Input
                required
                maxLength={160}
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="Ex.: Aluguel, energia, escola..."
              />
            </Field>
            <Field label="Valor (R$)">
              <Input
                required
                inputMode="decimal"
                value={form.amount}
                onChange={(event) => setForm({ ...form, amount: event.target.value })}
                placeholder="0,00"
                disabled={editing?.status === "paid"}
              />
            </Field>
            <Field label="Vencimento">
              <Input
                type="date"
                required
                value={form.due_on}
                onChange={(event) => setForm({ ...form, due_on: event.target.value })}
                disabled={editing?.status === "paid"}
              />
            </Field>
            <Field label="Categoria">
              <Select
                value={form.category_id}
                onChange={(event) => setForm({ ...form, category_id: event.target.value })}
              >
                <option value="">Sem categoria</option>
                {(categories.data || [])
                  .filter((category) => !category.archived || category.id === form.category_id)
                  .map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}{category.archived ? " (arquivada)" : ""}
                    </option>
                  ))}
              </Select>
            </Field>
            <Field label="Recorrência">
              <Select
                value={form.recurrence}
                onChange={(event) =>
                  setForm({ ...form, recurrence: event.target.value as "none" | "monthly" })
                }
              >
                <option value="none">Conta única</option>
                <option value="monthly">Mensal</option>
              </Select>
            </Field>
            <Field label="Observações" className="span-2">
              <Textarea
                rows={3}
                maxLength={2000}
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
                placeholder="Código de barras, detalhes ou lembretes..."
              />
            </Field>
          </div>
          {editing?.status === "paid" ? (
            <div className="form-hint">Para alterar valor ou vencimento, desfaça o pagamento primeiro.</div>
          ) : null}
          {formError ? <div className="form-error">{formError}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Excluir conta?"
        description={`"${deleting?.name || ""}" será removida da sua agenda. Contas pagas precisam ter o pagamento desfeito antes.`}
        confirmLabel="Excluir"
        danger
        loading={deleteLoading}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
