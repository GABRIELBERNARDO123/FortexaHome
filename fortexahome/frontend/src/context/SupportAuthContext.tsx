import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiError, api } from "../lib/api";
import type { SupportAuthResponse } from "../types";

type SupportStatus = "loading" | "guest" | "authenticated";

interface SupportAuthValue {
  status: SupportStatus;
  auth: SupportAuthResponse | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const SupportAuthContext = createContext<SupportAuthValue | null>(null);

export function SupportAuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SupportStatus>("loading");
  const [auth, setAuth] = useState<SupportAuthResponse | null>(null);

  useEffect(() => {
    let active = true;
    api<SupportAuthResponse>("/support/auth/me")
      .then((result) => {
        if (!active) return;
        setAuth(result);
        setStatus("authenticated");
      })
      .catch(() => {
        if (active) setStatus("guest");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const handler = () => {
      setAuth(null);
      setStatus("guest");
    };
    window.addEventListener("fh:support-unauthorized", handler);
    return () => window.removeEventListener("fh:support-unauthorized", handler);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api<SupportAuthResponse>("/support/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setAuth(result);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/support/auth/logout", { method: "POST" });
    } catch {
      // Limpa a sessão local mesmo se a API estiver indisponível.
    }
    setAuth(null);
    setStatus("guest");
  }, []);

  const refresh = useCallback(async () => {
    try {
      const result = await api<SupportAuthResponse>("/support/auth/me");
      setAuth(result);
      setStatus("authenticated");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAuth(null);
        setStatus("guest");
      }
    }
  }, []);

  const value = useMemo(
    () => ({ status, auth, login, logout, refresh }),
    [status, auth, login, logout, refresh],
  );
  return <SupportAuthContext.Provider value={value}>{children}</SupportAuthContext.Provider>;
}

export function useSupportAuth(): SupportAuthValue {
  const context = useContext(SupportAuthContext);
  if (!context) throw new Error("useSupportAuth deve ser usado dentro de SupportAuthProvider");
  return context;
}
