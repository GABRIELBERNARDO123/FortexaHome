import { expect, type Page } from "@playwright/test";

export const CUSTOMER_EMAIL = "cliente.e2e@example.com";
export const MEMBER_EMAIL = "membro.e2e@example.com";
export const CUSTOMER2_EMAIL = "cliente2.e2e@example.com";
export const PRIVACY_OWNER_EMAIL = "privacidade.owner.e2e@example.com";
export const PRIVACY_MEMBER_EMAIL = "privacidade.member.e2e@example.com";
export const PASSWORD = "E2eSenha#2026";
export const ACTIVATION_NAME = "Cliente Ativação";
export const ACTIVATION_EMAIL = "ativacao.e2e@example.com";
export const ACTIVATION_CODE = "FH-E2E-ATIV-0001";
export const RECOVERY_NAME = "Cliente Recuperação";
export const RECOVERY_EMAIL = "recuperacao.e2e@example.com";
export const RECOVERY_CODE = "FH-E2E-REC-0001";
export const SUPPORT_EMAIL = "suporte.e2e@example.com";
export const READ_ONLY_EMAIL = "leitura.e2e@example.com";
export const LOCKOUT_EMAIL = "lockout.e2e@example.com";
export const SUPPORT_PASSWORD = "SuporteE2e#2026";
export const SUPPORT_TRANSACTION = "TX-E2E-0001";
export const REFUNDED_TRANSACTION = "TX-E2E-REF-0001";

export function unique(prefix: string) {
  return `${prefix} ${Date.now()}-${Math.floor(Math.random() * 10_000)}`;
}

export async function loginCustomer(page: Page, email = CUSTOMER_EMAIL) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail").fill(email);
  await page.getByRole("textbox", { name: "Senha" }).fill(PASSWORD);
  await page.getByRole("button", { name: /Entrar na minha conta/i }).click();
  await expect(page.getByRole("heading", { name: "Seu dinheiro, sob controle." })).toBeVisible();
}

export async function loginSupport(page: Page, email = SUPPORT_EMAIL) {
  await page.goto("/backoffice/login");
  await page.getByLabel("E-mail do operador").fill(email);
  await page.getByLabel("Senha").fill(SUPPORT_PASSWORD);
  await page.getByRole("button", { name: /^Entrar$/ }).click();
  await expect(page.getByRole("heading", { name: "Visão geral do suporte" })).toBeVisible();
}

export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}
