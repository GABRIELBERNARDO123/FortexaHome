import { CreditCard, Pencil, Plus, Trash2, Wallet } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  MonthNav,
  PageHeader,
  Panel,
  Progress,
  Skeleton,
  StatCard,
} from "../components/ui";
import { useToast } from "../context/ToastContext";
import { api, errorMessage } from "../lib/api";
import {
  centsToApiDecimal,
  clampPercent,
  currentMonth,
  dateLabel,
  money,
  monthBounds,
  number,
  parseBRLAmountToCents,
} from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type { Card, Transaction } from "../types";

interface CardForm {
  id?: string;
  name: string;
  institution: string;
  limit_amount: string;
  closing_day: string;
  due_day: string;
}

function emptyForm(): CardForm {
  return { name: "", institution: "", limit_amount: "", closing_day: "20", due_day: "28" };
}

export default function CardsPage() {
  const { notify } = useToast();
  const [month, setMonth] = useState(currentMonth());
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Card | null>(null);
  const [form, setForm] = useState<CardForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [archiving, setArchiving] = useState<Card | null>(null);
  const [archiveLoading, setArchiveLoading] = useState(false);

  const bounds = monthBounds(month);
  const cards = useApiData<Card[]>(`/cards?start=${bounds.start}&end=${bounds.end}`);
  const transactions = useApiData<Transaction[]>(
    `/transactions?start=${bounds.start}&end=${bounds.end}&page_size=100&page=${page}`,
  );

  useEffect(() => {
    setPage(1);
  }, [month]);

  const stats = useMemo(() => {
    const rows = cards.data || [];
    const limit = rows.reduce((sum, card) => sum + number(card.limit_amount), 0);
    const spent = rows.reduce((sum, card) => sum + number(card.spent), 0);
    return { limit, spent, available: Math.max(0, limit - spent), count: rows.length };
  }, [cards.data]);

  const cardPurchases = (transactions.data || []).filter((item) => item.card_id);

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm());
    setFormError(null);
    setModalOpen(true);
  };

  const openEdit = (card: Card) => {
    setEditing(card);
    setForm({
      id: card.id,
      name: card.name,
      institution: card.institution,
      limit_amount: card.limit_amount,
      closing_day: String(card.closing_day),
      due_day: String(card.due_day),
    });
    setFormError(null);
    setModalOpen(true);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const limitCents = parseBRLAmountToCents(form.limit_amount);
    if (limitCents === null) {
      setFormError("Informe um limite válido. Use vírgula para centavos. Ex.: 5.000,00");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        institution: form.institution.trim(),
        limit_amount: centsToApiDecimal(limitCents),
        closing_day: Number(form.closing_day),
        due_day: Number(form.due_day),
      };
      if (editing) {
        await api(`/cards/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        notify("Cartão atualizado.");
      } else {
        await api("/cards", { method: "POST", body: JSON.stringify(payload) });
        notify("Cartão adicionado.");
      }
      setModalOpen(false);
      setEditing(null);
      cards.reload();
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const confirmArchive = async () => {
    if (!archiving) return;
    setArchiveLoading(true);
    try {
      await api(`/cards/${archiving.id}`, { method: "DELETE" });
      notify("Cartão arquivado. O histórico de compras foi preservado.");
      setArchiving(null);
      cards.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setArchiveLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="CRÉDITO"
        title="Cartões de crédito"
        description="Organize seus cartões e acompanhe limites e faturas."
        actions={
          <>
            <MonthNav month={month} onChange={setMonth} />
            <Button variant="primary" icon={Plus} onClick={openCreate}>
              Adicionar cartão
            </Button>
          </>
        }
      />

      <div className="stats-grid">
        <StatCard
          label="Limite total"
          value={money(stats.limit)}
          icon={CreditCard}
          tone="brand"
          footnote={`${stats.count} cartão(ões) ativo(s)`}
        />
        <StatCard
          label="Usado no mês"
          value={money(stats.spent)}
          icon={Wallet}
          tone="negative"
          footnote="Compras vinculadas a cartões"
        />
        <StatCard
          label="Limite disponível"
          value={money(stats.available)}
          icon={Wallet}
          tone="positive"
          footnote="Considerando o uso deste mês"
        />
        <StatCard
          label="Comprometimento"
          value={stats.limit > 0 ? `${((stats.spent / stats.limit) * 100).toFixed(0)}%` : "—"}
          icon={CreditCard}
          tone={stats.limit > 0 && stats.spent / stats.limit > 0.8 ? "negative" : "neutral"}
          footnote="Do limite total"
        />
      </div>

      {cards.loading ? (
        <div className="cards-grid">
          {Array.from({ length: 2 }).map((_, index) => (
            <div className="credit-card skeleton-card" key={index}>
              <Skeleton lines={4} />
            </div>
          ))}
        </div>
      ) : cards.error ? (
        <ErrorState message={cards.error} onRetry={cards.reload} />
      ) : !cards.data?.length ? (
        <Panel>
          <EmptyState
            icon={CreditCard}
            title="Nenhum cartão cadastrado"
            description="Adicione seus cartões para acompanhar o limite disponível e as compras do mês."
            action={
              <Button variant="primary" icon={Plus} onClick={openCreate}>
                Adicionar primeiro cartão
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="cards-grid">
          {cards.data.map((card, index) => {
            const usedPercent = number(card.limit_amount) > 0
              ? (number(card.spent) / number(card.limit_amount)) * 100
              : 0;
            return (
              <article className={`credit-card card-tone-${index % 3}`} key={card.id}>
                <div className="credit-card-top">
                  <div>
                    <span>{card.institution}</span>
                    <h3>{card.name}</h3>
                  </div>
                  <div className="card-chip" aria-hidden="true" />
                </div>
                <div className="credit-card-numbers" aria-hidden="true">
                  •••• •••• •••• {String(index + 1).padStart(4, "0")}
                </div>
                <div className="credit-card-footer">
                  <div>
                    <small>Fecha dia</small>
                    <b>{card.closing_day}</b>
                  </div>
                  <div>
                    <small>Vence dia</small>
                    <b>{card.due_day}</b>
                  </div>
                  <div className="card-actions">
                    <button type="button" onClick={() => openEdit(card)} aria-label="Editar cartão">
                      <Pencil size={15} />
                    </button>
                    <button type="button" onClick={() => setArchiving(card)} aria-label="Arquivar cartão">
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
                <div className="credit-card-progress">
                  <div>
                    <span>Usado {money(card.spent)}</span>
                    <span>Disponível {money(card.available)}</span>
                  </div>
                  <Progress value={clampPercent(usedPercent)} />
                  <small>
                    Limite de {money(card.limit_amount)} · {usedPercent.toFixed(0)}% comprometido
                  </small>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <Panel
        title="Compras no cartão"
        subtitle={`Lançamentos no crédito em ${month.split("-").reverse().join("/")}`}
      >
        {transactions.loading ? (
          <Skeleton lines={5} />
        ) : cardPurchases.length === 0 ? (
          <EmptyState
            icon={CreditCard}
            title="Nenhuma compra no cartão neste mês"
            description="Ao registrar uma despesa no crédito, vincule o cartão para acompanhar a fatura."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Descrição</th>
                  <th>Cartão</th>
                  <th>Data</th>
                  <th>Categoria</th>
                  <th className="align-right">Valor</th>
                </tr>
              </thead>
              <tbody>
                {cardPurchases.map((transaction) => {
                  const card = cards.data?.find((item) => item.id === transaction.card_id);
                  return (
                    <tr key={transaction.id}>
                      <td>{transaction.description}</td>
                      <td className="muted-cell">{card?.name || "Cartão"}</td>
                      <td className="muted-cell">{dateLabel(transaction.occurred_on)}</td>
                      <td className="muted-cell">{transaction.category_name || "Sem categoria"}</td>
                      <td className="align-right amount expense">− {money(transaction.amount)}</td>
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
        onClose={() => !saving && setModalOpen(false)}
        title={editing ? "Editar cartão" : "Adicionar cartão"}
        subtitle="Os limites e datas ajudam a planejar a fatura de cada mês."
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)} disabled={saving}>
              Cancelar
            </Button>
            <Button variant="primary" type="submit" form="card-form" loading={saving}>
              {editing ? "Salvar alterações" : "Adicionar cartão"}
            </Button>
          </>
        }
      >
        <form id="card-form" onSubmit={submit} className="form-stack">
          <div className="form-grid">
            <Field label="Nome do cartão">
              <Input
                required
                maxLength={100}
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="Ex.: Cartão da família"
              />
            </Field>
            <Field label="Instituição">
              <Input
                required
                maxLength={100}
                value={form.institution}
                onChange={(event) => setForm({ ...form, institution: event.target.value })}
                placeholder="Ex.: Banco Fortexa"
              />
            </Field>
            <Field label="Limite (R$)">
              <Input
                required
                inputMode="decimal"
                value={form.limit_amount}
                onChange={(event) => setForm({ ...form, limit_amount: event.target.value })}
                placeholder="0,00"
              />
            </Field>
            <Field label="Dia de fechamento">
              <Input
                required
                type="number"
                min={1}
                max={31}
                value={form.closing_day}
                onChange={(event) => setForm({ ...form, closing_day: event.target.value })}
              />
            </Field>
            <Field label="Dia de vencimento">
              <Input
                required
                type="number"
                min={1}
                max={31}
                value={form.due_day}
                onChange={(event) => setForm({ ...form, due_day: event.target.value })}
              />
            </Field>
          </div>
          {formError ? <div className="form-error">{formError}</div> : null}
        </form>
      </Modal>

      <ConfirmDialog
        open={Boolean(archiving)}
        title="Arquivar cartão?"
        description={`"${archiving?.name || ""}" deixará de aparecer na lista, mas o histórico de compras será mantido.`}
        confirmLabel="Arquivar"
        danger
        loading={archiveLoading}
        onConfirm={() => void confirmArchive()}
        onClose={() => setArchiving(null)}
      />
    </>
  );
}
