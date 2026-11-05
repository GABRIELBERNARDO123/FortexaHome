import { expect, test } from "@playwright/test";

import { CUSTOMER_EMAIL, PASSWORD, expectNoHorizontalOverflow, loginCustomer } from "./helpers";

test.describe("autenticação do cliente", () => {
  test("rota protegida redireciona visitante para o login", async ({ page }) => {
    await page.goto("/lancamentos");
    await expect(page).toHaveURL(/\/entrar$/);
    await expect(page.getByRole("tab", { name: "Entrar" })).toBeVisible();
  });

  test("sessão inválida ou expirada volta ao login", async ({ browser }) => {
    const context = await browser.newContext();
    await context.addCookies([{ name: "fh_session", value: "sessao-expirada", domain: "127.0.0.1", path: "/" }]);
    const page = await context.newPage();
    await page.goto("/");
    await expect(page).toHaveURL(/\/entrar$/);
    await context.close();
  });

  test("credenciais inválidas mostram mensagem genérica", async ({ page }) => {
    await page.goto("/entrar");
    await page.getByLabel("E-mail").fill(CUSTOMER_EMAIL);
    await page.getByRole("textbox", { name: "Senha" }).fill("senha-incorreta");
    await page.getByRole("button", { name: /Entrar na minha conta/i }).click();
    await expect(page.getByRole("alert")).toContainText("E-mail ou senha inválidos");
  });

  test("login válido persiste a sessão e logout encerra", async ({ page }) => {
    await loginCustomer(page);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Seu dinheiro, sob controle." })).toBeVisible();
    await page.getByRole("button", { name: "Sair da conta" }).click();
    await expect(page).toHaveURL(/\/entrar$/);
    await expect(page.getByRole("tab", { name: "Entrar" })).toBeVisible();
  });

  test("dashboard não cria scroll horizontal no desktop", async ({ page }) => {
    await loginCustomer(page);
    await expectNoHorizontalOverflow(page);
  });
});
