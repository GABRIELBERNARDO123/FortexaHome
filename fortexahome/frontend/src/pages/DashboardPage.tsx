import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CalendarClock,
  CreditCard,
  PiggyBank,
  ReceiptText,
  Target,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  MonthNav,
  PageHeader,
  Panel,
  Progress,
  Skeleton,
  StatCard,
} from "../components/ui";
import { useAuth } from "../context/AuthContext";
import {
  clampPercent,
  currentMonth,
  dateLabel,
  money,
  monthLabel,
  number,
  percent,
  shortMonthLabel,
} from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type { DashboardData, Goal } from "../types";

function FlowChart({ series }: { series: DashboardData["series"] }) {
  const max = Math.max(
    1,
    ...series.flatMap((item) => [number(item.income), number(item.expense)]),
  );
  return (
    <div className="flow-chart">
      {series.map((item) => {
        const incomeHeight = (number(item.income) / max) * 100;
        const expenseHeight = (number(item.expense) / max) * 100;
        return (
          <div className="flow-group" key={item.month}>
            <div className="flow-bars">
              <div className="flow-bar" style={{ height: `${Math.max(incomeHeight, 2)}%` }} title={`Receitas: ${money(item.income)}`}>
                <span className="bar-income" />
              </div>
              <div className="flow-bar" style={{ height: `${Math.max(expenseHeight, 2)}%` }} title={`Despesas: ${money(item.expense)}`}>
                <span className="bar-expense" />
              </div>
            </div>
            <span className="flow-label">{shortMonthLabel(item.month)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function DashboardPage() {
  const { auth } = useAuth();
  const navigate = useNavigate();
  const [month, setMonth] = useState(currentMonth());
  const { data, loading, error, reload } = useApiData<DashboardData>(`/dashboard?month=${month}`);
  const goals = useApiData<Goal[]>("/goals");

  const activeGoals = (goals.data || []).filter((goal) => goal.status === "active").slice(0, 3);

  return (
    <>
      <PageHeader
        eyebrow="VISÃO GERAL"
        title="Seu dinheiro, sob controle."
        description={`A saúde financeira da ${auth?.tenant.name || "sua família"} em um só lugar.`}
        actions={<MonthNav month={month} onChange={setMonth} />}
      />

      {loading ? (
        <div className="stack">
          <div className="stats-grid">
            {Array.from({ length: 4 }).map((_, index) => (
              <div className="stat skeleton-card" key={index}>
                <Skeleton lines={3} />
              </div>
            ))}
          </div>
          <div className="grid-main">
            <Panel title="Fluxo financeiro">{<Skeleton lines={6} />}</Panel>
            <Panel title="Despesas por categoria">{<Skeleton lines={5} />}</Panel>
          </div>
        </div>
      ) : error || !data ? (
        <ErrorState message={error || "Dados indisponíveis."} onRetry={reload} />
      ) : (
        <>
          <div className="stats-grid">
            <StatCard
              label="Saldo acumulado"
              value={money(data.total_balance)}
              icon={Wallet}
              tone={number(data.total_balance) >= 0 ? "brand" : "negative"}
              footnote="Receitas menos despesas de todo o histórico"
            />
            <StatCard
              label="Receitas do mês"
              value={money(data.income)}
              icon={TrendingUp}
              tone="positive"
              trend={
                data.income_change !== null ? (
                  <span className={data.income_change >= 0 ? "trend good" : "trend bad"}>
                    {data.income_change >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                    {percent(data.income_change)} vs. mês anterior
                  </span>
                ) : (
                  <span className="trend muted">Sem base no mês anterior</span>
                )
              }
            />
            <StatCard
              label="Despesas do mês"
              value={money(data.expense)}
              icon={TrendingDown}
              tone="negative"
              trend={
                data.expense_change !== null ? (
                  <span className={data.expense_change <= 0 ? "trend good" : "trend bad"}>
                    {data.expense_change <= 0 ? <ArrowDownRight size={13} /> : <ArrowUpRight size={13} />}
                    {percent(data.expense_change)} vs. mês anterior
                  </span>
                ) : (
                  <span className="trend muted">Sem base no mês anterior</span>
                )
              }
            />
            <StatCard
              label="Contas pendentes"
              value={money(data.pending_bills_total)}
              icon={CalendarClock}
              tone={data.overdue_bills_count ? "negative" : "neutral"}
              footnote={
                data.overdue_bills_count > 0 ? (
                  <span className="trend bad">{data.overdue_bills_count} conta(s) vencida(s)</span>
                ) : (
                  `${data.pending_bills_count} conta(s) a vencer`
                )
              }
            />
          </div>

          <div className="grid-main">
            <Panel
              title="Fluxo financeiro"
              subtitle="Receitas e despesas nos últimos 6 meses"
              actions={
                <div className="legend">
                  <span>
                    <i className="dot brand" /> Receitas
                  </span>
                  <span>
                    <i className="dot expense" /> Despesas
                  </span>
                </div>
              }
            >
              <FlowChart series={data.series} />
            </Panel>
            <Panel
              title="Despesas por categoria"
              subtitle={`Onde o dinheiro foi em ${monthLabel(month).toLowerCase()}`}
              actions={
                <Link to="/relatorios" className="link-inline">
                  Relatório <ArrowRight size={14} />
                </Link>
              }
            >
              {data.categories.length === 0 ? (
                <EmptyState
                  icon={ReceiptText}
                  title="Nenhuma despesa registrada"
                  description="Adicione lançamentos para enxergar a distribuição dos gastos."
                  action={
                    <Button variant="secondary" onClick={() => navigate("/lancamentos?novo=1")}>
                      Novo lançamento
                    </Button>
                  }
                />
              ) : (
                <div className="category-bars">
                  {data.categories.map((category) => (
                    <div className="category-bar" key={`${category.name}-${category.color}`}>
                      <div className="category-bar-head">
                        <span>
                          <i className="dot" style={{ background: category.color }} />
                          {category.name}
                        </span>
                        <b>{money(category.amount)}</b>
                      </div>
                      <div className="bar-track">
                        <span style={{ width: `${clampPercent(category.percent)}%`, background: category.color }} />
                      </div>
                      <small>{category.percent.toFixed(1).replace(".", ",")}% das despesas</small>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          <div className="lower-grid">
            <Panel
              title="Últimos lançamentos"
              subtitle="Movimentações recentes da família"
              actions={
                <Link to="/lancamentos" className="link-inline">
                  Ver todos <ArrowRight size={14} />
                </Link>
              }
            >
              {data.recent_transactions.length === 0 ? (
                <EmptyState
                  icon={ReceiptText}
                  title="Tudo pronto para começar"
                  description="Registre a primeira receita ou despesa desta casa."
                  action={
                    <Button variant="primary" onClick={() => navigate("/lancamentos?novo=1")}>
                      Novo lançamento
                    </Button>
                  }
                />
              ) : (
                <div className="table-wrap">
                  <table className="recent-table">
                    <thead>
                      <tr>
                        <th>Descrição</th>
                        <th>Categoria</th>
                        <th>Data</th>
                        <th className="align-right">Valor</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_transactions.map((transaction) => (
                        <tr key={transaction.id}>
                          <td>
                            <div className="table-title">
                              <span className={`transaction-dot ${transaction.kind}`} />
                              {transaction.description}
                            </div>
                          </td>
                          <td className="muted-cell">{transaction.category_name || "Sem categoria"}</td>
                          <td className="muted-cell">{dateLabel(transaction.occurred_on)}</td>
                          <td className={`align-right amount ${transaction.kind}`}>
                            {transaction.kind === "income" ? "+" : "−"} {money(transaction.amount)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>

            <Panel
              title="Metas da família"
              subtitle="Seus sonhos estão no caminho certo"
              actions={
                <Link to="/metas" className="link-inline">
                  Ver metas <ArrowRight size={14} />
                </Link>
              }
            >
              {goals.loading ? (
                <Skeleton lines={4} />
              ) : activeGoals.length === 0 ? (
                <EmptyState
                  icon={Target}
                  title="Qual é o próximo sonho?"
                  description="Crie uma meta e acompanhe cada passo até conquistá-la."
                  action={
                    <Button variant="secondary" onClick={() => navigate("/metas")}>
                      Criar uma meta
                    </Button>
                  }
                />
              ) : (
                <div className="goal-preview-list">
                  {activeGoals.map((goal) => (
                    <div className="goal-preview" key={goal.id}>
                      <div className="goal-preview-icon" aria-hidden="true">
                        {goal.icon || "🎯"}
                      </div>
                      <div className="goal-preview-body">
                        <div className="goal-preview-head">
                          <strong>{goal.name}</strong>
                          <span>{goal.progress_percent.toFixed(0)}%</span>
                        </div>
                        <Progress value={goal.progress_percent} />
                        <small>
                          {money(goal.saved_amount)} de {money(goal.target_amount)}
                        </small>
                      </div>
                    </div>
                  ))}
                  <div className="goal-summary">
                    <span>
                      <PiggyBank size={16} /> {money(data.goals.saved)} guardados
                    </span>
                    <span>
                      <CreditCard size={16} /> {money(data.cards.available)} de limite disponível
                    </span>
                  </div>
                </div>
              )}
            </Panel>
          </div>

          <div className="insight-strip">
            <div>
              <Badge tone={number(data.result) >= 0 ? "good" : "warn"}>
                {number(data.result) >= 0 ? "Mês positivo" : "Atenção ao saldo"}
              </Badge>
              <h3>
                {number(data.result) >= 0
                  ? `Sobraram ${money(data.result)} neste mês.`
                  : `O mês fechou ${money(Math.abs(number(data.result)))} no negativo.`}
              </h3>
              <p>
                {data.budgets.count > 0
                  ? `Orçamento: ${money(data.budgets.spent)} usados de ${money(data.budgets.planned)} planejados.`
                  : "Defina limites por categoria para planejar melhor o mês."}
              </p>
            </div>
            <div className="insight-actions">
              <Button variant="secondary" onClick={() => navigate("/orcamento")}>
                Ver orçamento
              </Button>
              <Button variant="primary" onClick={() => navigate("/relatorios")}>
                Abrir relatórios
              </Button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
