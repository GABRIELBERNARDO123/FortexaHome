import {
  ArrowDownLeft,
  ArrowLeftRight,
  ArrowUpRight,
  LockKeyhole,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
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
  parseBRLAmountToCents,
  todayISO,
} from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type {
  Card,
  Category,
  PaymentMethod,
  Transaction,
  TransactionKind,
  TransactionSummary,
} from "../types";

const PAYMENT_LABELS: Record<PaymentMethod, string> = {
  pix: "Pix",
  cash: "Dinheiro",
  debit: "Débito",
  credit: "Crédito",
  transfer: "Transferência",
  boleto: "Boleto",
  other: "Outro",
};

interface TransactionForm {
  id?: string;
  kind: TransactionKind;
  description: string;
  amount: string;
  occurred_on: string;
  category_id: string;
  payment_method: PaymentMethod;
  card_id: string;
  notes: string;
}

function emptyForm(kind: TransactionKind = "expense"): TransactionForm {
  return {
    kind,
    description: "",
    amount: "",
    occurred_on: todayISO(),
    category_id: "",
    payment_method: "pix",
    card_id: "",
    notes: "",
  };
}

export default function TransactionsPage() {
  const { notify } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [month, setMonth] = useState(currentMonth());
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [kindFilter, setKindFilter] = useState<"" | TransactionKind>("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [form, setForm] = useState<TransactionForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Transaction | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const createIdempotencyKey = useRef<string | null>(null);

  const bounds = monthBounds(month);
  const categories = useApiData<Category[]>("/categories");
  const cards = useApiData<Card[]>("/cards");
  const listPath = useMemo(() => {
    const params = new URLSearchParams({
      start: bounds.start,
      end: bounds.end,
      page_size: "100",
      page: String(page),
    });
    if (deferredSearch.trim()) params.set("search", deferredSearch.trim());
    if (kindFilter) params.set("kind", kindFilter);
    if (categoryFilter) params.set("category_id", categoryFilter);
    return `/transactions?${params.toString()}`;
  }, [bounds.start, bounds.end, deferredSearch, kindFilter, categoryFilter, page]);
  const transactions = useApiData<Transaction[]>(listPath);
  const summary = useApiData<TransactionSummary>(
    `/transactions/summary?start=${bounds.start}&end=${bounds.end}`,
  );

  useEffect(() => {
    setPage(1);
  }, [bounds.start, bounds.end, deferredSearch, kindFilter, categoryFilter]);

  const activeExpenseCategories = (categories.data || []).filter(
    (item) => item.kind === "expense" && !item.archived,
  );
  const activeIncomeCategories = (categories.data || []).filter(
    (item) => item.kind === "income" && !item.archived,
  );
  const selectedArchivedCategory = (categories.data || []).find(
    (item) => item.id === form.category_id && item.archived,
  );
  const activeFormCategories = form.kind === "expense" ? activeExpenseCategories : activeIncomeCategories;
  const formCategories =
    selectedArchivedCategory &&
    !activeFormCategories.some((item) => item.id === selectedArchivedCategory.id)
      ? [...activeFormCategories, selectedArchivedCategory]
      : activeFormCategories;

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
  }, [searchParams, setSearchParams]);

  const openEdit = (transaction: Transaction) => {
    setEditing(transaction);
    setForm({
      id: transaction.id,
      kind: transaction.kind,
      description: transaction.description,
      amount: transaction.amount,
      occurred_on: transaction.occurred_on,
      category_id: transaction.category_id || "",
      payment_method: transaction.payment_method,
      card_id: transaction.card_id || "",
      notes: transaction.notes || "",
    });
    setFormError(null);
    setModalOpen(true);
  };

  const closeModal = () => {
    if (saving) return;
    setModalOpen(false);
    setEditing(null);
  };

  const changeKind = (kind: TransactionKind) => {
    setForm((current) => ({
      ...current,
      kind,
      category_id: "",
      payment_method: kind === "income" && current.payment_method === "credit" ? "pix" : current.payment_method,
      card_id: "",
    }));
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
        kind: form.kind,
        amount: centsToApiDecimal(amountCents),
        occurred_on: form.occurred_on,
        description: form.description.trim(),
        category_id: form.category_id || null,
        payment_method: form.payment_method,
        notes: form.notes.trim() || null,
        card_id: form.payment_method === "credit" && form.card_id ? form.card_id : null,
      };
      if (editing) {
        await api(`/transactions/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        notify("Lançamento atualizado.");
      } else {
        const key = createIdempotencyKey.current ?? newIdempotencyKey();
        createIdempotencyKey.current = key;
        await api("/transactions", {
          method: "POST",
          body: JSON.stringify(payload),
          headers: idempotencyHeaders(key),
        });
        createIdempotencyKey.current = null;
        notify("Lançamento registrado.");
      }
      setModalOpen(false);
      setEditing(null);
      transactions.reload();
      summary.reload();
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteLoading(true);
    try {
      await api(`/transactions/${deleting.id}`, { method: "DELETE" });
      notify("Lançamento excluído.");
      setDeleting(null);
      transactions.reload();
      summary.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="MOVIMENTAÇÕES"
        title="Receitas e despesas"
        description="Registre e acompanhe cada movimentação financeira da casa."
        actions={
          <>
            <MonthNav month={month} onChange={setMonth} />
            <Button variant="primary" icon={Plus} onClick={openCreate}>
              Novo lançamento
            </Button>
          </>
        }
      />

      <div className="mini-stats">
        <div className="mini-stat">
          <span className="mini-icon income">
            <ArrowDownLeft size={17} />
          </span>
          <div>
            <small>Receitas</small>
            <strong>{money(summary.data?.income)}</strong>
          </div>
        </div>
        <div className="mini-stat">
          <span className="mini-icon expense">
            <ArrowUpRight size={17} />
          </span>
          <div>
            <small>Despesas</small>
            <strong>{money(summary.data?.expense)}</strong>
          </div>
        </div>
        <div className="mini-stat">
          <span className={`mini-icon ${Number(summary.data?.result || 0) >= 0 ? "income" : "expense"}`}>
            <ArrowLeftRight size={17} />
          </span>
          <div>
            <small>Resultado do mês</small>
            <strong>{money(summary.data?.result)}</strong>
          </div>
        </div>
        <div className="mini-stat">
          <div>
            <small>Lançamentos</small>
            <strong>{summary.data?.count ?? 0}</strong>
          </div>
        </div>
      </div>

      <Panel className="section-panel">
        <div className="toolbar">
          <div className="search-box">
            <Search size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Buscar por descrição ou observação..."
              aria-label="Buscar lançamento"
            />
          </div>
          <Select
            aria-label="Filtrar por tipo"
            value={kindFilter}
            onChange={(event) => setKindFilter(event.target.value as "" | TransactionKind)}
          >
            <option value="">Todos os tipos</option>
            <option value="income">Receitas</option>
            <option value="expense">Despesas</option>
          </Select>
          <Select
            aria-label="Filtrar por categoria"
            value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value)}
          >
            <option value="">Todas as categorias</option>
            {categories.data?.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}{category.archived ? " (arquivada)" : ""}
              </option>
            ))}
          </Select>
        </div>
      </Panel>

      <Panel>
        {transactions.loading ? (
          <Skeleton lines={7} />
        ) : transactions.error ? (
          <ErrorState message={transactions.error} onRetry={transactions.reload} />
        ) : !transactions.data?.length ? (
          <EmptyState
            icon={ArrowLeftRight}
            title={search || kindFilter || categoryFilter ? "Nada encontrado" : "Nenhum lançamento neste mês"}
            description={
              search || kindFilter || categoryFilter
                ? "Ajuste os filtros ou escolha outro mês para encontrar o que procura."
                : "Comece registrando uma receita ou despesa para dar vida ao seu painel."
            }
            action={
              !search && !kindFilter && !categoryFilter ? (
                <Button variant="primary" icon={Plus} onClick={openCreate}>
                  Registrar lançamento
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="table-wrap">
            <table className="responsive-table">
              <thead>
                <tr>
                  <th>Descrição</th>
                  <th>Tipo</th>
                  <th>Categoria</th>
                  <th>Forma</th>
                  <th>Data</th>
                  <th className="align-right">Valor</th>
                  <th className="align-right">Ações</th>
                </tr>
              </thead>
              <tbody>
                {transactions.data.map((transaction) => {
                  const locked = transaction.source === "bill";
                  return (
                    <tr key={transaction.id}>
                      <td data-label="Descrição">
                        <div className="table-title">
                          <span className={`transaction-dot ${transaction.kind}`} />
                          <div>
                            {transaction.description}
                            {locked ? <small className="row-note">Gerado por conta paga</small> : null}
                          </div>
                        </div>
                      </td>
                      <td data-label="Tipo">
                        <Badge tone={transaction.kind === "income" ? "good" : "warn"}>
                          {transaction.kind === "income" ? "Receita" : "Despesa"}
                        </Badge>
                      </td>
                      <td className="muted-cell" data-label="Categoria">{transaction.category_name || "Sem categoria"}</td>
                      <td className="muted-cell" data-label="Forma">{PAYMENT_LABELS[transaction.payment_method]}</td>
                      <td className="muted-cell" data-label="Data">{dateLabel(transaction.occurred_on)}</td>
                      <td className={`align-right amount ${transaction.kind}`} data-label="Valor">
                        {transaction.kind === "income" ? "+" : "−"} {money(transaction.amount)}
                      </td>
                      <td data-label="Ações">
                        <div className="row-actions">
                          {locked ? (
                            <span className="lock-note" title="Edite pela tela de contas a pagar">
                              <LockKeyhole size={15} />
                            </span>
                          ) : (
                            <>
                              <IconButton label="Editar lançamento" icon={Pencil} onClick={() => openEdit(transaction)} />
                              <IconButton
                                label="Excluir lançamento"
                                icon={Trash2}
                                className="danger-icon"
                                onClick={() => setDeleting(transaction)}
                              />
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {transactions.data?.length ? (
          <div className="toolbar" style={{ justifyContent: "flex-end", marginTop: 12 }}>
            <Button disabled={page === 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
              Anterior
            </Button>
            <span className="muted">Página {page}</span>
            <Button disabled={(transactions.data?.length || 0) < 100} onClick={() => setPage((current) => current + 1)}>
              Próxima
            </Button>
          </div>
        ) : null}
      </Panel>

      <Modal
        open={modalOpen}
        onClose={closeModal}
        title={editing ? "Editar lançamento" : "Novo lançamento"}
        subtitle="Registre uma movimentação para manter o painel sempre atualizado."
        footer={
          <>
            <Button variant="ghost" onClick={closeModal} disabled={saving}>
              Cancelar
            </Button>
            <Button variant="primary" type="submit" form="transaction-form" loading={saving}>
              {editing ? "Salvar alterações" : "Registrar lançamento"}
            </Button>
          </>
        }
      >
        <form id="transaction-form" onSubmit={submit} className="form-stack">
          <div className="segmented">
            <button
              type="button"
              className={form.kind === "expense" ? "active expense" : undefined}
              onClick={() => changeKind("expense")}
            >
              <ArrowUpRight size={15} /> Despesa
            </button>
            <button
              type="button"
              className={form.kind === "income" ? "active income" : undefined}
              onClick={() => changeKind("income")}
            >
              <ArrowDownLeft size={15} /> Receita
            </button>
          </div>
          <div className="form-grid">
            <Field label="Descrição" className="span-2">
              <Input
                required
                maxLength={180}
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                placeholder="Ex.: Mercado da semana"
              />
            </Field>
            <Field label="Valor (R$)">
              <Input
                required
                inputMode="decimal"
                value={form.amount}
                onChange={(event) => setForm({ ...form, amount: event.target.value })}
                placeholder="0,00"
              />
            </Field>
            <Field label="Data">
              <Input
                type="date"
                required
                value={form.occurred_on}
                onChange={(event) => setForm({ ...form, occurred_on: event.target.value })}
              />
            </Field>
            <Field label="Categoria">
              <Select
                value={form.category_id}
                onChange={(event) => setForm({ ...form, category_id: event.target.value })}
              >
                <option value="">Sem categoria</option>
                {formCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}{category.archived ? " (arquivada)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Forma de pagamento">
              <Select
                value={form.payment_method}
                onChange={(event) => {
                  const payment = event.target.value as PaymentMethod;
                  setForm({
                    ...form,
                    payment_method: payment,
                    card_id: payment === "credit" ? form.card_id : "",
                  });
                }}
              >
                {(Object.keys(PAYMENT_LABELS) as PaymentMethod[])
                  .filter((method) => form.kind !== "income" || method !== "credit")
                  .map((method) => (
                    <option key={method} value={method}>
                      {PAYMENT_LABELS[method]}
                    </option>
                  ))}
              </Select>
            </Field>
            {form.kind === "expense" && form.payment_method === "credit" ? (
              <Field label="Cartão" hint="Opcional. Ajuda a acompanhar a fatura.">
                <Select value={form.card_id} onChange={(event) => setForm({ ...form, card_id: event.target.value })}>
                  <option value="">Não vincular</option>
                  {cards.data
                    ?.filter((card) => !card.archived)
                    .map((card) => (
                      <option key={card.id} value={card.id}>
                        {card.name} · {card.institution}
                      </option>
                    ))}
                </Select>
              </Field>
            ) : null}
            <Field label="Observações" className="span-2">
              <Textarea
                rows={3}
                maxLength={2000}
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
                placeholder="Algum detalhe importante sobre esta movimentação?"
              />
            </Field>
          </div>
          {formError ? <div className="form-error">{formError}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Excluir lançamento?"
        description={`"${deleting?.description || ""}" será removido permanentemente. Esta ação não pode ser desfeita.`}
        confirmLabel="Excluir"
        danger
        loading={deleteLoading}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
