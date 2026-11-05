import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, PASSWORD, PRIVACY_MEMBER_EMAIL, PRIVACY_OWNER_EMAIL } from "./helpers";

test.describe("privacidade e exclusão de conta", () => {
  test("owner compartilhado, member com reautenticação e aprovação do suporte", async ({ browser }) => {
    const ownerContext = await browser.newContext({ storageState: "e2e/.auth/privacy-owner.json" });
    const memberContext = await browser.newContext({ storageState: "e2e/.auth/privacy-member.json" });
    const supportContext = await browser.newContext({ storageState: "e2e/.auth/support.json" });
    const ownerPage = await ownerContext.newPage();
    const memberPage = await memberContext.newPage();
    const supportPage = await supportContext.newPage();

    try {
      await ownerPage.goto("/configuracoes");
      await expect(ownerPage.getByRole("heading", { name: "Configurações" })).toBeVisible();
      await expect(ownerPage.getByText("Privacidade e exclusão")).toBeVisible();
      await ownerPage.getByRole("button", { name: "Solicitar", exact: true }).click();
      const ownerDialog = ownerPage.getByRole("dialog");
      await ownerDialog.getByLabel("Senha atual").fill(PASSWORD);
      await ownerDialog.getByLabel("Motivo (opcional)").fill("Encerrar conta familiar");
      await ownerDialog.getByRole("button", { name: "Confirmar solicitação" }).click();
      await expect(ownerPage.getByText(/registrada com status awaiting_review/)).toBeVisible();
      await expect(ownerPage.getByRole("heading", { name: "Configurações" })).toBeVisible();

      const protocolText = await ownerPage.locator(".session-row strong").filter({ hasText: "PRIV-" }).first().textContent();
      const protocol = protocolText?.match(/PRIV-\d{8}-[A-Z0-9]+/)?.[0];
      expect(protocol).toBeTruthy();

      await memberPage.goto("/configuracoes");
      await memberPage.getByRole("button", { name: "Solicitar", exact: true }).click();
      const memberDialog = memberPage.getByRole("dialog");
      await memberDialog.getByLabel("Senha atual").fill("senha-incorreta");
      await memberDialog.getByRole("button", { name: "Confirmar solicitação" }).click();
      await expect(memberDialog.getByText("Senha atual incorreta")).toBeVisible();
      await memberDialog.getByLabel("Senha atual").fill(PASSWORD);
      await memberDialog.getByRole("button", { name: "Confirmar solicitação" }).click();
      await expect(memberPage).toHaveURL(/\/entrar/);
      const memberLogin = await memberContext.request.post("/api/v1/auth/login", {
        data: { email: PRIVACY_MEMBER_EMAIL, password: PASSWORD },
      });
      expect(memberLogin.ok()).toBeFalsy();

      await supportPage.goto("/backoffice/privacidade");
      await expect(supportPage.getByRole("heading", { name: "Solicitações de titulares" })).toBeVisible();
      const row = supportPage.getByRole("row").filter({ hasText: protocol! });
      await expect(row).toBeVisible();
      await row.getByRole("button", { name: "Aprovar" }).click();
      const supportDialog = supportPage.getByRole("dialog");
      await supportDialog.getByLabel("Justificativa").fill("Member desvinculado; encerramento do tenant aprovado.");
      await supportDialog.getByRole("button", { name: "Aprovar e executar" }).click();
      await expect(supportPage.getByText("Solicitação aprovada e executada.")).toBeVisible();

      await ownerPage.reload();
      await expect(ownerPage).toHaveURL(/\/entrar/);
      const ownerLogin = await ownerContext.request.post("/api/v1/auth/login", {
        data: { email: PRIVACY_OWNER_EMAIL, password: PASSWORD },
      });
      expect(ownerLogin.ok()).toBeFalsy();
    } finally {
      await ownerContext.close();
      await memberContext.close();
      await supportContext.close();
    }
  });

  test("painel de privacidade permanece legível em celular", async ({ browser }) => {
    const context = await browser.newContext({
      storageState: "e2e/.auth/customer.json",
      viewport: { width: 390, height: 844 },
    });
    const page = await context.newPage();
    try {
      await page.goto("/configuracoes");
      await expect(page.getByRole("heading", { name: "Configurações" })).toBeVisible();
      await expect(page.getByText("Privacidade e exclusão")).toBeVisible();
      await expect(page.getByText(/Membros podem encerrar apenas os próprios dados pessoais/)).toBeVisible();
      await expectNoHorizontalOverflow(page);
    } finally {
      await context.close();
    }
  });
});
