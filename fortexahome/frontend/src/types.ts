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

export interface ActivationChallenge {
  activation_id: string;
  email_masked: string;
  expires_at: string | null;
  resend_at: string;
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
  archived: boolean;
  usage_count: number;
  in_use: boolean;
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

export interface SupportOperator {
  id: string;
  name: string;
  email: string;
  role: "support_read" | "support_operator";
  status: "active" | "disabled";
  created_at: string;
  last_login_at: string | null;
}

export interface SupportAuthResponse {
  operator: SupportOperator;
  permissions: string[];
}

export interface SupportOrderListItem {
  id: string;
  transaction: string;
  provider: string;
  status: string;
  product_slug: string;
  product_name: string;
  created_at: string;
  last_event_at: string | null;
  license_id: string | null;
  license_status: string | null;
  license_code_last4: string | null;
  delivery_status: string | null;
}

export interface SupportDelivery {
  id: string;
  event_type: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  processed_at: string | null;
  sent_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface SupportOrderDetail {
  order: {
    id: string;
    transaction: string;
    provider: string;
    status: string;
    created_at: string;
    updated_at: string;
    amount_cents: number;
    currency: string;
    buyer_email_masked: string | null;
  };
  product: { slug: string; name: string };
  license: {
    id: string;
    status: string;
    code_last4: string;
    tenant_id: string | null;
    issued_at: string;
    activated_at: string | null;
    expires_at: string | null;
    revoked_at: string | null;
  } | null;
  events: {
    event_type: string;
    provider_event_created_at: string | null;
    processed_at: string;
    state_priority: number;
  }[];
  deliveries: SupportDelivery[];
}

export interface SupportLicenseItem {
  id: string;
  code_last4: string;
  status: string;
  product_slug: string;
  product_name: string;
  order_id: string | null;
  transaction: string | null;
  tenant_id: string | null;
  issued_at: string;
  activated_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface SupportOutboxItem {
  id: string;
  event_type: string;
  status: string;
  aggregate_id: string | null;
  license_id: string | null;
  order_id: string | null;
  transaction: string | null;
  order_status: string | null;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  processed_at: string | null;
  sent_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface SupportAuditItem {
  id: string;
  operator_id: string | null;
  operator_masked: string | null;
  operation: string;
  order_id: string | null;
  license_id: string | null;
  outbox_id: string | null;
  justification: string | null;
  result: string;
  created_at: string;
}

export interface SupportDashboard {
  orders: Record<string, number>;
  licenses: Record<string, number>;
  outbox: Record<string, number>;
  dead_letters: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PrivacyRequest {
  id: string;
  protocol: string;
  request_type: string;
  status: string;
  scope: string;
  reason: string | null;
  retention_summary: Record<string, unknown> | null;
  result_summary: string | null;
  review_justification: string | null;
  created_at: string;
  updated_at: string;
  reviewed_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
}

export interface PrivacyRequestEvent {
  id: string;
  event_type: string;
  status: string | null;
  actor_type: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface PrivacyRequestDetail extends PrivacyRequest {
  events: PrivacyRequestEvent[];
}
