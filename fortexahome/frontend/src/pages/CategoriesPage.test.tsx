import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../context/AuthContext";
import { ToastProvider } from "../context/ToastContext";
import CategoriesPage from "./CategoriesPage";

function response(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function authResponse(role: "owner" | "member") {
  return {
    user: {
      id: "f1d809de-5722-46b4-a9a7-7d2bdbbe21be",
      name: role === "owner" ? "Pessoa Owner" : "Pessoa Member",
      email: "pessoa@example.test",
      role,
      theme: "claro",
      created_at: new Date().toISOString(),
    },
    tenant: {
      id: "4d02f9d3-7f83-4741-ae70-08c6f9d58ef4",
      name: "Família",
      currency: "BRL",
      timezone: "America/Sao_Paulo",
    },
    license: {
      id: "84015f72-52a8-4b5e-b14e-20f5f74cc617",
      status: "active",
      code_last4: "ABCD",
      kind: "lifetime",
      activated_at: new Date().toISOString(),
      expires_at: null,
    },
  };
}

const categories = [
  {
    id: "2770e2b8-1af4-4d23-a88a-0f64f0de70e1",
    name: "Alimentação",
    kind: "expense",
    color: "#f29a00",
    icon: "utensils",
    is_system: true,
    archived: false,
    usage_count: 2,
    in_use: true,
  },
  {
    id: "a98e993e-32db-4cd7-849a-d6f31be0c4fa",
    name: "Categoria pessoal",
    kind: "expense",
    color: "#123abc",
    icon: "tag",
    is_system: false,
    archived: false,
    usage_count: 0,
    in_use: false,
  },
];

function renderPage(role: "owner" | "member") {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return response(200, authResponse(role));
      if (path.endsWith("/categories")) return response(200, categories);
      throw new Error(`Unexpected API request ${path}`);
    }),
  );
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ToastProvider>
          <CategoriesPage />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("gestão de categorias", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("mostra ações de owner e o uso das categorias", async () => {
    renderPage("owner");
    expect(await screen.findByText("Categoria pessoal")).toBeInTheDocument();
    expect(screen.getByText("Em uso em 2 registro(s)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nova categoria" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar categoria Categoria pessoal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Arquivar categoria Categoria pessoal" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Arquivar categoria Alimentação" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Excluir categoria Alimentação" })).not.toBeInTheDocument();
  });

  it("mantém member em modo somente leitura", async () => {
    renderPage("member");
    expect(await screen.findByText("Categoria pessoal")).toBeInTheDocument();
    expect(screen.getByText(/Apenas o responsável pela conta pode criar/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nova categoria" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Editar categoria/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Arquivar categoria/ })).not.toBeInTheDocument();
  });
});
