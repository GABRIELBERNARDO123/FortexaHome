const brl = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const MONTHS = [
  "janeiro",
  "fevereiro",
  "março",
  "abril",
  "maio",
  "junho",
  "julho",
  "agosto",
  "setembro",
  "outubro",
  "novembro",
  "dezembro",
];

const SHORT_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export function money(value: string | number | null | undefined): string {
  return brl.format(Number(value || 0));
}

export function number(value: string | number | null | undefined): number {
  return Number(value || 0);
}

export function dateLabel(value: string | null | undefined): string {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  if (!year || !month || !day) return value;
  return `${day}/${month}/${year}`;
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  if (!year || !month || !day) return value;
  return `${day}/${month}`;
}

let defaultTimeZone: string | undefined;

export function setDefaultTimeZone(timeZone: string | undefined): void {
  defaultTimeZone = timeZone || undefined;
}

export function todayISO(timeZone: string | undefined = defaultTimeZone): string {
  if (timeZone) {
    try {
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).formatToParts(new Date());
      const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
      if (value.year && value.month && value.day) {
        return `${value.year}-${value.month}-${value.day}`;
      }
    } catch {
      // Fuso inválido: usa o fuso do navegador.
    }
  }
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

export function currentMonth(timeZone?: string): string {
  return todayISO(timeZone).slice(0, 7);
}

export function monthLabel(month: string): string {
  const [year, monthNumber] = month.split("-").map(Number);
  if (!year || !monthNumber) return month;
  const name = MONTHS[monthNumber - 1] || month;
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} de ${year}`;
}

export function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const index = year * 12 + (monthNumber - 1) + delta;
  const nextYear = Math.floor(index / 12);
  const nextMonth = (index % 12) + 1;
  return `${String(nextYear).padStart(4, "0")}-${String(nextMonth).padStart(2, "0")}`;
}

export function monthBounds(month: string): { start: string; end: string } {
  const [year, monthNumber] = month.split("-").map(Number);
  const lastDay = new Date(year, monthNumber, 0).getDate();
  return {
    start: `${month}-01`,
    end: `${month}-${String(lastDay).padStart(2, "0")}`,
  };
}

export function monthName(month: string): string {
  const monthNumber = Number(month.split("-")[1]);
  return MONTHS[monthNumber - 1] || month;
}

export function shortMonthLabel(month: string): string {
  const monthNumber = Number(month.split("-")[1]);
  return SHORT_MONTHS[monthNumber - 1] || month;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(1).replace(".", ",")}%`;
}

export function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

export function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Bom dia";
  if (hour < 18) return "Boa tarde";
  return "Boa noite";
}

export function toNumberInput(value: string | number): string {
  return String(value).replace(".", ",");
}

export function parseBRLAmountToCents(input: string): number | null {
  let value = input
    .trim()
    .replace(/\u00a0/g, " ")
    .replace(/R\$\s*/gi, "")
    .replace(/\s+/g, "");

  if (!value) return null;
  if (value.startsWith("+")) value = value.slice(1);
  if (value.startsWith("-")) return null;

  let integerPart: string;
  let fractionPart: string;

  if (value.includes(",")) {
    if ((value.match(/,/g) || []).length !== 1) return null;
    const [rawInteger, rawFraction] = value.split(",");
    if (!rawInteger || !rawFraction) return null;
    if (!/^(\d{1,3}(\.\d{3})+|\d+)$/.test(rawInteger)) return null;
    if (!/^\d{1,2}$/.test(rawFraction)) return null;
    integerPart = rawInteger.replace(/\./g, "");
    fractionPart = rawFraction;
  } else if (/^\d{1,3}(\.\d{3})+$/.test(value)) {
    integerPart = value.replace(/\./g, "");
    fractionPart = "";
  } else if (/^\d+(\.\d{1,2})?$/.test(value)) {
    [integerPart, fractionPart = ""] = value.split(".");
  } else {
    return null;
  }

  if (!/^\d+$/.test(integerPart) || !/^\d{0,2}$/.test(fractionPart)) return null;

  const cents = Number(integerPart) * 100 + Number(fractionPart.padEnd(2, "0"));
  return Number.isSafeInteger(cents) && cents > 0 ? cents : null;
}

export function centsToApiDecimal(cents: number): string {
  const integerPart = Math.floor(cents / 100);
  const fractionPart = String(cents % 100).padStart(2, "0");
  return `${integerPart}.${fractionPart}`;
}
