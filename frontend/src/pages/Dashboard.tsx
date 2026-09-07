import { FormEvent, ReactNode, useEffect, useState } from "react";

import {
  Credential,
  connectCredential,
  deleteCredential,
  listCredentials,
} from "../api/credentials";
import { fetchBalances, WalletSummary } from "../api/wallet";
import { useAuth } from "../context/AuthContext";

function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail ?? fallback;
}

function formatAmount(value: number): string {
  return value.toLocaleString("tr-TR", { maximumFractionDigits: 8 });
}

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [selectedCredentialId, setSelectedCredentialId] = useState<string>("");
  const [wallet, setWallet] = useState<WalletSummary | null>(null);
  const [walletError, setWalletError] = useState<string | null>(null);
  const [walletLoading, setWalletLoading] = useState(false);

  const [label, setLabel] = useState("default");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [connectError, setConnectError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingList, setLoadingList] = useState(true);

  const refreshCredentials = async () => {
    setLoadingList(true);
    try {
      const list = await listCredentials();
      setCredentials(list);
      if (list.length > 0 && !list.some((c) => c.id === selectedCredentialId)) {
        setSelectedCredentialId(list[0].id);
      }
      if (list.length === 0) {
        setSelectedCredentialId("");
        setWallet(null);
      }
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => {
    refreshCredentials();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadBalances = async () => {
    if (!selectedCredentialId) return;
    setWalletLoading(true);
    setWalletError(null);
    try {
      setWallet(await fetchBalances(selectedCredentialId));
    } catch (err) {
      setWalletError(extractErrorMessage(err, "Bakiyeler alınamadı"));
    } finally {
      setWalletLoading(false);
    }
  };

  useEffect(() => {
    if (selectedCredentialId) {
      loadBalances();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCredentialId]);

  const handleConnect = async (event: FormEvent) => {
    event.preventDefault();
    setConnectError(null);
    setSubmitting(true);
    try {
      await connectCredential({ label, api_key: apiKey, api_secret: apiSecret });
      setApiKey("");
      setApiSecret("");
      await refreshCredentials();
    } catch (err) {
      setConnectError(extractErrorMessage(err, "Bağlantı başarısız oldu"));
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
        <div className="section-header">
          <h2>Bakiyeler</h2>
          {credentials.length > 1 && (
            <select value={selectedCredentialId} onChange={(e) => setSelectedCredentialId(e.target.value)}>
              {credentials.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          )}
          <button onClick={loadBalances} disabled={!selectedCredentialId || walletLoading}>
            {walletLoading ? "Yenileniyor..." : "Yenile"}
          </button>
        </div>

        {credentials.length === 0 && !loadingList && (
          <p>Bakiyeleri görmek için önce aşağıdan bir Binance hesabı bağlayın.</p>
        )}
        {walletError && <p className="error">{walletError}</p>}

        {wallet && (
          <div className="wallet-grid">
            <WalletCard title="Spot">
              {wallet.spot.length === 0 ? (
                <p className="hint">Bakiye yok</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Coin</th>
                      <th>Serbest</th>
                      <th>Kilitli</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wallet.spot.map((b) => (
                      <tr key={b.asset}>
                        <td>{b.asset}</td>
                        <td>{formatAmount(b.free)}</td>
                        <td>{formatAmount(b.locked)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </WalletCard>

            <WalletCard title="Futures (USDⓈ-M)">
              {wallet.futures.length === 0 ? (
                <p className="hint">Bakiye yok</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Coin</th>
                      <th>Cüzdan</th>
                      <th>Kullanılabilir</th>
                      <th>PNL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wallet.futures.map((b) => (
                      <tr key={b.asset}>
                        <td>{b.asset}</td>
                        <td>{formatAmount(b.wallet_balance)}</td>
                        <td>{formatAmount(b.available_balance)}</td>
                        <td>{formatAmount(b.unrealized_profit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </WalletCard>

            <WalletCard title="Funding">
              {wallet.funding.length === 0 ? (
                <p className="hint">Bakiye yok</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Coin</th>
                      <th>Serbest</th>
                      <th>Kilitli</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wallet.funding.map((b) => (
                      <tr key={b.asset}>
                        <td>{b.asset}</td>
                        <td>{formatAmount(b.free)}</td>
                        <td>{formatAmount(b.locked)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </WalletCard>
          </div>
        )}
      </section>

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
          {connectError && <p className="error">{connectError}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Bağlanıyor..." : "Bağla"}
          </button>
        </form>
      </section>

      <p className="hint">Cüzdanlar arası transfer ekranı bir sonraki fazda burada görünecek.</p>
    </div>
  );
}

function WalletCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="wallet-card">
      <h3>{title}</h3>
      {children}
    </div>
  );
}
