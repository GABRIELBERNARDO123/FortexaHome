import { Badge, Button } from "../../components/ui";

export function moneyFromCents(cents: number, currency = "BRL") {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency }).format(cents / 100);
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const GOOD = new Set(["paid", "active", "sent", "success"]);
const WARN = new Set(["pending", "processing", "suspended", "delayed"]);
const BAD = new Set(["refunded", "chargeback", "cancelled", "expired", "dead", "locked", "rejected_terminal", "rejected_license", "rejected_email", "rejected_duplicate"]);

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge tone="neutral">—</Badge>;
  const tone = GOOD.has(status) ? "good" : WARN.has(status) ? "warn" : BAD.has(status) ? "bad" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}

export function Pager({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="toolbar support-pager">
      <span className="muted">
        Página {page} de {lastPage} · {total} registro(s)
      </span>
      <div className="row-actions">
        <Button disabled={page <= 1} onClick={() => onChange(page - 1)}>Anterior</Button>
        <Button disabled={page >= lastPage} onClick={() => onChange(page + 1)}>Próxima</Button>
      </div>
    </div>
  );
}
