import { expect, test } from "@playwright/test";

import { unique } from "./helpers";

test.use({ storageState: "e2e/.auth/customer.json" });

test.describe("fluxos financeiros do cliente", () => {
  test("cria, pesquisa e exclui lançamento", async ({ page }) => {
    await page.goto("/lancamentos");
    await expect(page.getByRole("heading", { name: "Receitas e despesas" })).toBeVisible();
    const description = unique("Mercado E2E");
    await page.getByRole("button", { name: "Novo lançamento" }).last().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Descrição").fill(description);
    await dialog.getByLabel("Valor (R$)").fill("123,45");
    await dialog.getByRole("button", { name: "Registrar lançamento" }).click();
    await expect(page.getByText("Lançamento registrado.")).toBeVisible();
    await page.getByLabel("Buscar lançamento").fill(description);
    await expect(page.getByRole("cell", { name: description })).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: description });
    await row.getByRole("button", { name: "Excluir lançamento" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Excluir" }).click();
    await expect(page.getByText("Lançamento excluído.")).toBeVisible();
    await expect(page.getByText(description)).toHaveCount(0);
  });

  test("cria conta, paga e desfaz pagamento", async ({ page }) => {
    await page.goto("/contas");
    const name = unique("Energia E2E");
    await page.getByRole("button", { name: "Nova conta" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Nome da conta").fill(name);
    await dialog.getByLabel("Valor (R$)").fill("80,00");
    await dialog.getByRole("button", { name: "Adicionar conta" }).click();
    await expect(page.getByText("Conta adicionada à agenda.")).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: name });
    await row.getByRole("button", { name: "Pagar" }).click();
    await expect(page.getByText("Conta marcada como paga e despesa registrada.")).toBeVisible();
    await expect(row.getByText("Paga")).toBeVisible();
    await row.getByRole("button", { name: "Desfazer" }).click();
    await expect(page.getByText("Pagamento desfeito. A despesa vinculada foi removida.")).toBeVisible();
  });

  test("cria cartão e acompanha limite", async ({ page }) => {
    await page.goto("/cartoes");
    const name = unique("Cartão E2E");
    await page.getByRole("button", { name: "Adicionar cartão" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Nome do cartão").fill(name);
    await dialog.getByLabel("Instituição").fill("Banco E2E");
    await dialog.getByLabel("Limite (R$)").fill("1000,00");
    await dialog.getByRole("button", { name: "Adicionar cartão" }).click();
    await expect(page.getByText("Cartão adicionado.")).toBeVisible();
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByText(/Limite de R\$\s*1\.000,00/)).toBeVisible();
  });

  test("cria meta e registra aporte", async ({ page }) => {
    await page.goto("/metas");
    const name = unique("Viagem E2E");
    await page.getByRole("button", { name: "Nova meta" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Nome da meta").fill(name);
    await dialog.getByLabel("Valor-alvo (R$)").fill("1000,00");
    await dialog.getByRole("button", { name: "Criar meta" }).click();
    await expect(page.getByText("Nova meta criada. O próximo sonho já tem um plano.")).toBeVisible();
    const card = page.getByRole("article").filter({ hasText: name });
    await card.getByRole("button", { name: "Aportar" }).click();
    const movement = page.getByRole("dialog");
    await movement.getByLabel("Valor (R$)").fill("100,00");
    await movement.getByRole("button", { name: "Guardar valor" }).click();
    await expect(page.getByText("Aporte registrado.")).toBeVisible();
    await expect(card.getByText("R$ 100,00")).toBeVisible();
  });

  test("dashboard, relatórios e CSV respondem", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Seu dinheiro, sob controle." })).toBeVisible();
    await expect(page.getByText("Receitas do mês")).toBeVisible();
    await page.goto("/relatorios");
    await expect(page.getByRole("heading", { name: "Relatórios financeiros" })).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Baixar CSV" }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
  });

  test("configurações exibem licença e sessões", async ({ page }) => {
    await page.goto("/configuracoes");
    await expect(page.getByRole("heading", { name: "Configurações" })).toBeVisible();
    await expect(page.getByText("Licença FortexaHome")).toBeVisible();
    await expect(page.getByText("Sessões ativas")).toBeVisible();
  });
});
