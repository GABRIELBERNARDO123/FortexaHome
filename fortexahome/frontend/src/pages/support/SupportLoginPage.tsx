import { ArrowRight, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Brand, Button, Field, Input } from "../../components/ui";
import { useSupportAuth } from "../../context/SupportAuthContext";
import { errorMessage } from "../../lib/api";

export default function SupportLoginPage() {
  const { login } = useSupportAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/backoffice", { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="support-login-page">
      <div className="support-login-card">
        <Brand />
        <div className="support-login-heading">
          <span className="eyebrow">ACESSO RESTRITO</span>
          <h1>Console de suporte</h1>
          <p>Consulta segura de pedidos, licenças e entregas. Ações sensíveis exigem justificativa e ficam auditadas.</p>
        </div>
        <form onSubmit={submit} className="form-stack">
          <Field label="E-mail do operador">
            <div className="input-with-icon">
              <Mail size={16} />
              <Input type="email" required autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>
          </Field>
          <Field label="Senha">
            <div className="input-with-icon">
              <LockKeyhole size={16} />
              <Input type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
            </div>
          </Field>
          {error ? <div className="form-error" role="alert">{error}</div> : null}
          <Button type="submit" variant="primary" loading={loading} className="btn-block">
            Entrar <ArrowRight size={16} />
          </Button>
        </form>
        <div className="support-login-foot">
          <ShieldCheck size={15} /> Sessão separada da conta do cliente. Acesso somente para operadores provisionados no servidor.
        </div>
      </div>
    </div>
  );
}
