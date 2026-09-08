from app.whale_tracker.models import ModuleSignal, TrapScoreResult


class TrapScorer:
    """Sinyal ve Skorlama Motoru (Trap Scorer).

    Her modülün ağırlıklı katkısını toplayarak 0-100 arasında tek bir "Tuzak Skoru"
    üretir. Yönlü sinyaller (LONG/SHORT) kendi taraflarına eklenir; yönsüz sinyaller
    (ör. OI birikimi — direction=None) doğrudan bir taraf seçmez, o anki baskın yöne
    (hangi taraf daha yüksek puanlıysa) eklenerek onu güçlendirir. Sonuç, baskın
    tarafın toplam puanı ve o tarafın yönüdür.

    Örnek: Yüksek Hacim Girişi (LONG) + Aşırı Negatif Funding Rate (LONG) + Yüksek OI
    Artışı (yönsüz, LONG tarafını güçlendirir) + Short Likidasyon Patlaması (LONG)
    → tüm ağırlıklar LONG tarafında toplanır → LONG Tuzak Skoru 85+.
    """

    DEFAULT_WEIGHTS: dict[str, float] = {
        "volume": 0.20,
        "open_interest": 0.25,
        "funding_rate": 0.25,
        "liquidation": 0.20,
        "orderbook": 0.10,
    }

    CRISIS_WEIGHTS: dict[str, float] = {
        "volume": 0.15,
        "open_interest": 0.35,
        "funding_rate": 0.10,
        "liquidation": 0.35,
        "orderbook": 0.05,
    }
    """Piyasa sakinken emir defteri dengesizliği (%10) anlamlı bir sinyaldir; ama bir
    likidasyon patlaması (Modül C tetiklendiğinde) sırasında emir defteri hızla
    anlamsızlaşır (spread açılır, defter boşalır) ve OI/likidasyon çok daha güvenilir
    hale gelir. Likidasyon modülü tetiklendiğinde skor motoru otomatik olarak bu 'kriz'
    ağırlıklarına geçer (dinamik ağırlıklandırma)."""

    def __init__(self, weights: dict[str, float] | None = None, crisis_weights: dict[str, float] | None = None) -> None:
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)
        self.crisis_weights = crisis_weights or dict(self.CRISIS_WEIGHTS)

    def score(self, signals: dict[str, ModuleSignal]) -> TrapScoreResult:
        liquidation_signal = signals.get("liquidation")
        crisis_mode = bool(liquidation_signal and liquidation_signal.triggered)
        weights = self.crisis_weights if crisis_mode else self.weights
        regime = "crisis" if crisis_mode else "normal"

        long_score = 0.0
        short_score = 0.0
        undirected_score = 0.0

        for name, signal in signals.items():
            if not signal.triggered:
                continue
            weight = weights.get(name, 0.0)
            contribution = weight * signal.score

            if signal.direction == "LONG":
                long_score += contribution
            elif signal.direction == "SHORT":
                short_score += contribution
            else:
                undirected_score += contribution

        if long_score == 0 and short_score == 0:
            return TrapScoreResult(score=round(undirected_score, 1), direction=None, signals=signals, regime=regime)

        if long_score >= short_score:
            return TrapScoreResult(
                score=round(long_score + undirected_score, 1), direction="LONG", signals=signals, regime=regime
            )
        return TrapScoreResult(
            score=round(short_score + undirected_score, 1), direction="SHORT", signals=signals, regime=regime
        )
