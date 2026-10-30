import {
  ArrowDownLeft,
  ArrowUpRight,
  BarChart3,
  Download,
  PieChart,
  ReceiptText,
  Wallet,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  Button,
  EmptyState,
  ErrorState,
  MonthNav,
  PageHeader,
  Panel,
  Skeleton,
  StatCard,
} from "../components/ui";
import { useToast } from "../context/ToastContext";
import { downloadFile, errorMessage } from "../lib/api";
import {
  currentMonth,
  dateLabel,
  money,
  monthBounds,
  monthLabel,
  number,
  shortMonthLabel,
} from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type { DashboardData, ReportData, Transaction } from "../types";

function CategoryDonut({ categories }: { categories: ReportData["by_category"] }) {
  if (categories.length === 0) {
    return (
      <div className="donut-wrap">
        <div className="donut empty-donut" />
        <p className="muted">Nenhuma despesa no período.</p>
      </div>
    );
  }
  let cursor = 0;
  const stops = categories.map((category) => {
    const start = cursor;
    cursor += category.percent;
    return `${category.color} ${start}% ${cursor}%`;
  });
  return (
    <div className="donut-wrap">
      <div className="donut" style={{ background: `conic-gradient(${stops.join(", ")})` }}>
        <div className="donut-center">
          <small>Despesas</small>
          <strong>{money(categories.reduce((sum, item) => sum + number(item.amount), 0))}</strong>
        </div>
      </div>
    </div>
  );
}

export default function ReportsPage() {
  const { notify } = useToast();
  const [month, setMonth] = useState(currentMonth());
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const bounds = monthBounds(month);
  const report = useApiData<ReportData>(`/reports/monthly?month=${month}`);
  const dashboard = useApiData<DashboardData>(`/dashboard?month=${month}`);
  const transactions = useApiData<Transaction[]>(
    `/transactions?start=${bounds.start}&end=${bounds.end}&page_size=100&page=${page}`,
  );

  useEffect(() => {
    setPage(1);
  }, [month]);

  const exportCsv = async () => {
    setExporting(true);
    try {
      await downloadFile(
        `/reports/transactions.csv?start=${bounds.start}&end=${bounds.end}`,
        `fortexahome-lancamentos-${month}.csv`,
      );
      notify("Relatório CSV gerado.");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="ANÁLISE"
        title="Relatórios financeiros"
        description="Entenda seus hábitos e acompanhe a evolução da família."
        actions={
          <>
            <MonthNav month={month} onChange={setMonth} />
            <Button variant="secondary" icon={Download} loading={exporting} onClick={() => void exportCsv()}>
              Baixar CSV
            </Button>
          </>
        }
      />

      {report.loading ? (
        <Skeleton lines={8} />
      ) : report.error || !report.data ? (
        <ErrorState message={report.error || "Relatório indisponível."} onRetry={report.reload} />
      ) : (
        <>
          <div className="stats-grid">
            <StatCard
              label="Receitas"
              value={money(report.data.income)}
              icon={ArrowDownLeft}
              tone="positive"
              footnote={monthLabel(month)}
            />
            <StatCard
              label="Despesas"
              value={money(report.data.expense)}
              icon={ArrowUpRight}
              tone="negative"
              footnote={monthLabel(month)}
            />
            <StatCard
              label="Resultado"
              value={money(report.data.result)}
              icon={Wallet}
              tone={number(report.data.result) >= 0 ? "positive" : "negative"}
              footnote={number(report.data.result) >= 0 ? "Sobrou neste mês" : "Mês fechou no negativo"}
            />
            <StatCard
              label="Movimentações"
              value={String(report.data.count)}
              icon={ReceiptText}
              tone="neutral"
              footnote="Lançamentos no mês"
            />
          </div>

          <div className="grid-main">
            <Panel title="Resumo do período" subtitle="Consolidado do mês selecionado">
              <div className="report-summary">
                <div>
                  <span>Receitas</span>
                  <strong className="positive-text">{money(report.data.income)}</strong>
                </div>
                <div>
                  <span>Despesas</span>
                  <strong className="negative-text">{money(report.data.expense)}</strong>
                </div>
                <div className="report-divider" />
                <div>
                  <span>Resultado</span>
                  <strong className={number(report.data.result) >= 0 ? "positive-text" : "negative-text"}>
                    {money(report.data.result)}
                  </strong>
                </div>
                <div>
                  <span>Taxa de poupança</span>
                  <strong>
                    {number(report.data.income) > 0
                      ? `${Math.max(0, (number(report.data.result) / number(report.data.income)) * 100).toFixed(0)}%`
                      : "—"}
                  </strong>
                </div>
              </div>
              {dashboard.data ? (
                <div className="mini-flow">
                  {dashboard.data.series.map((item) => {
                    const max = Math.max(
                      1,
                      ...dashboard.data!.series.flatMap((entry) => [
                        number(entry.income),
                        number(entry.expense),
                      ]),
                    );
                    return (
                      <div className="mini-flow-group" key={item.month}>
                        <div className="mini-flow-bars">
                          <span style={{ height: `${Math.max(3, (number(item.income) / max) * 100)}%` }} className="income" />
                          <span style={{ height: `${Math.max(3, (number(item.expense) / max) * 100)}%` }} className="expense" />
                        </div>
                        <small>{shortMonthLabel(item.month)}</small>
                      </div>
                    );
                  })}
                </div>
              ) : null}
              <div className="legend report-legend">
                <span>
                  <i className="dot brand" /> Receitas
                </span>
                <span>
                  <i className="dot expense" /> Despesas
                </span>
              </div>
            </Panel>
            <Panel title="Distribuição das despesas" subtitle="Valores por categoria">
              <CategoryDonut categories={report.data.by_category} />
              {report.data.by_category.length > 0 ? (
                <div className="report-category-list">
                  {report.data.by_category.map((category) => (
                    <div className="report-category" key={`${category.name}-${category.color}`}>
                      <span>
                        <i className="dot" style={{ background: category.color }} />
                        {category.name}
                      </span>
                      <div>
                        <b>{money(category.amount)}</b>
                        <small>{category.percent.toFixed(1).replace(".", ",")}%</small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </Panel>
          </div>

          <Panel
            title="Histórico de movimentações"
            subtitle={`Dados de ${monthLabel(month).toLowerCase()}`}
            actions={
              <span className="panel-icon">
                <BarChart3 size={17} />
              </span>
            }
          >
            {transactions.loading ? (
              <Skeleton lines={6} />
            ) : transactions.error ? (
              <ErrorState message={transactions.error} onRetry={transactions.reload} />
            ) : !transactions.data?.length ? (
              <EmptyState
                icon={PieChart}
                title="Nenhuma movimentação no mês"
                description="Escolha outro mês ou registre novos lançamentos para preencher este relatório."
              />
            ) : (
              <div className="table-wrap">
                <table className="responsive-table">
                  <thead>
                    <tr>
                      <th>Descrição</th>
                      <th>Tipo</th>
                      <th>Categoria</th>
                      <th>Data</th>
                      <th className="align-right">Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.data.map((transaction) => (
                      <tr key={transaction.id}>
                        <td data-label="Descrição">{transaction.description}</td>
                        <td className="muted-cell" data-label="Tipo">
                          {transaction.kind === "income" ? "Receita" : "Despesa"}
                        </td>
                        <td className="muted-cell" data-label="Categoria">{transaction.category_name || "Sem categoria"}</td>
                        <td className="muted-cell" data-label="Data">{dateLabel(transaction.occurred_on)}</td>
                        <td className={`align-right amount ${transaction.kind}`} data-label="Valor">
                          {transaction.kind === "income" ? "+" : "−"} {money(transaction.amount)}
                        </td>
                      </tr>
                    ))}
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
        </>
      )}
    </>
  );
}
