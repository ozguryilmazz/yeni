import { FormEvent, ReactNode, useEffect, useState } from "react";

import {
  Credential,
  connectCredential,
  deleteCredential,
  listCredentials,
} from "../api/credentials";
import { createTransfer, listTransfers, Transfer, WalletType } from "../api/transfers";
import { fetchBalances, WalletSummary } from "../api/wallet";
import { useAuth } from "../context/AuthContext";

const WALLET_LABELS: Record<WalletType, string> = {
  SPOT: "Spot",
  USDM_FUTURES: "Futures (USDⓈ-M)",
  FUNDING: "Funding",
};
const WALLET_OPTIONS = Object.keys(WALLET_LABELS) as WalletType[];

const TRANSFER_STATUS_LABELS: Record<Transfer["status"], string> = {
  PENDING: "Beklemede",
  SUCCESS: "Başarılı",
  FAILED: "Başarısız",
};

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

  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [transfersLoading, setTransfersLoading] = useState(true);
  const [transferFrom, setTransferFrom] = useState<WalletType>("SPOT");
  const [transferTo, setTransferTo] = useState<WalletType>("USDM_FUTURES");
  const [transferAsset, setTransferAsset] = useState("USDT");
  const [transferAmount, setTransferAmount] = useState("");
  const [transferError, setTransferError] = useState<string | null>(null);
  const [transferSubmitting, setTransferSubmitting] = useState(false);

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

  const refreshTransfers = async () => {
    setTransfersLoading(true);
    try {
      setTransfers(await listTransfers());
    } finally {
      setTransfersLoading(false);
    }
  };

  useEffect(() => {
    refreshCredentials();
    refreshTransfers();
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

  const handleTransfer = async (event: FormEvent) => {
    event.preventDefault();
    setTransferError(null);

    if (transferFrom === transferTo) {
      setTransferError("Kaynak ve hedef cüzdan aynı olamaz");
      return;
    }

    setTransferSubmitting(true);
    try {
      await createTransfer({
        credential_id: selectedCredentialId || undefined,
        asset: transferAsset.trim().toUpperCase(),
        amount: transferAmount,
        from_wallet: transferFrom,
        to_wallet: transferTo,
      });
      setTransferAmount("");
      await Promise.all([refreshTransfers(), loadBalances()]);
    } catch (err) {
      setTransferError(extractErrorMessage(err, "Transfer başarısız oldu"));
    } finally {
      setTransferSubmitting(false);
    }
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

      <section>
        <h2>Cüzdanlar Arası Transfer</h2>
        {credentials.length === 0 ? (
          <p className="hint">Transfer yapmak için önce bir Binance hesabı bağlayın.</p>
        ) : (
          <form onSubmit={handleTransfer}>
            <label>
              Kaynak Cüzdan
              <select value={transferFrom} onChange={(e) => setTransferFrom(e.target.value as WalletType)}>
                {WALLET_OPTIONS.map((w) => (
                  <option key={w} value={w}>
                    {WALLET_LABELS[w]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Hedef Cüzdan
              <select value={transferTo} onChange={(e) => setTransferTo(e.target.value as WalletType)}>
                {WALLET_OPTIONS.map((w) => (
                  <option key={w} value={w}>
                    {WALLET_LABELS[w]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Coin
              <input
                value={transferAsset}
                onChange={(e) => setTransferAsset(e.target.value)}
                required
                placeholder="USDT"
              />
            </label>
            <label>
              Miktar
              <input
                type="number"
                step="any"
                min="0"
                value={transferAmount}
                onChange={(e) => setTransferAmount(e.target.value)}
                required
              />
            </label>
            {transferError && <p className="error">{transferError}</p>}
            <button type="submit" disabled={transferSubmitting}>
              {transferSubmitting ? "Transfer ediliyor..." : "Transfer Et"}
            </button>
          </form>
        )}

        <h3>Transfer Geçmişi</h3>
        {transfersLoading ? (
          <p>Yükleniyor...</p>
        ) : transfers.length === 0 ? (
          <p className="hint">Henüz transfer yapılmadı.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Tarih</th>
                <th>Coin</th>
                <th>Miktar</th>
                <th>Yön</th>
                <th>Durum</th>
              </tr>
            </thead>
            <tbody>
              {transfers.map((t) => (
                <tr key={t.id}>
                  <td>{new Date(t.created_at).toLocaleString("tr-TR")}</td>
                  <td>{t.asset}</td>
                  <td>{t.amount}</td>
                  <td>
                    {WALLET_LABELS[t.from_wallet]} → {WALLET_LABELS[t.to_wallet]}
                  </td>
                  <td title={t.error_message ?? undefined}>{TRANSFER_STATUS_LABELS[t.status]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
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
