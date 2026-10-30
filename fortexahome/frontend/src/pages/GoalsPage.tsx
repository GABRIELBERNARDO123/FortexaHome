import {
  CalendarDays,
  CheckCircle2,
  History,
  Minus,
  Pencil,
  Plus,
  Target,
  Trash2,
  TrendingUp,
} from "lucide-react";
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
  PageHeader,
  Panel,
  Progress,
  Select,
  Skeleton,
  StatCard,
  Textarea,
} from "../components/ui";
import { useToast } from "../context/ToastContext";
import { api, errorMessage } from "../lib/api";
import {
  centsToApiDecimal,
  clampPercent,
  dateLabel,
  money,
  number,
  parseBRLAmountToCents,
  todayISO,
} from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type { Goal, GoalMovement } from "../types";

const ICONS = ["🎯", "✈️", "🏠", "🚗", "🎓", "💍", "🌱", "🛟", "💻", "🏖️"];

interface GoalForm {
  id?: string;
  name: string;
  description: string;
  target_amount: string;
  target_date: string;
  icon: string;
  status: Goal["status"];
}

function emptyForm(): GoalForm {
  return {
    name: "",
    description: "",
    target_amount: "",
    target_date: "",
    icon: "🎯",
    status: "active",
  };
}

interface MovementForm {
  kind: "deposit" | "withdrawal";
  amount: string;
  occurred_on: string;
  note: string;
}

function emptyMovement(): MovementForm {
  return { kind: "deposit", amount: "", occurred_on: todayISO(), note: "" };
}

function GoalHistory({ goal, onClose }: { goal: Goal; onClose: () => void }) {
  const movements = useApiData<GoalMovement[]>(`/goals/${goal.id}/movements`);
  return (
    <Modal open onClose={onClose} title={`Histórico · ${goal.name}`} subtitle="Aportes e retiradas desta meta.">
      {movements.loading ? (
        <Skeleton lines={5} />
      ) : movements.error ? (
        <ErrorState message={movements.error} onRetry={movements.reload} />
      ) : !movements.data?.length ? (
        <EmptyState
          icon={History}
          title="Nenhuma movimentação"
          description="Os aportes e retiradas desta meta aparecerão aqui."
        />
      ) : (
        <div className="movement-list">
          {movements.data.map((movement) => (
            <div className="movement-row" key={movement.id}>
              <span className={`movement-icon ${movement.kind}`}>
                {movement.kind === "deposit" ? <Plus size={15} /> : <Minus size={15} />}
              </span>
              <div>
                <strong>{movement.kind === "deposit" ? "Aporte" : "Retirada"}</strong>
                <small>
                  {dateLabel(movement.occurred_on)}
                  {movement.note ? ` · ${movement.note}` : ""}
                </small>
              </div>
              <b className={movement.kind === "deposit" ? "positive-text" : "negative-text"}>
                {movement.kind === "deposit" ? "+" : "−"} {money(movement.amount)}
              </b>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

export default function GoalsPage() {
  const { notify } = useToast();
  const resource = useApiData<Goal[]>("/goals");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Goal | null>(null);
  const [form, setForm] = useState<GoalForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [movementGoal, setMovementGoal] = useState<Goal | null>(null);
  const [movementForm, setMovementForm] = useState<MovementForm>(emptyMovement());
  const [movementSaving, setMovementSaving] = useState(false);
  const [movementError, setMovementError] = useState<string | null>(null);
  const [historyGoal, setHistoryGoal] = useState<Goal | null>(null);
  const [deleting, setDeleting] = useState<Goal | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const rows = resource.data || [];
  const stats = useMemo(() => {
    const active = rows.filter((goal) => goal.status === "active");
    const saved = active.reduce((sum, goal) => sum + number(goal.saved_amount), 0);
    const target = active.reduce((sum, goal) => sum + number(goal.target_amount), 0);
    return {
      active: active.length,
      completed: rows.filter((goal) => goal.status === "completed").length,
      saved,
      target,
    };
  }, [rows]);

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (goal: Goal) => {
    setEditing(goal);
    setForm({
      id: goal.id,
      name: goal.name,
      description: goal.description || "",
      target_amount: goal.target_amount,
      target_date: goal.target_date || "",
      icon: goal.icon,
      status: goal.status,
    });
    setFormError(null);
    setModalOpen(true);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const targetCents = parseBRLAmountToCents(form.target_amount);
    if (targetCents === null) {
      setFormError("Informe um valor-alvo maior que zero. Use vírgula para centavos. Ex.: 1.500,00");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        target_amount: centsToApiDecimal(targetCents),
        target_date: form.target_date || null,
        icon: form.icon || "🎯",
        ...(editing ? { status: form.status } : {}),
      };
      if (editing) {
        await api(`/goals/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        notify("Meta atualizada.");
      } else {
        await api("/goals", { method: "POST", body: JSON.stringify(payload) });
        notify("Nova meta criada. O próximo sonho já tem um plano.");
      }
      setModalOpen(false);
      setEditing(null);
      resource.reload();
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const openMovement = (goal: Goal, kind: "deposit" | "withdrawal") => {
    setMovementGoal(goal);
    setMovementForm({ ...emptyMovement(), kind });
    setMovementError(null);
  };

  const submitMovement = async (event: FormEvent) => {
    event.preventDefault();
    if (!movementGoal) return;
    setMovementError(null);
    const amountCents = parseBRLAmountToCents(movementForm.amount);
    if (amountCents === null) {
      setMovementError("Informe um valor maior que zero. Use vírgula para centavos. Ex.: 1.500,00");
      return;
    }
    setMovementSaving(true);
    try {
      await api(`/goals/${movementGoal.id}/movements`, {
        method: "POST",
        body: JSON.stringify({
          kind: movementForm.kind,
          amount: centsToApiDecimal(amountCents),
          occurred_on: movementForm.occurred_on,
          note: movementForm.note.trim() || null,
        }),
      });
      notify(movementForm.kind === "deposit" ? "Aporte registrado." : "Retirada registrada.");
      setMovementGoal(null);
      resource.reload();
    } catch (caught) {
      setMovementError(errorMessage(caught));
    } finally {
      setMovementSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteLoading(true);
    try {
      await api(`/goals/${deleting.id}`, { method: "DELETE" });
      notify("Meta e histórico excluídos.");
      setDeleting(null);
      resource.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="FUTURO DA FAMÍLIA"
        title="Metas financeiras"
        description="Transforme planos em conquistas, um passo de cada vez."
        actions={
          <Button variant="primary" icon={Plus} onClick={openCreate}>
            Nova meta
          </Button>
        }
      />

      <div className="stats-grid">
        <StatCard
          label="Metas ativas"
          value={String(stats.active)}
          icon={Target}
          tone="brand"
          footnote={`${stats.completed} concluída(s)`}
        />
        <StatCard
          label="Total guardado"
          value={money(stats.saved)}
          icon={TrendingUp}
          tone="positive"
          footnote="Somando as metas em andamento"
        />
        <StatCard
          label="Objetivo ativo"
          value={money(stats.target)}
          icon={CheckCircle2}
          tone="neutral"
          footnote="Soma das metas em andamento"
        />
        <StatCard
          label="Progresso geral"
          value={stats.target > 0 ? `${((stats.saved / stats.target) * 100).toFixed(0)}%` : "—"}
          icon={Target}
          tone="neutral"
          footnote="Do objetivo das metas ativas"
        />
      </div>

      {resource.loading ? (
        <div className="goals-grid">
          {Array.from({ length: 3 }).map((_, index) => (
            <Panel key={index}>
              <Skeleton lines={4} />
            </Panel>
          ))}
        </div>
      ) : resource.error ? (
        <ErrorState message={resource.error} onRetry={resource.reload} />
      ) : rows.length === 0 ? (
        <Panel>
          <EmptyState
            icon={Target}
            title="Qual é o próximo sonho da família?"
            description="Uma viagem, a reserva de emergência, a casa nova... crie uma meta e acompanhe cada passo."
            action={
              <Button variant="primary" icon={Plus} onClick={openCreate}>
                Criar primeira meta
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="goals-grid">
          {rows.map((goal) => {
            const completed = goal.status === "completed";
            return (
              <article className={`goal-card ${completed ? "completed" : ""}`} key={goal.id}>
                <div className="goal-card-top">
                  <div className="goal-icon" aria-hidden="true">
                    {goal.icon || "🎯"}
                  </div>
                  <div className="goal-card-title">
                    <h3>{goal.name}</h3>
                    {goal.description ? <p>{goal.description}</p> : null}
                  </div>
                  <Badge tone={completed ? "good" : goal.status === "cancelled" ? "neutral" : "brand"}>
                    {completed ? "Conquistada" : goal.status === "cancelled" ? "Cancelada" : "Em andamento"}
                  </Badge>
                </div>
                <div className="goal-amounts">
                  <div>
                    <small>Guardado</small>
                    <strong>{money(goal.saved_amount)}</strong>
                  </div>
                  <div className="align-right">
                    <small>Objetivo</small>
                    <strong>{money(goal.target_amount)}</strong>
                  </div>
                </div>
                <Progress value={clampPercent(goal.progress_percent)} />
                <div className="goal-meta">
                  <span>{goal.progress_percent.toFixed(0)}% concluído</span>
                  <span>{money(goal.remaining_amount)} restantes</span>
                </div>
                <div className="goal-info">
                  {goal.target_date ? (
                    <span>
                      <CalendarDays size={14} /> Até {dateLabel(goal.target_date)}
                    </span>
                  ) : (
                    <span>
                      <CalendarDays size={14} /> Sem data definida
                    </span>
                  )}
                  {goal.projected_monthly && goal.status === "active" ? (
                    <span>
                      <TrendingUp size={14} /> {money(goal.projected_monthly)}/mês sugerido
                    </span>
                  ) : null}
                </div>
                <div className="goal-actions">
                  <Button
                    variant="primary"
                    icon={Plus}
                    className="btn-compact"
                    onClick={() => openMovement(goal, "deposit")}
                    disabled={goal.status === "cancelled"}
                  >
                    Aportar
                  </Button>
                  <Button
                    variant="secondary"
                    icon={Minus}
                    className="btn-compact"
                    onClick={() => openMovement(goal, "withdrawal")}
                    disabled={goal.status === "cancelled"}
                  >
                    Retirar
                  </Button>
                  <div className="goal-actions-right">
                    <IconButton label="Ver histórico" icon={History} onClick={() => setHistoryGoal(goal)} />
                    <IconButton label="Editar meta" icon={Pencil} onClick={() => openEdit(goal)} />
                    <IconButton
                      label="Excluir meta"
                      icon={Trash2}
                      className="danger-icon"
                      onClick={() => setDeleting(goal)}
                    />
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <Modal
        open={modalOpen}
        onClose={() => !saving && setModalOpen(false)}
        title={editing ? "Editar meta" : "Nova meta financeira"}
        subtitle="Dê um nome ao sonho e defina quanto e quando quer conquistá-lo."
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)} disabled={saving}>
              Cancelar
            </Button>
            <Button variant="primary" type="submit" form="goal-form" loading={saving}>
              {editing ? "Salvar meta" : "Criar meta"}
            </Button>
          </>
        }
      >
        <form id="goal-form" onSubmit={submit} className="form-stack">
          <div className="emoji-picker" role="group" aria-label="Ícone da meta">
            {ICONS.map((icon) => (
              <button
                key={icon}
                type="button"
                className={form.icon === icon ? "active" : undefined}
                onClick={() => setForm({ ...form, icon })}
                aria-label={`Ícone ${icon}`}
              >
                {icon}
              </button>
            ))}
          </div>
          <div className="form-grid">
            <Field label="Nome da meta" className="span-2">
              <Input
                required
                maxLength={140}
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="Ex.: Viagem em família"
              />
            </Field>
            <Field label="Valor-alvo (R$)">
              <Input
                required
                inputMode="decimal"
                value={form.target_amount}
                onChange={(event) => setForm({ ...form, target_amount: event.target.value })}
                placeholder="0,00"
              />
            </Field>
            <Field label="Data-alvo" hint="Opcional.">
              <Input
                type="date"
                value={form.target_date}
                onChange={(event) => setForm({ ...form, target_date: event.target.value })}
              />
            </Field>
            {editing ? (
              <Field label="Situação">
                <Select
                  value={form.status}
                  onChange={(event) =>
                    setForm({ ...form, status: event.target.value as Goal["status"] })
                  }
                >
                  <option value="active">Em andamento</option>
                  <option value="completed">Conquistada</option>
                  <option value="cancelled">Cancelada</option>
                </Select>
              </Field>
            ) : null}
            <Field label="Descrição" className="span-2">
              <Textarea
                rows={3}
                maxLength={2000}
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                placeholder="Por que esta meta é importante para a família?"
              />
            </Field>
          </div>
          {formError ? <div className="form-error">{formError}</div> : null}
        </form>
      </Modal>

      <Modal
        open={Boolean(movementGoal)}
        onClose={() => !movementSaving && setMovementGoal(null)}
        title={movementForm.kind === "deposit" ? "Registrar aporte" : "Registrar retirada"}
        subtitle={movementGoal ? `Meta: ${movementGoal.name}` : undefined}
        footer={
          <>
            <Button variant="ghost" onClick={() => setMovementGoal(null)} disabled={movementSaving}>
              Cancelar
            </Button>
            <Button variant="primary" type="submit" form="movement-form" loading={movementSaving}>
              {movementForm.kind === "deposit" ? "Guardar valor" : "Retirar valor"}
            </Button>
          </>
        }
      >
        <form id="movement-form" onSubmit={submitMovement} className="form-stack">
          <div className="segmented">
            <button
              type="button"
              className={movementForm.kind === "deposit" ? "active income" : undefined}
              onClick={() => setMovementForm({ ...movementForm, kind: "deposit" })}
            >
              <Plus size={15} /> Aporte
            </button>
            <button
              type="button"
              className={movementForm.kind === "withdrawal" ? "active expense" : undefined}
              onClick={() => setMovementForm({ ...movementForm, kind: "withdrawal" })}
            >
              <Minus size={15} /> Retirada
            </button>
          </div>
          <div className="form-grid">
            <Field label="Valor (R$)">
              <Input
                required
                inputMode="decimal"
                value={movementForm.amount}
                onChange={(event) => setMovementForm({ ...movementForm, amount: event.target.value })}
                placeholder="0,00"
              />
            </Field>
            <Field label="Data">
              <Input
                type="date"
                required
                value={movementForm.occurred_on}
                onChange={(event) => setMovementForm({ ...movementForm, occurred_on: event.target.value })}
              />
            </Field>
            <Field label="Observação" className="span-2">
              <Input
                maxLength={1000}
                value={movementForm.note}
                onChange={(event) => setMovementForm({ ...movementForm, note: event.target.value })}
                placeholder="Ex.: 13º salário, reserva do mês..."
              />
            </Field>
          </div>
          {movementError ? <div className="form-error">{movementError}</div> : null}
        </form>
      </Modal>

      {historyGoal ? <GoalHistory goal={historyGoal} onClose={() => setHistoryGoal(null)} /> : null}

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Excluir meta?"
        description={`"${deleting?.name || ""}" e todo o histórico de aportes serão removidos permanentemente.`}
        confirmLabel="Excluir"
        danger
        loading={deleteLoading}
        onConfirm={() => void confirmDelete()}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
