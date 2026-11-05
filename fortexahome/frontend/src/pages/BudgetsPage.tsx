import { Pencil, PieChart, Plus, Target, Trash2, Wallet } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

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
  Progress,
  Select,
  Skeleton,
  StatCard,
} from "../components/ui";
import { useToast } from "../context/ToastContext";
import { api, errorMessage } from "../lib/api";
import {
  centsToApiDecimal,
  clampPercent,
  currentMonth,
  money,
  monthLabel,
  number,
  parseBRLAmountToCents,
} from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type { Budget, Category } from "../types";

export default function BudgetsPage() {
  const { notify } = useToast();
  const [month, setMonth] = useState(currentMonth());
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Budget | null>(null);
  const [categoryId, setCategoryId] = useState("");
  const [limitAmount, setLimitAmount] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Budget | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const budgets = useApiData<Budget[]>(`/budgets?month=${month}`);
  const categories = useApiData<Category[]>("/categories?kind=expense");

  const stats = useMemo(() => {
    const rows = budgets.data || [];
    const planned = rows.reduce((sum, item) => sum + number(item.limit_amount), 0);
    const spent = rows.reduce((sum, item) => sum + number(item.spent), 0);
    return {
      planned,
      spent,
      available: planned - spent,
      count: rows.length,
      over: rows.filter((item) => number(item.spent) > number(item.limit_amount)).length,
    };
  }, [budgets.data]);

  const usedCategoryIds = new Set((budgets.data || []).map((item) => item.category_id));
  const availableCategories = (categories.data || []).filter(
    (category) => !category.archived && !usedCategoryIds.has(category.id),
  );

  const openCreate = () => {
    setEditing(null);
    setCategoryId(availableCategories[0]?.id || "");
    setLimitAmount("");
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (budget: Budget) => {
    setEditing(budget);
    setCategoryId(budget.category_id);
    setLimitAmount(budget.limit_amount);
    setFormError(null);
    setModalOpen(true);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const limitCents = parseBRLAmountToCents(limitAmount);
    if (limitCents === null) {
      setFormError("Informe um limite maior que zero. Use vírgula para centavos. Ex.: 1.500,00");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await api(`/budgets/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify({ limit_amount: centsToApiDecimal(limitCents) }),
        });
        notify("Limite atualizado.");
      } else {
        if (!categoryId) {
          setFormError("Escolha uma categoria.");
          setSaving(false);
          return;
        }
        await api("/budgets", {
          method: "POST",
          body: JSON.stringify({
            category_id: categoryId,
            competence_month: `${month}-01`,
            limit_amount: centsToApiDecimal(limitCents),
          }),
        });
        notify("Limite de orçamento definido.");
      }
      setModalOpen(false);
      budgets.reload();
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
      await api(`/budgets/${deleting.id}`, { method: "DELETE" });
      notify("Limite removido.");
      setDeleting(null);
      budgets.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="PLANEJAMENTO"
        title="Orçamento familiar"
        description="Defina limites para gastar com consciência e tranquilidade."
        actions={
          <>
            <MonthNav month={month} onChange={setMonth} />
            <Button
              variant="primary"
              icon={Plus}
              onClick={openCreate}
              disabled={availableCategories.length === 0}
            >
              Definir limite
            </Button>
          </>
        }
      />

      <div className="stats-grid">
        <StatCard
          label="Planejado"
          value={money(stats.planned)}
          icon={PieChart}
          tone="brand"
          footnote={`${stats.count} categoria(s) com limite`}
        />
        <StatCard
          label="Gasto"
          value={money(stats.spent)}
          icon={Wallet}
          tone="negative"
          footnote={`${monthLabel(month)}`}
        />
        <StatCard
          label="Disponível"
          value={money(stats.available)}
          icon={Target}
          tone={stats.available >= 0 ? "positive" : "negative"}
          footnote={stats.available >= 0 ? "Ainda dentro do plano" : "Orçamento ultrapassado"}
        />
        <StatCard
          label="Limites excedidos"
          value={String(stats.over)}
          icon={PieChart}
          tone={stats.over ? "negative" : "neutral"}
          footnote={stats.over ? "Revise estas categorias" : "Tudo sob controle"}
        />
      </div>

      <Panel
        title="Limites por categoria"
        subtitle="Comparativo entre o limite planejado e o gasto do mês"
      >
        {budgets.loading ? (
          <Skeleton lines={6} />
        ) : budgets.error ? (
          <ErrorState message={budgets.error} onRetry={budgets.reload} />
        ) : !budgets.data?.length ? (
          <EmptyState
            icon={PieChart}
            title="Seu orçamento começa com um limite"
            description="Defina quanto pretende gastar em cada categoria e acompanhe o ritmo dos gastos ao longo do mês."
            action={
              <Button variant="primary" icon={Plus} onClick={openCreate}>
                Definir primeiro limite
              </Button>
            }
          />
        ) : (
          <div className="budget-list">
            {budgets.data.map((budget) => {
              const over = number(budget.spent) > number(budget.limit_amount);
              const warning = budget.percent >= 80 && !over;
              return (
                <div className="budget-row" key={budget.id}>
                  <div className="budget-head">
                    <div>
                      <strong>{budget.category_name || "Categoria"}</strong>
                      <small>
                        {money(budget.spent)} de {money(budget.limit_amount)}
                      </small>
                    </div>
                    <div className="budget-side">
                      <Badge tone={over ? "bad" : warning ? "warn" : "good"}>
                        {over ? "Excedido" : warning ? "Atenção" : "Dentro do plano"}
                      </Badge>
                      <b className={over ? "negative-text" : undefined}>{budget.percent.toFixed(0)}%</b>
                    </div>
                  </div>
                  <Progress
                    value={clampPercent(budget.percent)}
                    tone={over ? "var(--danger)" : warning ? "var(--warn)" : "var(--positive)"}
                  />
                  <div className="budget-foot">
                    <span>
                      {over
                        ? `Excedeu ${money(Math.abs(number(budget.available)))}`
                        : `Restam ${money(budget.available)}`}
                    </span>
                    <div className="row-actions">
                      <IconButton label="Editar limite" icon={Pencil} onClick={() => openEdit(budget)} />
                      <IconButton
                        label="Excluir limite"
                        icon={Trash2}
                        className="danger-icon"
                        onClick={() => setDeleting(budget)}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      <Modal
        open={modalOpen}
        onClose={() => !saving && setModalOpen(false)}
        title={editing ? "Editar limite" : "Novo limite de orçamento"}
        subtitle={
          editing
            ? `Ajuste o limite de ${editing.category_name} para ${monthLabel(month)}.`
            : "Escolha uma categoria de despesa e defina o limite para este mês."
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)} disabled={saving}>
              Cancelar
            </Button>
            <Button variant="primary" type="submit" form="budget-form" loading={saving}>
              {editing ? "Salvar limite" : "Definir limite"}
            </Button>
          </>
        }
      >
        <form id="budget-form" onSubmit={submit} className="form-stack">
          <Field label="Categoria">
            {editing ? (
              <Input value={editing.category_name || ""} disabled />
            ) : (
              <Select
                required
                value={categoryId}
                onChange={(event) => setCategoryId(event.target.value)}
              >
                <option value="">Escolha uma categoria</option>
                {availableCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Limite mensal (R$)" hint={`Válido para ${monthLabel(month)}.`}>
            <Input
              required
              inputMode="decimal"
              value={limitAmount}
              onChange={(event) => setLimitAmount(event.target.value)}
              placeholder="0,00"
            />
          </Field>
          {formError ? <div className="form-error">{formError}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Remover limite?"
        description={`O limite de ${deleting?.category_name || "categoria"} será removido de ${monthLabel(month)}. Os lançamentos continuam intactos.`}
        confirmLabel="Remover"
        danger
        loading={deleteLoading}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
