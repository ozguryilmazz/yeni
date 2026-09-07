import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/");
    } catch {
      setError("E-posta veya şifre hatalı");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <h1>Giriş Yap</h1>
      <form onSubmit={handleSubmit}>
        <label>
          E-posta
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Şifre
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Giriş yapılıyor..." : "Giriş Yap"}
        </button>
      </form>
      <p>
        Hesabın yok mu? <Link to="/register">Kayıt ol</Link>
      </p>
    </div>
  );
}
