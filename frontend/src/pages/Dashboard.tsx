import { FormEvent, useEffect, useState } from "react";

import {
  Credential,
  connectCredential,
  deleteCredential,
  listCredentials,
} from "../api/credentials";
import { useAuth } from "../context/AuthContext";

function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail ?? fallback;
}

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [label, setLabel] = useState("default");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingList, setLoadingList] = useState(true);

  const refreshCredentials = async () => {
    setLoadingList(true);
    try {
      setCredentials(await listCredentials());
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => {
    refreshCredentials();
  }, []);

  const handleConnect = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await connectCredential({ label, api_key: apiKey, api_secret: apiSecret });
      setApiKey("");
      setApiSecret("");
      await refreshCredentials();
    } catch (err) {
      setError(extractErrorMessage(err, "Bağlantı başarısız oldu"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    await deleteCredential(id);
    await refreshCredentials();
  };

  return (
    <div className="dashboard">
      <header>
        <h1>Cüzdan Özeti</h1>
        <div>
          <span>{user?.email}</span>
          <button onClick={logout}>Çıkış Yap</button>
        </div>
      </header>

      <section>
        <h2>Bağlı Binance Hesapları</h2>
        {loadingList ? (
          <p>Yükleniyor...</p>
        ) : credentials.length === 0 ? (
          <p>Henüz bağlı bir Binance hesabı yok.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Etiket</th>
                <th>Withdrawal İzni</th>
                <th>Bağlanma Tarihi</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {credentials.map((c) => (
                <tr key={c.id}>
                  <td>{c.label}</td>
                  <td>{c.can_withdraw ? "Açık ⚠️" : "Kapalı"}</td>
                  <td>{new Date(c.created_at).toLocaleString("tr-TR")}</td>
                  <td>
                    <button onClick={() => handleDelete(c.id)}>Kaldır</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Binance Hesabı Bağla</h2>
        <p className="hint">
          Sadece <strong>Enable Reading</strong> (ve gerekirse Spot/Futures trading) izni açık bir API
          key kullanın. Withdrawal (para çekme) izni açık key'ler güvenlik nedeniyle reddedilir.
        </p>
        <form onSubmit={handleConnect}>
          <label>
            Etiket
            <input value={label} onChange={(e) => setLabel(e.target.value)} required />
          </label>
          <label>
            API Key
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} required minLength={10} />
          </label>
          <label>
            API Secret
            <input
              type="password"
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              required
              minLength={10}
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Bağlanıyor..." : "Bağla"}
          </button>
        </form>
      </section>

      <p className="hint">
        Spot / Futures / Funding bakiyeleri ve transfer ekranı bir sonraki fazda burada görünecek.
      </p>
    </div>
  );
}
