import { expect, test } from "@playwright/test";

import {
  ACTIVATION_CODE,
  ACTIVATION_EMAIL,
  ACTIVATION_NAME,
  PASSWORD,
  RECOVERY_EMAIL,
  RECOVERY_NAME,
} from "./helpers";

test.describe("ativação e recuperação de licença", () => {
  test("ativa com código de e-mail controlado e entra na conta", async ({ page }) => {
    await page.goto("/entrar");
    await page.getByRole("tab", { name: "Ativar licença" }).click();
    await page.getByLabel("Seu nome").fill(ACTIVATION_NAME);
    await page.getByLabel("E-mail").fill(ACTIVATION_EMAIL);
    await page.getByRole("textbox", { name: "Senha" }).fill(PASSWORD);
    await page.getByLabel("Código da licença").fill(ACTIVATION_CODE);
    await page.getByRole("button", { name: /Criar minha conta/i }).click();

    await expect(page.getByRole("heading", { name: "Confirme seu e-mail." })).toBeVisible();
    await page.getByLabel("Código de verificação").fill("000000");
    await page.getByRole("button", { name: /Confirmar e entrar/i }).click();
    await expect(page.getByRole("alert").first()).toBeVisible();

    await page.getByLabel("Código de verificação").fill("123456");
    await page.getByRole("button", { name: /Confirmar e entrar/i }).click();
    await expect(page.getByRole("heading", { name: "Seu dinheiro, sob controle." })).toBeVisible();
  });

  test("recupera licença não ativada com resposta genérica e código de e-mail", async ({ page }) => {
    await page.goto("/entrar");
    await page.getByRole("tab", { name: "Recuperar acesso" }).click();
    await page.getByLabel("Seu nome").fill(RECOVERY_NAME);
    await page.getByLabel("E-mail da compra").fill(RECOVERY_EMAIL);
    await page.getByRole("textbox", { name: "Senha" }).fill(PASSWORD);
    await page.getByRole("button", { name: /Enviar instruções/i }).click();

    await expect(page.getByRole("heading", { name: "Confira seu e-mail" })).toBeVisible();
    await expect(page.getByText(/Se houver um acesso pendente/i)).toBeVisible();
    await page.getByRole("textbox", { name: "Código de recuperação" }).fill("654321");
    await page.getByRole("button", { name: /Confirmar e entrar/i }).click();
    await expect(page.getByRole("heading", { name: "Seu dinheiro, sob controle." })).toBeVisible();
  });
});
