import { expect, test } from "@playwright/test";

import { unique } from "./helpers";

test.use({ storageState: "e2e/.auth/customer.json" });

test.describe("gestão de categorias", () => {
  test("owner cria, edita, arquiva, reativa e exclui categoria", async ({ page }) => {
    await page.goto("/categorias");
    await expect(page.getByRole("heading", { name: "Categorias", exact: true })).toBeVisible();
    const name = unique("Categoria E2E");

    await page.getByRole("button", { name: "Nova categoria" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel("Nome da categoria").fill(name);
    await dialog.getByLabel("Tipo").selectOption("income");
    await dialog.getByLabel("Ícone").selectOption("gift");
    await dialog.getByRole("button", { name: "Criar categoria" }).click();
    await expect(page.getByText("Categoria criada.")).toBeVisible();

    let row = page.getByRole("article").filter({ hasText: name });
    await expect(row.getByText("Receita")).toBeVisible();
    await expect(row.getByText("Sem uso")).toBeVisible();

    await page.getByRole("button", { name: "Nova categoria" }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Nome da categoria").fill(name);
    await dialog.getByLabel("Tipo").selectOption("income");
    await dialog.getByRole("button", { name: "Criar categoria" }).click();
    await expect(dialog.getByText(/Já existe uma categoria com este nome/)).toBeVisible();
    await dialog.getByRole("button", { name: "Fechar" }).click();

    const editedName = `${name} editada`;
    await row.getByRole("button", { name: `Editar categoria ${name}` }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Nome da categoria").fill(editedName);
    await dialog.getByRole("button", { name: "Salvar categoria" }).click();
    await expect(page.getByText("Categoria atualizada.")).toBeVisible();

    row = page.getByRole("article").filter({ hasText: editedName });
    await row.getByRole("button", { name: `Arquivar categoria ${editedName}` }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Arquivar" }).click();
    await expect(page.getByText("Categoria arquivada. O histórico foi preservado.")).toBeVisible();
    await expect(row.getByText("Arquivada")).toBeVisible();

    await row.getByRole("button", { name: `Reativar categoria ${editedName}` }).click();
    await expect(page.getByText("Categoria reativada.")).toBeVisible();
    await expect(row.getByText("Arquivada")).toHaveCount(0);

    await row.getByRole("button", { name: `Excluir categoria ${editedName}` }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Excluir" }).click();
    await expect(page.getByText("Categoria excluída.")).toBeVisible();
    await expect(page.getByText(editedName)).toHaveCount(0);
  });

  test("categoria em uso é arquivada e o histórico permanece editável", async ({ page }) => {
    await page.goto("/categorias");
    const name = unique("Categoria em uso");
    const description = unique("Lançamento categoria arquivada");

    await page.getByRole("button", { name: "Nova categoria" }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel("Nome da categoria").fill(name);
    await dialog.getByRole("button", { name: "Criar categoria" }).click();
    await expect(page.getByText("Categoria criada.")).toBeVisible();

    await page.goto("/lancamentos");
    await page.getByRole("button", { name: "Novo lançamento" }).last().click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel("Descrição").fill(description);
    await dialog.getByLabel("Valor (R$)").fill("12,34");
    await dialog.getByLabel("Categoria").selectOption({ label: name });
    await dialog.getByRole("button", { name: "Registrar lançamento" }).click();
    await expect(page.getByText("Lançamento registrado.")).toBeVisible();

    await page.goto("/categorias");
    let row = page.getByRole("article").filter({ hasText: name });
    await expect(row.getByText(/Em uso em 1 registro/)).toBeVisible();
    await row.getByRole("button", { name: `Arquivar categoria ${name}` }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Arquivar" }).click();
    await expect(page.getByText("Categoria arquivada. O histórico foi preservado.")).toBeVisible();

    row = page.getByRole("article").filter({ hasText: name });
    await expect(row.getByText("Arquivada")).toBeVisible();
    await expect(row.getByRole("button", { name: `Excluir categoria ${name}` })).toBeDisabled();

    await page.goto("/lancamentos");
    await page.getByLabel("Buscar lançamento").fill(description);
    const transactionRow = page.getByRole("row").filter({ hasText: description });
    await expect(transactionRow.getByText(name)).toBeVisible();
    await transactionRow.getByRole("button", { name: "Editar lançamento" }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel("Categoria").locator("option:checked")).toHaveText(
      new RegExp(`${name} \\(arquivada\\)`),
    );
    await dialog.getByLabel("Descrição").fill(`${description} editado`);
    await dialog.getByRole("button", { name: "Salvar alterações" }).click();
    await expect(page.getByText("Lançamento atualizado.")).toBeVisible();
    await expect(page.getByText(`${description} editado`)).toBeVisible();
  });

  test("membro consulta categorias, mas não pode gerenciá-las", async ({ browser }) => {
    const context = await browser.newContext({ storageState: "e2e/.auth/member.json" });
    const page = await context.newPage();
    await page.goto("/categorias");
    await expect(page.getByRole("heading", { name: "Categorias", exact: true })).toBeVisible();
    await expect(page.getByText(/Apenas o responsável pela conta pode criar/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Nova categoria" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Editar categoria/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Arquivar categoria/ })).toHaveCount(0);

    const listed = await page.request.get("/api/v1/categories");
    expect(listed.ok()).toBeTruthy();
    const categoryId = (await listed.json())[0].id;
    const forbidden = await page.request.patch(`/api/v1/categories/${categoryId}`, {
      data: { archived: true },
    });
    expect(forbidden.status()).toBe(403);
    await context.close();
  });

  test("categorias de um tenant não aparecem nem podem ser alteradas em outro", async ({ browser }) => {
    const ownerContext = await browser.newContext({ storageState: "e2e/.auth/customer.json" });
    const ownerPage = await ownerContext.newPage();
    const name = unique("Categoria isolada");
    const created = await ownerPage.request.post("/api/v1/categories", {
      data: { name, kind: "expense" },
    });
    expect(created.ok()).toBeTruthy();
    const categoryId = (await created.json()).id;

    const otherContext = await browser.newContext({ storageState: "e2e/.auth/customer2.json" });
    const otherPage = await otherContext.newPage();
    await otherPage.goto("/categorias");
    await expect(otherPage.getByRole("heading", { name: "Categorias", exact: true })).toBeVisible();
    await expect(otherPage.getByText(name)).toHaveCount(0);

    const forbidden = await otherPage.request.patch(`/api/v1/categories/${categoryId}`, {
      data: { name: "Invasão de tenant" },
    });
    expect(forbidden.status()).toBe(404);
    await ownerContext.close();
    await otherContext.close();
  });
});
