import { expect, test, type Request } from "@playwright/test";

import { unique } from "./helpers";

test.use({ storageState: "e2e/.auth/customer.json" });

function idempotencyKey(request: Request): string {
  const value = request.headers()["idempotency-key"];
  expect(value).toBeTruthy();
  return value;
}

test.describe("idempotência financeira no navegador", () => {
  test("retry de lançamento reutiliza a chave e não duplica após refresh", async ({ page }) => {
    await page.goto("/lancamentos");
    const description = unique("Idempotência lançamento");
    await page.getByRole("button", { name: "Novo lançamento" }).last().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Descrição").fill(description);
    await dialog.getByLabel("Valor (R$)").fill("123,45");

    const requestPromise = page.waitForRequest(
      (request) => request.method() === "POST" && request.url().endsWith("/api/v1/transactions"),
    );
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().endsWith("/api/v1/transactions"),
    );
    await dialog.getByRole("button", { name: "Registrar lançamento" }).click();
    const firstRequest = await requestPromise;
    const firstResponse = await responsePromise;
    const firstBody = await firstResponse.json();
    const key = idempotencyKey(firstRequest);
    const payload = firstRequest.postDataJSON() as Record<string, unknown>;
    expect(firstResponse.status()).toBe(201);

    const retry = await page.request.post("/api/v1/transactions", {
      data: payload,
      headers: { "Idempotency-Key": key },
    });
    expect(retry.status()).toBe(201);
    expect((await retry.json()).id).toBe(firstBody.id);

    const conflict = await page.request.post("/api/v1/transactions", {
      data: { ...payload, amount: "999.00" },
      headers: { "Idempotency-Key": key },
    });
    expect(conflict.status()).toBe(409);

    await page.reload();
    await page.getByLabel("Buscar lançamento").fill(description);
    await expect(page.getByRole("cell", { name: description })).toHaveCount(1);

    await page.getByRole("button", { name: "Novo lançamento" }).last().click();
    const secondDialog = page.getByRole("dialog");
    await secondDialog.getByLabel("Descrição").fill(unique("Nova operação"));
    await secondDialog.getByLabel("Valor (R$)").fill("10,00");
    const secondRequestPromise = page.waitForRequest(
      (request) => request.method() === "POST" && request.url().endsWith("/api/v1/transactions"),
    );
    await secondDialog.getByRole("button", { name: "Registrar lançamento" }).click();
    const secondKey = idempotencyKey(await secondRequestPromise);
    expect(secondKey).not.toBe(key);
  });

  test("retry de pagamento de conta não cria segunda despesa", async ({ page }) => {
    await page.goto("/contas");
    const name = unique("Conta idempotente E2E");
    await page.getByRole("button", { name: "Nova conta" }).click();
    const createDialog = page.getByRole("dialog");
    await createDialog.getByLabel("Nome da conta").fill(name);
    await createDialog.getByLabel("Valor (R$)").fill("80,00");
    await createDialog.getByRole("button", { name: "Adicionar conta" }).click();
    await expect(page.getByText("Conta adicionada à agenda.")).toBeVisible();

    const row = page.getByRole("row").filter({ hasText: name });
    const payRequestPromise = page.waitForRequest(
      (request) => request.method() === "POST" && request.url().includes("/api/v1/bills/") && request.url().endsWith("/pay"),
    );
    const payResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().endsWith("/pay"),
    );
    await row.getByRole("button", { name: "Pagar" }).click();
    const payRequest = await payRequestPromise;
    const payResponse = await payResponsePromise;
    const payBody = await payResponse.json();
    const key = idempotencyKey(payRequest);
    expect(payResponse.status()).toBe(200);

    const retry = await page.request.post(payRequest.url(), {
      headers: { "Idempotency-Key": key },
    });
    expect(retry.status()).toBe(200);
    expect((await retry.json()).transaction_id).toBe(payBody.transaction_id);

    await page.reload();
    await expect(page.getByRole("row").filter({ hasText: name })).toHaveCount(1);
    await expect(page.getByRole("row").filter({ hasText: name }).getByText("Paga")).toBeVisible();

    await page.goto(`/lancamentos`);
    await page.getByLabel("Buscar lançamento").fill(name);
    await expect(page.getByRole("cell", { name })).toHaveCount(1);
  });

  test("retry de aporte não duplica saldo nem movimentação", async ({ page }) => {
    await page.goto("/metas");
    const name = unique("Meta idempotente E2E");
    await page.getByRole("button", { name: "Nova meta" }).click();
    const createDialog = page.getByRole("dialog");
    await createDialog.getByLabel("Nome da meta").fill(name);
    await createDialog.getByLabel("Valor-alvo (R$)").fill("1000,00");
    await createDialog.getByRole("button", { name: "Criar meta" }).click();
    await expect(page.getByText("Nova meta criada. O próximo sonho já tem um plano.")).toBeVisible();

    const card = page.getByRole("article").filter({ hasText: name });
    await card.getByRole("button", { name: "Aportar" }).click();
    const movementDialog = page.getByRole("dialog");
    await movementDialog.getByLabel("Valor (R$)").fill("100,00");
    const movementRequestPromise = page.waitForRequest(
      (request) => request.method() === "POST" && request.url().endsWith("/movements"),
    );
    const movementResponsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().endsWith("/movements"),
    );
    await movementDialog.getByRole("button", { name: "Guardar valor" }).click();
    const movementRequest = await movementRequestPromise;
    const movementResponse = await movementResponsePromise;
    const movementBody = await movementResponse.json();
    const key = idempotencyKey(movementRequest);
    expect(movementResponse.status()).toBe(201);

    const retry = await page.request.post(movementRequest.url(), {
      data: movementRequest.postDataJSON(),
      headers: { "Idempotency-Key": key },
    });
    expect(retry.status()).toBe(201);
    expect((await retry.json()).movement.id).toBe(movementBody.movement.id);

    const conflict = await page.request.post(movementRequest.url(), {
      data: { ...(movementRequest.postDataJSON() as Record<string, unknown>), amount: "50.00" },
      headers: { "Idempotency-Key": key },
    });
    expect(conflict.status()).toBe(409);

    await page.reload();
    const reloadedCard = page.getByRole("article").filter({ hasText: name });
    await expect(reloadedCard.getByText("R$ 100,00")).toBeVisible();
    await expect(reloadedCard.getByText("R$ 150,00")).toHaveCount(0);
  });
});
