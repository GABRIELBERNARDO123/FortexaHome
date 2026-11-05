import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, api } from "../lib/api";
import { setDefaultTimeZone } from "../lib/format";
import type { ActivationChallenge, AuthResponse, Theme } from "../types";

type AuthStatus = "loading" | "guest" | "authenticated" | "blocked";

interface AuthContextValue {
  status: AuthStatus;
  auth: AuthResponse | null;
  blockedMessage: string | null;
  login: (email: string, password: string) => Promise<void>;
  activate: (input: { name: string; email: string; password: string; license_code: string }) => Promise<ActivationChallenge>;
  confirmActivation: (activationId: string, code: string) => Promise<void>;
  resendActivation: (activationId: string) => Promise<ActivationChallenge>;
  recoverLicense: (input: { name: string; email: string; password: string }) => Promise<{ message: string }>;
  confirmLicenseRecovery: (email: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<AuthResponse | null>;
  updateUserTheme: (theme: Theme) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const THEME_KEY = "fortexahome-theme";

export function resolveTheme(theme: Theme): "minimal" | "escuro" {
  return theme === "escuro" ? "escuro" : "minimal";
}

export function applyTheme(theme: Theme) {
  const resolved = resolveTheme(theme);
  document.documentElement.dataset.theme = resolved;
  try {
    localStorage.setItem(THEME_KEY, resolved);
  } catch {
    // Armazenamento indisponível: o tema ainda vale para a sessão atual.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [auth, setAuth] = useState<AuthResponse | null>(null);
  const [blockedMessage, setBlockedMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api<AuthResponse>("/auth/me")
      .then((result) => {
        if (!active) return;
        setAuth(result);
        setDefaultTimeZone(result.tenant.timezone);
        applyTheme(result.user.theme);
        setStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 403) {
          setBlockedMessage(error.message);
          setStatus("blocked");
          return;
        }
        setStatus("guest");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const handler = () => {
      setAuth(null);
      setDefaultTimeZone(undefined);
      setStatus("guest");
    };
    window.addEventListener("fh:unauthorized", handler);
    return () => window.removeEventListener("fh:unauthorized", handler);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api<AuthResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setAuth(result);
    setDefaultTimeZone(result.tenant.timezone);
    applyTheme(result.user.theme);
    setBlockedMessage(null);
    setStatus("authenticated");
  }, []);

  const activate = useCallback(
    async (input: { name: string; email: string; password: string; license_code: string }) => {
      return api<ActivationChallenge>("/auth/activate", {
        method: "POST",
        body: JSON.stringify(input),
      });
    },
    [],
  );

  const confirmActivation = useCallback(async (activationId: string, code: string) => {
    const result = await api<AuthResponse>("/auth/activate/confirm", {
      method: "POST",
      body: JSON.stringify({ activation_id: activationId, code }),
    });
    setAuth(result);
    setDefaultTimeZone(result.tenant.timezone);
    applyTheme(result.user.theme);
    setBlockedMessage(null);
    setStatus("authenticated");
  }, []);

  const resendActivation = useCallback((activationId: string) =>
    api<ActivationChallenge>("/auth/activate/resend", {
      method: "POST",
      body: JSON.stringify({ activation_id: activationId }),
    }), []);

  const recoverLicense = useCallback(
    async (input: { name: string; email: string; password: string }) => {
      return api<{ message: string }>("/auth/recover-license", {
        method: "POST",
        body: JSON.stringify(input),
      });
    },
    [],
  );

  const confirmLicenseRecovery = useCallback(async (email: string, code: string) => {
    const result = await api<AuthResponse>("/auth/recover-license/confirm", {
      method: "POST",
      body: JSON.stringify({ email, code }),
    });
    setAuth(result);
    setDefaultTimeZone(result.tenant.timezone);
    applyTheme(result.user.theme);
    setBlockedMessage(null);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      // Encerra a sessão local mesmo se o servidor não responder.
    }
    setAuth(null);
    setBlockedMessage(null);
    setDefaultTimeZone(undefined);
    setStatus("guest");
  }, []);

  const refresh = useCallback(async () => {
    try {
      const result = await api<AuthResponse>("/auth/me");
      setAuth(result);
      setDefaultTimeZone(result.tenant.timezone);
      applyTheme(result.user.theme);
      setStatus("authenticated");
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setBlockedMessage(error.message);
        setStatus("blocked");
      } else if (error instanceof ApiError && error.status === 401) {
        setAuth(null);
        setDefaultTimeZone(undefined);
        setStatus("guest");
      }
      return null;
    }
  }, []);

  const updateUserTheme = useCallback((theme: Theme) => {
    applyTheme(theme);
    setAuth((current) =>
      current ? { ...current, user: { ...current.user, theme } } : current,
    );
  }, []);

  const value = useMemo(
    () => ({
      status,
      auth,
      blockedMessage,
      login,
      activate,
      confirmActivation,
      resendActivation,
      recoverLicense,
      confirmLicenseRecovery,
      logout,
      refresh,
      updateUserTheme,
    }),
    [
      status,
      auth,
      blockedMessage,
      login,
      activate,
      confirmActivation,
      resendActivation,
      recoverLicense,
      confirmLicenseRecovery,
      logout,
      refresh,
      updateUserTheme,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth deve ser usado dentro de AuthProvider");
  return context;
}
