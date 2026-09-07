import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";

export default function Register() {
  const { register } = useAuth();
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
      await register(email, password);
      navigate("/");
    } catch {
      setError("Kayıt başarısız oldu. E-posta zaten kullanımda olabilir.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <h1>Kayıt Ol</h1>
      <form onSubmit={handleSubmit}>
        <label>
          E-posta
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Şifre (en az 8 karakter)
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Kaydediliyor..." : "Kayıt Ol"}
        </button>
      </form>
      <p>
        Zaten hesabın var mı? <Link to="/login">Giriş yap</Link>
      </p>
    </div>
  );
}
