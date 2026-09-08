from app.whale_tracker.models import ModuleSignal


class VolumeSurgeModule:
    """Bonus modül — mevcut 1s/4s/24s hacim verisiyle entegre çalışır. Son periyodun
    hacmi, geçmiş periyotların ortalamasının `surge_multiplier` katından fazlaysa
    "hacim patlaması" sayılır; yön, o periyottaki fiyat değişiminin işaretinden alınır
    (yükselişte LONG, düşüşte SHORT) — hacmin kendisi yön belirtmez, fiyatla
    birlikte yorumlanır."""

    def __init__(self, surge_multiplier: float = 2.0) -> None:
        self.surge_multiplier = surge_multiplier

    def evaluate(self, current_volume: float, average_volume: float, price_change_percent: float) -> ModuleSignal:
        if average_volume <= 0:
            return ModuleSignal(False, 0, "Ortalama hacim verisi yok")

        ratio = current_volume / average_volume
        if ratio < self.surge_multiplier:
            return ModuleSignal(False, 0, f"Hacim normal (ortalamanın x{ratio:.2f} katı)")

        direction = None
        if price_change_percent > 0:
            direction = "LONG"
        elif price_change_percent < 0:
            direction = "SHORT"

        score = min(100.0, ratio / self.surge_multiplier * 50)
        return ModuleSignal(
            True,
            score,
            f"Hacim patlaması: ortalamanın x{ratio:.2f} katı, fiyat değişimi %{price_change_percent:+.2f}",
            direction=direction,
        )
