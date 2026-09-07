import { useAuth } from "../context/AuthContext";

export default function Dashboard() {
  const { user, logout } = useAuth();

  return (
    <div className="dashboard">
      <header>
        <h1>Cüzdan Özeti</h1>
        <div>
          <span>{user?.email}</span>
          <button onClick={logout}>Çıkış Yap</button>
        </div>
      </header>
      <p>
        Binance hesabı henüz bağlanmadı. Spot / Futures / Funding bakiyeleri ve transfer ekranı bir sonraki
        fazda burada görünecek.
      </p>
    </div>
  );
}
