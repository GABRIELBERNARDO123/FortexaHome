import { expect, test } from "@playwright/test";

import {
  LOCKOUT_EMAIL,
  MEMBER_EMAIL,
  PASSWORD,
  READ_ONLY_EMAIL,
  REFUNDED_TRANSACTION,
  SUPPORT_TRANSACTION,
  loginCustomer,
  loginSupport,
} from "./helpers";

async function openOrder(page: import("@playwright/test").Page, transaction: string) {
  await page.goto("/backoffice/pedidos");
  await page.getByLabel("Buscar transação").fill(transaction);
  const row = page.getByRole("row").filter({ hasText: transaction });
  await expect(row).toBeVisible();
  await row.getByRole("link", { name: "Ver" }).click();
  await expect(page.getByRole("heading", { name: transaction })).toBeVisible();
}

test.describe("backoffice de suporte", () => {
  test("login, consultas, ação auditada e idempotência", async ({ browser }) => {
    const context = await browser.newContext({ storageState: "e2e/.auth/support.json" });
    const page = await context.newPage();
    await page.goto("/backoffice");
    await expect(page.getByRole("heading", { name: "Visão geral do suporte" })).toBeVisible();
    await page.getByRole("link", { name: "Pedidos" }).click();
    await expect(page.getByRole("heading", { name: "Pedidos e licenças" })).toBeVisible();
    await openOrder(page, SUPPORT_TRANSACTION);
    await expect(page.getByText("comprador.e2e@example.com")).toHaveCount(0);
    await expect(page.getByText(/••••/)).toBeVisible();

    await page.getByRole("button", { name: "Solicitar recuperação" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Justificativa").fill("Cliente confirmou perda do e-mail original");
    await dialog.getByRole("button", { name: "Enviar instruções" }).click();
    await expect(page.getByText("Instruções de recuperação enfileiradas.")).toBeVisible();

    await page.getByRole("button", { name: "Solicitar recuperação" }).click();
    const duplicate = page.getByRole("dialog");
    await duplicate.getByLabel("Justificativa").fill("Cliente confirmou perda do e-mail original");
    await duplicate.getByRole("button", { name: "Enviar instruções" }).click();
    await expect(duplicate.getByText("Instruções já solicitadas nesta hora")).toBeVisible();
    await duplicate.getByRole("button", { name: "Fechar" }).click();

    await page.getByRole("link", { name: "Auditoria" }).click();
    await expect(page.getByRole("heading", { name: "Trilha de auditoria" })).toBeVisible();
    await expect(page.getByText("SUPPORT_RECOVERY_INSTRUCTIONS").first()).toBeVisible();

    await openOrder(page, REFUNDED_TRANSACTION);
    await page.getByRole("button", { name: "Solicitar recuperação" }).click();
    const terminalDialog = page.getByRole("dialog");
    await terminalDialog.getByLabel("Justificativa").fill("Tentativa em pedido reembolsado");
    await terminalDialog.getByRole("button", { name: "Enviar instruções" }).click();
    await expect(terminalDialog.getByText("Pedido não permite recuperação")).toBeVisible();
    await terminalDialog.getByRole("button", { name: "Fechar" }).click();

    await page.getByRole("link", { name: "Licenças" }).click();
    await expect(page.getByRole("heading", { name: "Licenças", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Outbox" }).click();
    await expect(page.getByRole("heading", { name: "Transactional outbox" })).toBeVisible();
    await expect(page.getByText("payload_encrypted")).toHaveCount(0);
    await expect(page.getByRole("cell").filter({ hasText: "license_delivery" }).first()).toBeVisible();
    await context.close();
  });

  test("perfil de leitura não vê ação e recebe 403 na API", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginSupport(page, READ_ONLY_EMAIL);
    await openOrder(page, SUPPORT_TRANSACTION);
    await expect(page.getByRole("button", { name: "Solicitar recuperação" })).toHaveCount(0);
    const orderId = page.url().split("/").pop();
    const response = await page.request.post(
      `/api/v1/support/orders/${orderId}/recovery-instructions`,
      { data: { justification: "Tentativa sem permissão de ação" } },
    );
    expect(response.status()).toBe(403);
    await context.close();
  });

  test("cliente owner e member não entram no backoffice", async ({ browser }) => {
    for (const email of [undefined, MEMBER_EMAIL]) {
      const context = await browser.newContext();
      const page = await context.newPage();
      await loginCustomer(page, email);
      await page.goto("/backoffice");
      await expect(page).toHaveURL(/\/backoffice\/login/);
      await expect(page.getByRole("heading", { name: "Console de suporte" })).toBeVisible();
      await context.close();
    }
  });

  test("cookie administrativo inválido volta ao login", async ({ browser }) => {
    const context = await browser.newContext();
    await context.addCookies([
      { name: "fh_support_session", value: "invalido", domain: "127.0.0.1", path: "/api/v1/support" },
    ]);
    const page = await context.newPage();
    await page.goto("/backoffice");
    await expect(page).toHaveURL(/\/backoffice\/login/);
    await context.close();
  });

  test("login inválido e lockout do operador", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await page.goto("/backoffice/login");
      await page.getByLabel("E-mail do operador").fill(LOCKOUT_EMAIL);
      await page.getByLabel("Senha").fill("senha-incorreta");
      await page.getByRole("button", { name: /^Entrar$/ }).click();
      await expect(page.getByRole("alert")).toContainText("Credenciais inválidas");
    }
    await page.getByLabel("Senha").fill("SuporteE2e#2026");
    await page.getByRole("button", { name: /^Entrar$/ }).click();
    await expect(page.getByRole("alert")).toContainText("Credenciais inválidas");
    await context.close();
  });
});
