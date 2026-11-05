import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import AuthPage from "./AuthPage";
import { AuthProvider, useAuth } from "../context/AuthContext";

const challenge = {
  activation_id: "e46286a5-62bb-4c20-a355-e434e260a6df",
  email_masked: "pe***@example.test",
  expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
  resend_at: new Date(Date.now() + 60_000).toISOString(),
};

const authResponse = {
  user: {
    id: "f1d809de-5722-46b4-a9a7-7d2bdbbe21be",
    name: "Pessoa Teste",
    email: "pessoa@example.test",
    role: "owner" as const,
    theme: "claro" as const,
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

function response(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function AuthStatus() {
  const { status } = useAuth();
  return <output aria-label="Estado da autenticação">{status}</output>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/entrar"]}>
      <AuthProvider>
        <AuthPage />
        <AuthStatus />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("ativação com confirmação de e-mail", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("only authenticates after the server confirms the code", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return response(401, { detail: "unauthorized" });
      if (path.endsWith("/auth/activate")) return response(202, challenge);
      if (path.endsWith("/auth/activate/confirm")) return response(201, authResponse);
      throw new Error(`Unexpected API request ${path} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();

    await screen.findByRole("tab", { name: "Ativar licença" });
    fireEvent.click(screen.getByRole("tab", { name: "Ativar licença" }));
    fireEvent.change(screen.getByLabelText("Seu nome"), { target: { value: "Pessoa Teste" } });
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "pessoa@example.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "SenhaSegura#2026" } });
    fireEvent.change(screen.getByLabelText("Código da licença"), { target: { value: "FH-TEST-1234" } });
    fireEvent.click(screen.getByRole("button", { name: /Criar minha conta/i }));

    expect(await screen.findByText("pe***@example.test")).toBeInTheDocument();
    expect(screen.getByText(/Registramos o pedido de envio/)).toBeInTheDocument();
    expect(screen.getByLabelText("Estado da autenticação")).toHaveTextContent("guest");
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/auth/activate/confirm"))).toBe(false);
    expect(localStorage.getItem("fortexahome-theme")).toBeNull();
    expect(sessionStorage.length).toBe(0);

    fireEvent.change(screen.getByLabelText("Código de verificação"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /Confirmar e entrar/i }));
    await waitFor(() => expect(screen.getByLabelText("Estado da autenticação")).toHaveTextContent("authenticated"));
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/auth/activate/confirm"))).toBe(true);
    expect(sessionStorage.length).toBe(0);
  });

  it("enables resend when the backend-provided 60 second interval ends and sends a new request", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-31T12:00:00.000Z"));
    const firstChallenge = {
      ...challenge,
      expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
      resend_at: new Date(Date.now() + 60_000).toISOString(),
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/auth/me")) return response(401, { detail: "unauthorized" });
      if (path.endsWith("/auth/activate")) return response(202, firstChallenge);
      if (path.endsWith("/auth/activate/resend")) {
        return response(200, {
          ...firstChallenge,
          expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
          resend_at: new Date(Date.now() + 60_000).toISOString(),
        });
      }
      throw new Error(`Unexpected API request ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Ativar licença" }));
    fireEvent.change(screen.getByLabelText("Seu nome"), { target: { value: "Pessoa Teste" } });
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "pessoa@example.test" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "SenhaSegura#2026" } });
    fireEvent.change(screen.getByLabelText("Código da licença"), { target: { value: "FH-TEST-1234" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Criar minha conta/i }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const resend = screen.getByRole("button", { name: /Reenviar código em/i });
    expect(resend).toBeDisabled();
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/auth/activate/resend"))).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    const enabledResend = screen.getByRole("button", { name: "Enviar novo código" });
    expect(enabledResend).toBeEnabled();
    await act(async () => {
      fireEvent.click(enabledResend);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/auth/activate/resend"))).toBe(true);
    expect(screen.getByRole("button", { name: /Reenviar código em/i })).toBeDisabled();
  });
});
