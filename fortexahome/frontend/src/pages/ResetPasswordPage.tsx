import { ArrowLeft, CheckCircle2, Eye, EyeOff, LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Brand, Button, Field, Input } from "../components/ui";
import { api, errorMessage } from "../lib/api";

export default function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password !== confirmation) {
      setError("As senhas não conferem.");
      return;
    }
    setLoading(true);
    try {
      await api("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password }),
      });
      setSuccess(true);
      window.setTimeout(() => navigate("/entrar", { replace: true }), 2200);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="simple-auth">
      <div className="simple-auth-card">
        <Brand />
        {!token ? (
          <>
            <h1>Link inválido</h1>
            <p>Este link de redefinição está incompleto ou expirou. Solicite um novo e-mail de recuperação.</p>
            <Link to="/entrar" className="btn btn-primary">
              <ArrowLeft size={16} /> Voltar para o acesso
            </Link>
          </>
        ) : success ? (
          <>
            <div className="success-icon">
              <CheckCircle2 size={32} />
            </div>
            <h1>Senha atualizada</h1>
            <p>Pronto! Você será direcionado para o login em instantes.</p>
          </>
        ) : (
          <>
            <h1>Crie uma nova senha</h1>
            <p>Escolha uma senha forte, com pelo menos 8 caracteres, que você ainda não use em outros lugares.</p>
            <form onSubmit={submit} className="form-stack">
              <Field label="Nova senha">
                <div className="input-with-icon">
                  <LockKeyhole size={16} />
                  <Input
                    type={showPassword ? "text" : "password"}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
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
              <Field label="Confirme a nova senha">
                <div className="input-with-icon">
                  <LockKeyhole size={16} />
                  <Input
                    type={showPassword ? "text" : "password"}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    value={confirmation}
                    onChange={(event) => setConfirmation(event.target.value)}
                  />
                </div>
              </Field>
              {error ? <div className="form-error">{error}</div> : null}
              <Button type="submit" variant="primary" loading={loading} className="btn-block">
                Salvar nova senha
              </Button>
              <Link to="/entrar" className="link-button centered">
                <ArrowLeft size={14} /> Voltar para o login
              </Link>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
