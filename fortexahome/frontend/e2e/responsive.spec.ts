import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow } from "./helpers";

const viewports = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "tablet", width: 834, height: 1112 },
  { name: "mobile", width: 390, height: 844 },
];

test.describe("responsividade e acessibilidade básica", () => {
  for (const viewport of viewports) {
    test(`dashboard e cliente em ${viewport.name}`, async ({ browser }) => {
      const context = await browser.newContext({ viewport, storageState: "e2e/.auth/customer.json" });
      const page = await context.newPage();
      await page.goto("/");
      await expect(page.getByRole("heading", { name: "Seu dinheiro, sob controle." })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      if (viewport.name === "mobile") {
        await page.getByRole("button", { name: "Abrir menu" }).click();
        await expect(page.getByRole("link", { name: "Receitas e despesas" })).toBeVisible();
        await expectNoHorizontalOverflow(page);
      }
      await context.close();
    });
  }

  test("categorias em celular", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      storageState: "e2e/.auth/customer.json",
    });
    const page = await context.newPage();
    await page.goto("/categorias");
    await expect(page.getByRole("heading", { name: "Categorias", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Nova categoria" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await context.close();
  });

  test("backoffice em celular", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      storageState: "e2e/.auth/support.json",
    });
    const page = await context.newPage();
    await page.goto("/backoffice");
    await expect(page.getByRole("heading", { name: "Visão geral do suporte" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.getByRole("link", { name: "Pedidos" }).click();
    await expect(page.getByRole("heading", { name: "Pedidos e licenças" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await context.close();
  });

  test("formulários usam labels acessíveis e erro é anunciado", async ({ page }) => {
    await page.goto("/entrar");
    await expect(page.getByLabel("E-mail")).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Senha" })).toBeVisible();
    await page.getByLabel("E-mail").fill("invalido@example.test");
    await page.getByRole("textbox", { name: "Senha" }).fill("senha-errada");
    await page.getByLabel("E-mail").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("textbox", { name: "Senha" })).toBeFocused();
    await page.getByRole("button", { name: /Entrar na minha conta/i }).click();
    await expect(page.getByRole("alert")).toBeVisible();
  });
});
