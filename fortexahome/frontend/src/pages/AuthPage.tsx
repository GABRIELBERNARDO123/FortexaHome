import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { Brand, Button, Field, Input } from "../components/ui";
import { api, errorMessage } from "../lib/api";
import type { ActivationChallenge } from "../types";

type Mode = "login" | "activate" | "forgot" | "recover";

function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

export default function AuthPage() {
  const { login, activate, confirmActivation, resendActivation, recoverLicense, confirmLicenseRecovery } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;
  const destination = from && from !== "/entrar" ? from : "/";
  const [mode, setMode] = useState<Mode>("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [resetToken, setResetToken] = useState<string | null>(null);
  const [forgotEmail, setForgotEmail] = useState("");
  const [forgotSent, setForgotSent] = useState(false);
  const [recoverySent, setRecoverySent] = useState(false);
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [activationChallenge, setActivationChallenge] = useState<ActivationChallenge | null>(null);
  const [activationCode, setActivationCode] = useState("");
  const [clock, setClock] = useState(Date.now());

  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [activateForm, setActivateForm] = useState({
    name: "",
    email: "",
    password: "",
    license_code: "",
  });
  const [recoveryForm, setRecoveryForm] = useState({
    name: "",
    email: "",
    password: "",
  });

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const secondsUntilResend = activationChallenge
    ? Math.max(0, Math.ceil((Date.parse(activationChallenge.resend_at) - clock) / 1000))
    : 0;
  const secondsUntilExpiry = activationChallenge?.expires_at
    ? Math.max(0, Math.ceil((Date.parse(activationChallenge.expires_at) - clock) / 1000))
    : null;

  const changeMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setResetToken(null);
    setForgotSent(false);
    setRecoverySent(false);
    setRecoveryCode("");
    if (next !== "activate") {
      setActivationChallenge(null);
      setActivationCode("");
    }
  };

  const submitLogin = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(loginForm.email, loginForm.password);
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  const submitActivate = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const challenge = await activate(activateForm);
      setActivationChallenge(challenge);
      setActivationCode("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  const submitActivationCode = async (event: FormEvent) => {
    event.preventDefault();
    if (!activationChallenge) return;
    setLoading(true);
    setError(null);
    try {
      await confirmActivation(activationChallenge.activation_id, activationCode);
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  const submitResend = async () => {
    if (!activationChallenge || secondsUntilResend > 0) return;
    setLoading(true);
    setError(null);
    try {
      const challenge = await resendActivation(activationChallenge.activation_id);
      setActivationChallenge(challenge);
      setActivationCode("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  const submitForgot = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await api<{ message: string; reset_token: string | null }>("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email: forgotEmail }),
      });
      setForgotSent(true);
      setResetToken(result.reset_token);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  const submitRecovery = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await recoverLicense(recoveryForm);
      setRecoveryEmail(recoveryForm.email);
      setRecoverySent(true);
      setRecoveryCode("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  const submitRecoveryCode = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await confirmLicenseRecovery(recoveryEmail, recoveryCode);
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <section className="auth-art">
        <div className="auth-art-inner">
          <Brand />
          <div className="auth-copy">
            <div className="eyebrow light">FORTEXAHOME</div>
            <h1>O futuro da sua família começa com clareza hoje.</h1>
            <p>
              Receitas, contas, cartões, orçamento e sonhos em um só lugar. Uma visão simples e acolhedora da
              vida financeira da sua casa.
            </p>
          </div>
          <div className="auth-preview" aria-hidden="true">
            <div className="preview-top">
              <span>Saldo da família</span>
              <span className="preview-pill">Outubro</span>
            </div>
            <strong>R$ 8.420,00</strong>
            <div className="preview-bars">
              {[46, 63, 52, 78, 70, 88].map((height, index) => (
                <div key={index} className="preview-bar">
                  <i style={{ height: `${height}%` }} />
                  <b style={{ height: `${Math.max(26, height - 24)}%` }} />
                </div>
              ))}
            </div>
            <div className="preview-legend">
              <span>
                <i className="dot brand" /> Receitas
              </span>
              <span>
                <i className="dot muted" /> Despesas
              </span>
            </div>
          </div>
          <div className="auth-bullets">
            <span>
              <ShieldCheck size={17} /> Dados protegidos
            </span>
            <span>
              <Sparkles size={17} /> Feito para famílias
            </span>
            <span>
              <CheckCircle2 size={17} /> Acesso por licença
            </span>
          </div>
        </div>
        <div className="auth-art-orbit auth-orbit-one" />
        <div className="auth-art-orbit auth-orbit-two" />
      </section>

      <section className="auth-form-side">
        <div className="auth-form-wrap">
          <div className="mobile-brand">
            <Brand />
          </div>
          <div className="auth-tabs" role="tablist" aria-label="Acesso à conta">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              className={mode === "login" ? "active" : undefined}
              onClick={() => changeMode("login")}
            >
              Entrar
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "activate"}
              className={mode === "activate" ? "active" : undefined}
              onClick={() => changeMode("activate")}
            >
              Ativar licença
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "recover"}
              className={mode === "recover" ? "active" : undefined}
              onClick={() => changeMode("recover")}
            >
              Recuperar acesso
            </button>
          </div>

          {mode === "login" ? (
            <div className="auth-form-block">
              <div className="auth-heading">
                <h2>Que bom ter você de volta.</h2>
                <p>Entre para acompanhar a saúde financeira da sua família.</p>
              </div>
              <form onSubmit={submitLogin} className="form-stack">
                <Field label="E-mail">
                  <div className="input-with-icon">
                    <Mail size={16} />
                    <Input
                      type="email"
                      autoComplete="email"
                      required
                      value={loginForm.email}
                      onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
                      placeholder="voce@familia.com"
                    />
                  </div>
                </Field>
                <Field label="Senha">
                  <div className="input-with-icon">
                    <LockKeyhole size={16} />
                    <Input
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      required
                      value={loginForm.password}
                      onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
                      placeholder="Sua senha"
                    />
                    <button
                      type="button"
                      className="input-action"
                      onClick={() => setShowPassword((value) => !value)}
                      aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </Field>
                {error ? <div className="form-error" role="alert">{error}</div> : null}
                <Button type="submit" variant="primary" loading={loading} className="btn-block">
                  Entrar na minha conta <ArrowRight size={16} />
                </Button>
                <button type="button" className="link-button centered" onClick={() => changeMode("forgot")}>
                  Esqueci minha senha
                </button>
              </form>
            </div>
          ) : null}

          {mode === "activate" && !activationChallenge ? (
            <div className="auth-form-block">
              <div className="auth-heading">
                <h2>Ative seu acesso FortexaHome.</h2>
                <p>Cada licença cria uma única conta, vinculada ao seu e-mail.</p>
              </div>
              <form onSubmit={submitActivate} className="form-stack">
                <Field label="Seu nome">
                  <div className="input-with-icon">
                    <UserRound size={16} />
                    <Input
                      required
                      minLength={2}
                      autoComplete="name"
                      value={activateForm.name}
                      onChange={(event) => setActivateForm({ ...activateForm, name: event.target.value })}
                      placeholder="Como quer ser chamado(a)?"
                    />
                  </div>
                </Field>
                <Field label="E-mail">
                  <div className="input-with-icon">
                    <Mail size={16} />
                    <Input
                      type="email"
                      required
                      autoComplete="email"
                      value={activateForm.email}
                      onChange={(event) => setActivateForm({ ...activateForm, email: event.target.value })}
                      placeholder="voce@familia.com"
                    />
                  </div>
                </Field>
                <Field label="Senha" hint="Use pelo menos 8 caracteres.">
                  <div className="input-with-icon">
                    <LockKeyhole size={16} />
                    <Input
                      type={showPassword ? "text" : "password"}
                      required
                      minLength={8}
                      autoComplete="new-password"
                      value={activateForm.password}
                      onChange={(event) => setActivateForm({ ...activateForm, password: event.target.value })}
                      placeholder="Crie uma senha segura"
                    />
                    <button
                      type="button"
                      className="input-action"
                      onClick={() => setShowPassword((value) => !value)}
                      aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </Field>
                <Field label="Código da licença">
                  <div className="input-with-icon">
                    <KeyRound size={16} />
                    <Input
                      required
                      autoComplete="one-time-code"
                      value={activateForm.license_code}
                      onChange={(event) => setActivateForm({ ...activateForm, license_code: event.target.value })}
                      placeholder="FH-XXXX-XXXX-XXXX"
                      className="mono-input"
                    />
                  </div>
                </Field>
                {error ? <div className="form-error" role="alert">{error}</div> : null}
                <Button type="submit" variant="primary" loading={loading} className="btn-block">
                  Criar minha conta <ArrowRight size={16} />
                </Button>
                <p className="auth-fineprint">
                  O código é enviado por e-mail após a compra. Já possui conta?{" "}
                  <button type="button" className="link-button" onClick={() => changeMode("login")}>
                    Entrar
                  </button>
                </p>
              </form>
            </div>
          ) : null}

          {mode === "activate" && activationChallenge ? (
            <div className="auth-form-block">
              <div className="auth-heading">
                <h2>Confirme seu e-mail.</h2>
                <p>Registramos o pedido de envio de um código para <strong>{activationChallenge.email_masked}</strong>. O worker está processando o envio.</p>
              </div>
              {activationChallenge.expires_at && secondsUntilExpiry !== null && secondsUntilExpiry > 0 ? (
                <form onSubmit={submitActivationCode} className="form-stack">
                  <Field label="Código de verificação" hint="O código tem seis dígitos e só pode ser usado uma vez.">
                    <div className="input-with-icon">
                      <KeyRound size={16} />
                      <Input
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        pattern="[0-9]{6}"
                        maxLength={6}
                        required
                        value={activationCode}
                        onChange={(event) => setActivationCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                        placeholder="000000"
                        className="mono-input"
                        aria-label="Código de verificação"
                      />
                    </div>
                  </Field>
                  <p className="auth-fineprint">Este código expira em {formatCountdown(secondsUntilExpiry)}.</p>
                  {error ? <div className="form-error" role="alert">{error}</div> : null}
                  <Button type="submit" variant="primary" loading={loading} disabled={activationCode.length !== 6} className="btn-block">
                    Confirmar e entrar <ArrowRight size={16} />
                  </Button>
                </form>
              ) : (
                <div className="forgot-success">
                  <p>
                    {activationChallenge.expires_at
                      ? "Este código expirou. Solicite um novo código para continuar."
                      : "Seus dados foram atualizados. Solicite o código quando o intervalo de reenvio terminar."}
                  </p>
                </div>
              )}
              {error ? <div className="form-error" role="alert">{error}</div> : null}
              <div className="form-stack">
                <Button
                  variant="secondary"
                  onClick={submitResend}
                  loading={loading}
                  disabled={secondsUntilResend > 0}
                  className="btn-block"
                >
                  {secondsUntilResend > 0
                    ? `Reenviar código em ${formatCountdown(secondsUntilResend)}`
                    : "Enviar novo código"}
                </Button>
                <button
                  type="button"
                  className="link-button centered"
                  onClick={() => {
                    setActivationChallenge(null);
                    setActivationCode("");
                    setError(null);
                  }}
                >
                  <ArrowLeft size={14} /> Corrigir dados
                </button>
              </div>
            </div>
          ) : null}

          {mode === "recover" ? (
            <div className="auth-form-block">
              <div className="auth-heading">
                <h2>Recupere seu acesso.</h2>
                <p>
                  Informe o e-mail usado na compra. Se houver uma licença aguardando
                  ativação, enviaremos um código. Se a conta já existe, enviaremos
                  instruções de senha.
                </p>
              </div>
              {recoverySent ? (
                <div className="form-stack">
                  <div className="forgot-success">
                    <CheckCircle2 size={28} />
                    <h3>Confira seu e-mail</h3>
                    <p>
                      Se houver um acesso pendente para <strong>{recoveryEmail}</strong>,
                      enviaremos as instruções. Se a conta já existe, use o link de
                      redefinição de senha recebido.
                    </p>
                  </div>
                  <form onSubmit={submitRecoveryCode} className="form-stack">
                    <Field label="Código de ativação recebido" hint="Seis dígitos, quando aplicável.">
                      <div className="input-with-icon">
                        <KeyRound size={16} />
                        <Input
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          pattern="[0-9]{6}"
                          maxLength={6}
                          value={recoveryCode}
                          onChange={(event) =>
                            setRecoveryCode(event.target.value.replace(/\D/g, "").slice(0, 6))
                          }
                          placeholder="000000"
                          className="mono-input"
                          aria-label="Código de recuperação"
                        />
                      </div>
                    </Field>
                    {error ? <div className="form-error" role="alert">{error}</div> : null}
                    <Button
                      type="submit"
                      variant="primary"
                      loading={loading}
                      disabled={recoveryCode.length !== 6}
                      className="btn-block"
                    >
                      Confirmar e entrar <ArrowRight size={16} />
                    </Button>
                  </form>
                  <button
                    type="button"
                    className="link-button centered"
                    onClick={() => {
                      setRecoverySent(false);
                      setRecoveryCode("");
                      setError(null);
                    }}
                  >
                    <ArrowLeft size={14} /> Usar outro e-mail
                  </button>
                  <p className="auth-fineprint">
                    Já tem conta?{" "}
                    <button type="button" className="link-button" onClick={() => changeMode("login")}>
                      Entrar
                    </button>
                  </p>
                </div>
              ) : (
                <form onSubmit={submitRecovery} className="form-stack">
                  <Field label="Seu nome">
                    <div className="input-with-icon">
                      <UserRound size={16} />
                      <Input
                        required
                        minLength={2}
                        autoComplete="name"
                        value={recoveryForm.name}
                        onChange={(event) => setRecoveryForm({ ...recoveryForm, name: event.target.value })}
                        placeholder="Como quer ser chamado(a)?"
                      />
                    </div>
                  </Field>
                  <Field label="E-mail da compra">
                    <div className="input-with-icon">
                      <Mail size={16} />
                      <Input
                        type="email"
                        required
                        autoComplete="email"
                        value={recoveryForm.email}
                        onChange={(event) => setRecoveryForm({ ...recoveryForm, email: event.target.value })}
                        placeholder="voce@familia.com"
                      />
                    </div>
                  </Field>
                  <Field label="Senha" hint="Mínimo de 8 caracteres. Usada apenas se a licença ainda não foi ativada.">
                    <div className="input-with-icon">
                      <LockKeyhole size={16} />
                      <Input
                        type={showPassword ? "text" : "password"}
                        required
                        minLength={8}
                        autoComplete="new-password"
                        value={recoveryForm.password}
                        onChange={(event) => setRecoveryForm({ ...recoveryForm, password: event.target.value })}
                        placeholder="Crie uma senha segura"
                      />
                    </div>
                  </Field>
                  {error ? <div className="form-error" role="alert">{error}</div> : null}
                  <Button type="submit" variant="primary" loading={loading} className="btn-block">
                    Enviar instruções <ArrowRight size={16} />
                  </Button>
                  <p className="auth-fineprint">
                    Já tem conta ou quer usar a licença?{" "}
                    <button type="button" className="link-button" onClick={() => changeMode("login")}>
                      Entrar
                    </button>
                  </p>
                </form>
              )}
            </div>
          ) : null}

          {mode === "forgot" ? (
            <div className="auth-form-block">
              <div className="auth-heading">
                <h2>Recuperar acesso.</h2>
                <p>Informe seu e-mail e enviaremos instruções para criar uma nova senha.</p>
              </div>
              {forgotSent ? (
                <div className="forgot-success">
                  <CheckCircle2 size={30} />
                  <h3>Confira seu e-mail</h3>
                  <p>Se o endereço estiver cadastrado, as instruções chegarão em instantes.</p>
                  {resetToken ? (
                    <Button
                      variant="primary"
                      onClick={() => navigate(`/redefinir-senha?token=${encodeURIComponent(resetToken)}`)}
                    >
                      Abrir redefinição (ambiente local)
                    </Button>
                  ) : null}
                  <Button variant="ghost" icon={ArrowLeft} onClick={() => changeMode("login")}>
                    Voltar para o login
                  </Button>
                </div>
              ) : (
                <form onSubmit={submitForgot} className="form-stack">
                  <Field label="E-mail cadastrado">
                    <div className="input-with-icon">
                      <Mail size={16} />
                      <Input
                        type="email"
                        required
                        value={forgotEmail}
                        onChange={(event) => setForgotEmail(event.target.value)}
                        placeholder="voce@familia.com"
                      />
                    </div>
                  </Field>
                  {error ? <div className="form-error" role="alert">{error}</div> : null}
                  <Button type="submit" variant="primary" loading={loading} className="btn-block">
                    Enviar instruções
                  </Button>
                  <button type="button" className="link-button centered" onClick={() => changeMode("login")}>
                    <ArrowLeft size={14} /> Voltar para o login
                  </button>
                </form>
              )}
            </div>
          ) : null}

          <footer className="auth-footer">
            <span>Acesso exclusivo para licenças FortexaHome.</span>
            <Link to="/entrar">Precisa de ajuda?</Link>
          </footer>
        </div>
      </section>
    </div>
  );
}
