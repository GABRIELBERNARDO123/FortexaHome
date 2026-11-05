import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SupportAuthProvider } from "../../context/SupportAuthContext";
import SupportLoginPage from "./SupportLoginPage";

function response(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("backoffice de suporte", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("autentica o operador e navega para o backoffice", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/support/auth/me")) return response(401, { detail: "unauthorized" });
      if (path.endsWith("/support/auth/login")) {
        return response(200, {
          operator: {
            id: "740d3b9e-4b12-4f6c-a56a-3d0d7f2a3e55",
            name: "Operador Teste",
            email: "operador@example.test",
            role: "support_read",
            status: "active",
            created_at: new Date().toISOString(),
            last_login_at: null,
          },
          permissions: ["support:read"],
        });
      }
      throw new Error(`Unexpected API request ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/backoffice/login"]}>
        <Routes>
          <Route
            path="/backoffice/login"
            element={
              <SupportAuthProvider>
                <SupportLoginPage />
              </SupportAuthProvider>
            }
          />
          <Route path="/backoffice" element={<div>Console carregado</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const email = await screen.findByLabelText("E-mail do operador");
    fireEvent.change(email, { target: { value: "operador@example.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "SupportPass#2026" } });
    fireEvent.click(screen.getByRole("button", { name: /Entrar/i }));

    await waitFor(() => expect(screen.getByText("Console carregado")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/support/auth/login"))).toBe(true);
  });
});
