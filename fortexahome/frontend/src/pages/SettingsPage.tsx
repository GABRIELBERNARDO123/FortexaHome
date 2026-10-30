import {
  BadgeCheck,
  Download,
  KeyRound,
  Laptop,
  LogOut,
  Monitor,
  Moon,
  Palette,
  ShieldCheck,
  Sun,
  Trash2,
  UserRound,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  ConfirmDialog,
  ErrorState,
  Field,
  IconButton,
  Input,
  PageHeader,
  Panel,
  Select,
  Skeleton,
} from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { api, downloadFile, errorMessage } from "../lib/api";
import { dateLabel } from "../lib/format";
import { useApiData } from "../lib/useApiData";
import type { Account, LicenseStatus, SessionInfo, Theme } from "../types";

const TIMEZONES = [
  "America/Sao_Paulo",
  "America/Manaus",
  "America/Belem",
  "America/Fortaleza",
  "America/Recife",
  "America/Cuiaba",
  "America/Porto_Velho",
  "America/Rio_Branco",
  "America/Noronha",
];

const THEMES: { value: Theme; label: string; description: string; icon: typeof Sun }[] = [
  { value: "minimal", label: "Claro", description: "Minimal, limpo e discreto", icon: Sun },
  { value: "escuro", label: "Escuro", description: "Conforto para a noite", icon: Moon },
];

function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function SettingsPage() {
  const { auth, refresh, logout, updateUserTheme } = useAuth();
  const isOwner = auth?.user.role === "owner";
  const { notify } = useToast();
  const account = useApiData<Account>("/account");
  const license = useApiData<LicenseStatus>("/license");
  const sessions = useApiData<SessionInfo[]>("/auth/sessions");

  const [form, setForm] = useState({
    family_name: "",
    name: "",
    timezone: "America/Sao_Paulo",
    theme: "minimal" as Theme,
  });
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    current_password: "",
    new_password: "",
    confirmation: "",
  });
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<SessionInfo | null>(null);
  const [revokeLoading, setRevokeLoading] = useState(false);

  useEffect(() => {
    if (account.data) {
      setForm({
        family_name: account.data.family_name,
        name: account.data.name,
        timezone: account.data.timezone,
        theme: account.data.theme === "escuro" ? "escuro" : "minimal",
      });
    }
  }, [account.data]);

  const saveAccount = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api("/account", {
        method: "PATCH",
        body: JSON.stringify({
          ...(isOwner
            ? { family_name: form.family_name.trim(), timezone: form.timezone }
            : {}),
          name: form.name.trim(),
          theme: form.theme,
        }),
      });
      await refresh();
      account.reload();
      notify("Preferências salvas.");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setSaving(false);
    }
  };

  const selectTheme = async (theme: Theme) => {
    const previous = form.theme;
    setForm((current) => ({ ...current, theme }));
    updateUserTheme(theme);
    try {
      await api("/account", { method: "PATCH", body: JSON.stringify({ theme }) });
      notify("Tema atualizado.");
    } catch (caught) {
      setForm((current) => ({ ...current, theme: previous }));
      updateUserTheme(previous);
      notify(errorMessage(caught), "error");
    }
  };

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    setPasswordError(null);
    if (passwordForm.new_password !== passwordForm.confirmation) {
      setPasswordError("A confirmação não confere com a nova senha.");
      return;
    }
    setPasswordLoading(true);
    try {
      await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: passwordForm.current_password,
          new_password: passwordForm.new_password,
        }),
      });
      setPasswordForm({ current_password: "", new_password: "", confirmation: "" });
      sessions.reload();
      notify("Senha alterada. Outras sessões foram encerradas.");
    } catch (caught) {
      setPasswordError(errorMessage(caught));
    } finally {
      setPasswordLoading(false);
    }
  };

  const exportBackup = async () => {
    setExporting(true);
    try {
      const data = await api<unknown>("/account/export");
      downloadJson(data, `fortexahome-backup-${new Date().toISOString().slice(0, 10)}.json`);
      notify("Backup JSON exportado.");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setExporting(false);
    }
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      await downloadFile("/reports/transactions.csv", "fortexahome-lancamentos.csv");
      notify("Lançamentos exportados em CSV.");
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setExporting(false);
    }
  };

  const revokeSession = async () => {
    if (!revoking) return;
    setRevokeLoading(true);
    try {
      await api(`/auth/sessions/${revoking.id}`, { method: "DELETE" });
      notify("Sessão encerrada.");
      setRevoking(null);
      sessions.reload();
    } catch (caught) {
      notify(errorMessage(caught), "error");
    } finally {
      setRevokeLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="PERSONALIZAÇÃO"
        title="Configurações"
        description="Personalize sua experiência e cuide dos seus dados."
      />

      {account.loading ? (
        <Skeleton lines={7} />
      ) : account.error || !account.data ? (
        <ErrorState message={account.error || "Conta indisponível."} onRetry={account.reload} />
      ) : (
        <div className="settings-grid">
          <Panel title="Perfil da família" subtitle="Como o FortexaHome chama a sua casa.">
            <form onSubmit={saveAccount} className="form-stack">
              {isOwner ? (
                <Field label="Nome da família ou responsável">
                  <Input
                    required
                    maxLength={120}
                    value={form.family_name}
                    onChange={(event) => setForm({ ...form, family_name: event.target.value })}
                  />
                </Field>
              ) : (
                <p className="setting-note">
                  O nome da família e o fuso horário só podem ser alterados pelo responsável pela conta.
                </p>
              )}
              <Field label="Seu nome">
                <Input
                  required
                  maxLength={120}
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                />
              </Field>
              <Field label="E-mail de acesso" hint="O e-mail não pode ser alterado nesta versão.">
                <Input value={account.data.email} disabled />
              </Field>
              {isOwner ? (
                <Field label="Fuso horário">
                  <Select
                    value={form.timezone}
                    onChange={(event) => setForm({ ...form, timezone: event.target.value })}
                  >
                    {TIMEZONES.map((timezone) => (
                      <option key={timezone} value={timezone}>
                        {timezone.replace("America/", "").replaceAll("_", " ")}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : null}
              <Field label="Moeda" hint="Nesta versão, os valores são sempre em Real brasileiro.">
                <Input value="Real brasileiro (R$)" disabled />
              </Field>
              <Button type="submit" variant="primary" loading={saving} icon={UserRound}>
                Salvar preferências
              </Button>
            </form>
          </Panel>

          <Panel title="Aparência" subtitle="Escolha o clima visual da sua casa.">
            <div className="theme-grid">
              {THEMES.map((theme) => (
                <button
                  type="button"
                  key={theme.value}
                  className={`theme-option ${form.theme === theme.value ? "active" : ""}`}
                  onClick={() => void selectTheme(theme.value)}
                >
                  <span className={`theme-preview theme-${theme.value}`}>
                    <i />
                    <i />
                    <i />
                  </span>
                  <span>
                    <strong>
                      <theme.icon size={15} /> {theme.label}
                    </strong>
                    <small>{theme.description}</small>
                  </span>
                </button>
              ))}
            </div>
            <div className="setting-note">
              <Palette size={16} />
              O tema escolhido vale para todos os dispositivos em que você entrar com esta conta.
            </div>
          </Panel>

          <Panel title="Licença FortexaHome" subtitle="Seu vínculo de acesso ao produto.">
            {license.loading ? (
              <Skeleton lines={3} />
            ) : license.data ? (
              <div className="license-card">
                <div className="license-top">
                  <BadgeCheck size={24} />
                  <div>
                    <strong>{license.data.product_name}</strong>
                    <span>{license.data.license_kind === "lifetime" ? "Licença vitalícia" : "Assinatura"}</span>
                  </div>
                  <Badge tone={license.data.status === "active" ? "good" : "bad"}>
                    {license.data.status === "active" ? "Ativa" : "Inativa"}
                  </Badge>
                </div>
                <div className="license-details">
                  <div>
                    <small>Final do código</small>
                    <strong>•••• {license.data.code_last4}</strong>
                  </div>
                  <div>
                    <small>Ativada em</small>
                    <strong>{dateLabel(license.data.activated_at)}</strong>
                  </div>
                  <div>
                    <small>Validade</small>
                    <strong>{license.data.expires_at ? dateLabel(license.data.expires_at) : "Sem expiração"}</strong>
                  </div>
                </div>
                <p className="muted">
                  Esta licença está vinculada ao e-mail {account.data.email}. Cada licença permite uma única conta.
                </p>
              </div>
            ) : (
              <ErrorState message={license.error || "Licença indisponível."} onRetry={license.reload} />
            )}
          </Panel>

          <Panel title="Segurança" subtitle="Senha e dispositivos com sessão ativa.">
            <form onSubmit={changePassword} className="form-stack">
              <Field label="Senha atual">
                <Input
                  type="password"
                  required
                  autoComplete="current-password"
                  value={passwordForm.current_password}
                  onChange={(event) =>
                    setPasswordForm({ ...passwordForm, current_password: event.target.value })
                  }
                />
              </Field>
              <div className="form-grid">
                <Field label="Nova senha" hint="Mínimo de 8 caracteres.">
                  <Input
                    type="password"
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={passwordForm.new_password}
                    onChange={(event) =>
                      setPasswordForm({ ...passwordForm, new_password: event.target.value })
                    }
                  />
                </Field>
                <Field label="Confirme a nova senha">
                  <Input
                    type="password"
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={passwordForm.confirmation}
                    onChange={(event) =>
                      setPasswordForm({ ...passwordForm, confirmation: event.target.value })
                    }
                  />
                </Field>
              </div>
              {passwordError ? <div className="form-error">{passwordError}</div> : null}
              <Button type="submit" variant="secondary" icon={KeyRound} loading={passwordLoading}>
                Alterar senha
              </Button>
            </form>

            <div className="divider" />
            <div className="sessions-head">
              <div>
                <h4>Sessões ativas</h4>
                <p className="muted">Encerre acessos que você não reconhece.</p>
              </div>
              <Laptop size={19} />
            </div>
            {sessions.loading ? (
              <Skeleton lines={3} />
            ) : (
              <div className="session-list">
                {(sessions.data || []).map((session) => (
                  <div className="session-row" key={session.id}>
                    <div>
                      <strong>
                        {session.current ? "Este dispositivo" : "Outro dispositivo"}
                        {session.current ? <Badge tone="good">Atual</Badge> : null}
                      </strong>
                      <small>
                        Iniciada em {formatDateTime(session.created_at)} · expira em{" "}
                        {formatDateTime(session.expires_at)}
                      </small>
                    </div>
                    {!session.current ? (
                      <IconButton
                        label="Encerrar sessão"
                        icon={Trash2}
                        className="danger-icon"
                        onClick={() => setRevoking(session)}
                      />
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="Seus dados" subtitle="Leve sua história com você quando quiser.">
            <div className="setting-action">
              <div>
                <strong>
                  <Download size={16} /> Exportar backup JSON
                </strong>
                <p>Uma cópia completa de lançamentos, contas, cartões, orçamentos e metas.</p>
              </div>
              <Button variant="secondary" loading={exporting} onClick={() => void exportBackup()}>
                Exportar
              </Button>
            </div>
            <div className="setting-action">
              <div>
                <strong>
                  <Download size={16} /> Baixar lançamentos em CSV
                </strong>
                <p>Ideal para abrir no Excel ou compartilhar com a família.</p>
              </div>
              <Button variant="secondary" loading={exporting} onClick={() => void exportCsv()}>
                Baixar CSV
              </Button>
            </div>
            <div className="setting-note">
              <ShieldCheck size={16} />
              Seus dados são criptografados no servidor. Você pode solicitar a exclusão da conta pelo suporte
              FortexaHome.
            </div>
          </Panel>

          <Panel title="Sessão" subtitle="Tudo pronto por aqui?">
            <div className="setting-action">
              <div>
                <strong>
                  <LogOut size={16} /> Sair da conta
                </strong>
                <p>Encerra a sessão deste dispositivo com segurança.</p>
              </div>
              <Button variant="secondary" icon={LogOut} onClick={() => void logout()}>
                Sair
              </Button>
            </div>
            <div className="setting-note">
              <Monitor size={16} />
              Conta criada em {auth ? dateLabel(auth.user.created_at) : "—"} · Plano{" "}
              {license.data?.license_kind === "lifetime" ? "vitalício" : "ativo"}
            </div>
          </Panel>
        </div>
      )}

      <ConfirmDialog
        open={Boolean(revoking)}
        title="Encerrar esta sessão?"
        description="O dispositivo precisará entrar novamente com e-mail e senha."
        confirmLabel="Encerrar sessão"
        danger
        loading={revokeLoading}
        onConfirm={() => void revokeSession()}
        onClose={() => setRevoking(null)}
      />
    </>
  );
}
