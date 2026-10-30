export type Theme = "claro" | "escuro" | "minimal";

export interface Tenant {
  id: string;
  name: string;
  currency: string;
  timezone: string;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: "owner" | "member";
  theme: Theme;
  created_at: string;
}

export interface LicenseInfo {
  id: string;
  status: string;
  code_last4: string;
  kind: string;
  activated_at: string | null;
  expires_at: string | null;
}

export interface AuthResponse {
  user: User;
  tenant: Tenant;
  license: LicenseInfo;
}

export interface LicenseStatus {
  id: string;
  status: string;
  code_last4: string;
  product_name: string;
  license_kind: string;
  activated_at: string | null;
  expires_at: string | null;
}

export interface Account {
  family_name: string;
  currency: string;
  timezone: string;
  theme: Theme;
  name: string;
  email: string;
}

export interface Category {
  id: string;
  name: string;
  kind: "income" | "expense";
  color: string;
  icon: string;
  is_system: boolean;
}

export type TransactionKind = "income" | "expense";
export type PaymentMethod = "pix" | "cash" | "debit" | "credit" | "transfer" | "boleto" | "other";

export interface Transaction {
  id: string;
  kind: TransactionKind;
  amount: string;
  occurred_on: string;
  description: string;
  category_id: string | null;
  category_name: string | null;
  payment_method: PaymentMethod;
  notes: string | null;
  card_id: string | null;
  bill_id: string | null;
  source: "manual" | "bill" | "import";
  created_at: string;
}

export interface TransactionSummary {
  income: string;
  expense: string;
  result: string;
  count: number;
}

export interface Bill {
  id: string;
  name: string;
  category_id: string | null;
  category_name: string | null;
  amount: string;
  due_on: string;
  status: "pending" | "paid";
  paid_at: string | null;
  recurrence: "none" | "monthly";
  parent_bill_id: string | null;
  notes: string | null;
  transaction_id: string | null;
  is_overdue: boolean;
}

export interface Card {
  id: string;
  name: string;
  institution: string;
  limit_amount: string;
  closing_day: number;
  due_day: number;
  archived: boolean;
  spent: string;
  available: string;
}

export interface Budget {
  id: string;
  category_id: string;
  category_name: string | null;
  competence_month: string;
  limit_amount: string;
  spent: string;
  available: string;
  percent: number;
}

export interface Goal {
  id: string;
  name: string;
  description: string | null;
  target_amount: string;
  target_date: string | null;
  icon: string;
  status: "active" | "completed" | "cancelled";
  saved_amount: string;
  remaining_amount: string;
  progress_percent: number;
  projected_monthly: string | null;
  created_at: string;
}

export interface GoalMovement {
  id: string;
  kind: "deposit" | "withdrawal";
  amount: string;
  occurred_on: string;
  note: string | null;
  created_at: string;
}

export interface GoalMovementResult {
  goal: Goal;
  movement: GoalMovement;
}

export interface DashboardData {
  period: { month: string; start: string; end: string; label: string };
  total_balance: string;
  income: string;
  expense: string;
  result: string;
  previous_income: string;
  previous_expense: string;
  income_change: number | null;
  expense_change: number | null;
  pending_bills_total: string;
  pending_bills_count: number;
  overdue_bills_count: number;
  series: { month: string; label: string; income: string; expense: string }[];
  categories: { name: string; color: string; amount: string; percent: number }[];
  recent_transactions: Transaction[];
  goals: { count: number; saved: string; target: string };
  budgets: { planned: string; spent: string; available: string; count: number };
  cards: { count: number; limit: string; spent: string; available: string };
}

export interface ReportData {
  start: string;
  end: string;
  income: string;
  expense: string;
  result: string;
  count: number;
  by_category: { name: string; color: string; amount: string; count: number; percent: number }[];
  by_month: { month: string; income: string; expense: string }[];
}

export interface SessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  current: boolean;
}
