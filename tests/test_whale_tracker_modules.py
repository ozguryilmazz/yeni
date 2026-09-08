"""whale_tracker'daki saf mantık modüllerinin (ağ/websocket gerektirmeyen) testleri."""

from app.whale_tracker.funding_rate import FundingRateAnomalyModule
from app.whale_tracker.liquidation import LiquidationTracker
from app.whale_tracker.models import ModuleSignal
from app.whale_tracker.open_interest import OpenInterestDivergenceModule
from app.whale_tracker.orderbook import OrderbookImbalanceModule
from app.whale_tracker.scorer import TrapScorer
from app.whale_tracker.volume_surge import VolumeSurgeModule


# ---- Modül A: Open Interest & Hacim Diverjans -----------------------------


def test_oi_module_triggers_when_price_flat_and_oi_rising():
    module = OpenInterestDivergenceModule(price_change_threshold_pct=0.5, oi_change_threshold_pct=5.0)
    module.update(1000.0, timestamp=0)
    module.update(1060.0, timestamp=100)  # %6 artış

    signal = module.evaluate(price_change_percent_1h=0.2)  # yatay fiyat

    assert signal.triggered is True
    assert signal.direction is None  # OI birikimi tek başına yönsüzdür


def test_oi_module_does_not_trigger_when_price_moves():
    module = OpenInterestDivergenceModule(price_change_threshold_pct=0.5, oi_change_threshold_pct=5.0)
    module.update(1000.0, timestamp=0)
    module.update(1060.0, timestamp=100)

    signal = module.evaluate(price_change_percent_1h=3.0)  # fiyat zaten hareket etmiş

    assert signal.triggered is False


def test_oi_module_requires_at_least_two_samples():
    module = OpenInterestDivergenceModule()
    module.update(1000.0)
    signal = module.evaluate(price_change_percent_1h=0.0)
    assert signal.triggered is False


def test_oi_module_forgets_samples_outside_window():
    module = OpenInterestDivergenceModule(window_seconds=60)
    module.update(1000.0, timestamp=0)
    module.update(1060.0, timestamp=200)  # ilk örnek pencere dışına düşer

    signal = module.evaluate(price_change_percent_1h=0.0)

    # tek örnek kaldığı için yetersiz veri
    assert signal.triggered is False


# ---- Modül B: Funding Rate Anomali ----------------------------------------


def test_funding_rate_very_negative_signals_long():
    module = FundingRateAnomalyModule(short_squeeze_threshold=-0.0003, long_squeeze_threshold=0.0005)
    signal = module.evaluate(-0.0004)
    assert signal.triggered is True
    assert signal.direction == "LONG"


def test_funding_rate_very_positive_signals_short():
    module = FundingRateAnomalyModule(short_squeeze_threshold=-0.0003, long_squeeze_threshold=0.0005)
    signal = module.evaluate(0.0006)
    assert signal.triggered is True
    assert signal.direction == "SHORT"


def test_funding_rate_normal_range_does_not_trigger():
    module = FundingRateAnomalyModule(short_squeeze_threshold=-0.0003, long_squeeze_threshold=0.0005)
    signal = module.evaluate(0.0001)
    assert signal.triggered is False


# ---- Modül C: Likidasyon Takipçisi ----------------------------------------


def test_liquidation_tracker_short_liquidation_burst_signals_long():
    """SHORT pozisyonlar likide oluyorsa (BUY forceOrder), tersine (LONG) sinyal beklenir."""
    tracker = LiquidationTracker(window_seconds=60, threshold_usdt=1_000_000)
    tracker.add_liquidation("BUY", quantity=50, price=30_000, timestamp=0)  # 1.5M USDT

    signal = tracker.evaluate()

    assert signal.triggered is True
    assert signal.direction == "LONG"


def test_liquidation_tracker_long_liquidation_burst_signals_short():
    """LONG pozisyonlar likide oluyorsa (SELL forceOrder), tersine (SHORT) sinyal beklenir."""
    tracker = LiquidationTracker(window_seconds=60, threshold_usdt=1_000_000)
    tracker.add_liquidation("SELL", quantity=50, price=30_000, timestamp=0)

    signal = tracker.evaluate()

    assert signal.triggered is True
    assert signal.direction == "SHORT"


def test_liquidation_tracker_below_threshold_does_not_trigger():
    tracker = LiquidationTracker(window_seconds=60, threshold_usdt=1_000_000)
    tracker.add_liquidation("BUY", quantity=1, price=100, timestamp=0)

    signal = tracker.evaluate()

    assert signal.triggered is False


def test_liquidation_tracker_forgets_events_outside_window():
    tracker = LiquidationTracker(window_seconds=60, threshold_usdt=1_000_000)
    tracker.add_liquidation("BUY", quantity=50, price=30_000, timestamp=0)

    # evaluate() içindeki _trim() "şimdi"yi kullanır; eski olayı taklit etmek için
    # doğrudan _trim'i ileri bir zamanla çağırıyoruz.
    tracker._trim(now=200)

    signal = tracker.evaluate()
    assert signal.triggered is False


def test_liquidation_tracker_update_threshold_changes_trigger_point():
    tracker = LiquidationTracker(window_seconds=60, threshold_usdt=1_000_000)
    tracker.add_liquidation("BUY", quantity=1, price=500, timestamp=0)  # 500 USDT, eşiğin altında

    assert tracker.evaluate().triggered is False

    tracker.update_threshold(400)  # dinamik eşik: sembolün 24s hacminin küçük bir yüzdesi

    assert tracker.evaluate().triggered is True


def test_liquidation_tracker_still_accelerating_cascade_does_not_trigger():
    """Şelale hızlanmaya devam ediyorsa (yeni yarı > eski yarı), tersine tepki için
    henüz erken sayılır — bıçağı tutma riskine karşı tetiklenmemesi beklenir."""
    tracker = LiquidationTracker(window_seconds=60, threshold_usdt=1_000_000)
    tracker.add_liquidation("SELL", quantity=1, price=400_000, timestamp=0)  # eski yarı: 400k
    tracker.add_liquidation("SELL", quantity=1, price=700_000, timestamp=45)  # yeni yarı: 700k, toplam 1.1M

    signal = tracker.evaluate()

    assert signal.triggered is False
    assert "HIZLANIYOR" in signal.message


def test_liquidation_tracker_decelerating_cascade_triggers():
    """Şelale yavaşlıyorsa (yeni yarı <= eski yarı), tersine tepki sinyali normal
    şekilde üretilir."""
    tracker = LiquidationTracker(window_seconds=60, threshold_usdt=1_000_000)
    tracker.add_liquidation("SELL", quantity=1, price=700_000, timestamp=0)  # eski yarı: 700k
    tracker.add_liquidation("SELL", quantity=1, price=400_000, timestamp=45)  # yeni yarı: 400k, toplam 1.1M

    signal = tracker.evaluate()

    assert signal.triggered is True
    assert signal.direction == "SHORT"  # LONG likide oldu -> tersine SHORT


# ---- Modül D: Emir Defteri Dengesizliği -----------------------------------


def test_orderbook_module_bid_heavy_signals_long_after_confirmation():
    module = OrderbookImbalanceModule(up_pressure_ratio=2.5, down_pressure_ratio=0.4, confirmation_updates=3)

    # İlk iki güncelleme henüz "doğrulanıyor" aşamasında, tetiklenmemeli.
    assert module.evaluate(bid_volume=300, ask_volume=100).triggered is False
    assert module.evaluate(bid_volume=300, ask_volume=100).triggered is False

    signal = module.evaluate(bid_volume=300, ask_volume=100)  # 3. ardışık güncelleme, oran 3.0
    assert signal.triggered is True
    assert signal.direction == "LONG"


def test_orderbook_module_ask_heavy_signals_short_after_confirmation():
    module = OrderbookImbalanceModule(up_pressure_ratio=2.5, down_pressure_ratio=0.4, confirmation_updates=3)
    module.evaluate(bid_volume=30, ask_volume=100)
    module.evaluate(bid_volume=30, ask_volume=100)

    signal = module.evaluate(bid_volume=30, ask_volume=100)  # oran 0.3, 3. ardışık güncelleme
    assert signal.triggered is True
    assert signal.direction == "SHORT"


def test_orderbook_module_momentary_spike_does_not_trigger_spoof_filter():
    """Tek bir anlık sıçrama (sahte duvar/spoof) sonrası oran normale dönerse tetiklenmemeli."""
    module = OrderbookImbalanceModule(up_pressure_ratio=2.5, down_pressure_ratio=0.4, confirmation_updates=3)

    signal1 = module.evaluate(bid_volume=300, ask_volume=100)  # anlık sıçrama, oran 3.0
    signal2 = module.evaluate(bid_volume=100, ask_volume=100)  # hemen geri çekildi, oran 1.0
    signal3 = module.evaluate(bid_volume=300, ask_volume=100)  # tekrar sıçrama

    assert signal1.triggered is False  # henüz doğrulanmadı
    assert signal2.triggered is False  # spoof geri çekildi, kalıcı değil
    assert signal3.triggered is False  # son 3 güncellemenin TAMAMI eşiği aşmıyor (signal2 araya girdi)


def test_orderbook_module_balanced_does_not_trigger():
    module = OrderbookImbalanceModule(up_pressure_ratio=2.5, down_pressure_ratio=0.4)
    signal = module.evaluate(bid_volume=100, ask_volume=100)
    assert signal.triggered is False


# ---- Bonus: Hacim Patlaması ------------------------------------------------


def test_volume_surge_up_signals_long():
    module = VolumeSurgeModule(surge_multiplier=2.0)
    signal = module.evaluate(current_volume=300, average_volume=100, price_change_percent=1.5)
    assert signal.triggered is True
    assert signal.direction == "LONG"


def test_volume_surge_down_signals_short():
    module = VolumeSurgeModule(surge_multiplier=2.0)
    signal = module.evaluate(current_volume=300, average_volume=100, price_change_percent=-1.5)
    assert signal.triggered is True
    assert signal.direction == "SHORT"


def test_volume_surge_below_multiplier_does_not_trigger():
    module = VolumeSurgeModule(surge_multiplier=2.0)
    signal = module.evaluate(current_volume=120, average_volume=100, price_change_percent=1.0)
    assert signal.triggered is False


# ---- Trap Scorer ------------------------------------------------------------


def test_trap_scorer_users_worked_example_produces_long_85_plus():
    """Kullanıcının verdiği örnek: Yüksek Hacim Girişi (LONG) + Aşırı Negatif Funding
    Rate (LONG) + Yüksek OI Artışı (yönsüz) + Anlık Short Likidasyon Patlaması (LONG)
    => LONG Tuzak Skoru 85+."""
    funding_module = FundingRateAnomalyModule()
    oi_module = OpenInterestDivergenceModule()
    oi_module.update(1000.0, timestamp=0)
    oi_module.update(1080.0, timestamp=100)  # %8 artış, sıkışma birikimi
    liquidation_tracker = LiquidationTracker(threshold_usdt=1_000_000)
    liquidation_tracker.add_liquidation("BUY", quantity=100, price=30_000, timestamp=0)  # short likide -> LONG
    volume_module = VolumeSurgeModule()

    signals = {
        "volume": volume_module.evaluate(current_volume=500, average_volume=100, price_change_percent=2.0),
        "open_interest": oi_module.evaluate(price_change_percent_1h=0.1),
        "funding_rate": funding_module.evaluate(-0.001),  # çok negatif
        "liquidation": liquidation_tracker.evaluate(),
        "orderbook": OrderbookImbalanceModule().evaluate(bid_volume=0, ask_volume=0),  # veri yok, katkısız
    }

    result = TrapScorer().score(signals)

    assert result.direction == "LONG"
    assert result.score >= 85


def test_trap_scorer_picks_the_heavier_weighted_direction():
    scorer = TrapScorer()
    orderbook_module = OrderbookImbalanceModule()
    orderbook_module.evaluate(bid_volume=30, ask_volume=100)
    orderbook_module.evaluate(bid_volume=30, ask_volume=100)

    signals = {
        "funding_rate": FundingRateAnomalyModule().evaluate(-0.001),  # LONG, ağırlık .25 -> katkı 25
        # SHORT, ağırlık .10 -> katkı 10 (3. ardışık doğrulama ile tetiklenir)
        "orderbook": orderbook_module.evaluate(bid_volume=30, ask_volume=100),
    }

    result = scorer.score(signals)

    # Skor, net fark değil kazanan tarafın toplam katkısıdır (karşıt taraf ayrıca çıkarılmaz).
    assert result.direction == "LONG"
    assert result.score == 25.0
    assert result.regime == "normal"  # likidasyon anahtarı yok/tetiklenmedi -> normal ağırlıklar


def test_trap_scorer_no_signals_triggered_returns_zero_and_no_direction():
    scorer = TrapScorer()
    signals = {
        "funding_rate": FundingRateAnomalyModule().evaluate(0.0001),
        "orderbook": OrderbookImbalanceModule().evaluate(bid_volume=100, ask_volume=100),
    }

    result = scorer.score(signals)

    assert result.score == 0
    assert result.direction is None


def test_trap_scorer_switches_to_crisis_weights_when_liquidation_triggers():
    """Likidasyon modülü tetiklendiğinde skor motoru 'kriz ağırlıklarına' geçmeli:
    emir defteri ağırlığı düşer, OI/likidasyon ağırlığı artar."""
    scorer = TrapScorer()
    liquidation_tracker = LiquidationTracker(threshold_usdt=1_000_000)
    liquidation_tracker.add_liquidation("BUY", quantity=100, price=30_000, timestamp=0)  # short likide -> LONG

    signals = {
        "liquidation": liquidation_tracker.evaluate(),
        "open_interest": ModuleSignal(True, 100, "birikim", direction=None),
    }

    result = scorer.score(signals)

    assert result.regime == "crisis"
    # CRISIS_WEIGHTS: liquidation .35 + open_interest (undirected) .35 = 70
    assert result.score == 70.0
    assert result.direction == "LONG"


def test_trap_scorer_normal_regime_when_liquidation_not_triggered():
    scorer = TrapScorer()
    signals = {
        "liquidation": LiquidationTracker().evaluate(),  # hiç event yok -> tetiklenmez
        "funding_rate": FundingRateAnomalyModule().evaluate(-0.001),
    }

    result = scorer.score(signals)

    assert result.regime == "normal"
    assert result.score == 25.0  # DEFAULT_WEIGHTS: funding_rate .25 * 100
