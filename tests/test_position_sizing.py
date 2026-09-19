import pytest

from app.position_sizing import NEUTRAL_FEE_MULT, compute_position_sizing

# margin=2$, kaldıraç=5x -> notional=10$, quantity=0.1.
# fee_per_side = 10 * 0.0005 = 0.005 -> total_fee (giriş+çıkış) = 0.01.
# TP mesafesi (20x toplam komisyon) = 0.2 / 0.1 = 2.0 fiyat birimi.
# SL mesafesi (10x toplam komisyon) = 0.1 / 0.1 = 1.0 fiyat birimi.
TP_DISTANCE = 2.0
SL_DISTANCE = 1.0


def test_long_sizing_uses_default_margin_leverage_and_fee_mults():
    stop_loss, take_profit, quantity = compute_position_sizing(100.0, "LONG")

    assert quantity == pytest.approx(0.1)  # (2$ * 5x) / 100
    assert stop_loss == pytest.approx(100 - SL_DISTANCE)
    assert take_profit == pytest.approx(100 + TP_DISTANCE)


def test_short_sizing_mirrors_long():
    stop_loss, take_profit, quantity = compute_position_sizing(100.0, "SHORT")

    assert quantity == pytest.approx(0.1)
    assert stop_loss == pytest.approx(100 + SL_DISTANCE)
    assert take_profit == pytest.approx(100 - TP_DISTANCE)


def test_sizing_scales_with_margin_and_leverage():
    # notional = 4$ * 10x = 40$ -> quantity = 0.4; total_fee = 40*0.0005*2 = 0.04
    stop_loss, take_profit, quantity = compute_position_sizing(
        100.0, "LONG", margin_usd=4.0, leverage=10
    )

    assert quantity == pytest.approx(0.4)
    sl_distance = (10.0 * 0.04) / 0.4
    tp_distance = (20.0 * 0.04) / 0.4
    assert stop_loss == pytest.approx(100 - sl_distance)
    assert take_profit == pytest.approx(100 + tp_distance)


def test_custom_fee_mults_override_defaults():
    stop_loss, take_profit, _ = compute_position_sizing(100.0, "LONG", sl_fee_mult=1.0, tp_fee_mult=1.0)

    # total_fee=0.01, quantity=0.1 -> mesafe = 1*0.01/0.1 = 0.1 her iki taraf için de
    assert stop_loss == pytest.approx(99.9)
    assert take_profit == pytest.approx(100.1)


def test_neutral_fee_mult_produces_symmetric_distance():
    stop_loss, take_profit, _ = compute_position_sizing(
        100.0, "LONG", sl_fee_mult=NEUTRAL_FEE_MULT, tp_fee_mult=NEUTRAL_FEE_MULT
    )

    assert (100.0 - stop_loss) == pytest.approx(take_profit - 100.0)


def test_sizing_is_independent_of_entry_price_scale():
    # Fiyat ölçeği değişse de (ör. BTC ~60000 vs alt coin ~0.5) mesafe entry'nin
    # sabit bir yüzdesi olarak kalmalı (fee formülünden dolayı).
    low, high, _ = compute_position_sizing(0.5, "LONG")
    big, big_tp, _ = compute_position_sizing(60_000.0, "LONG")

    assert (0.5 - low) / 0.5 == pytest.approx((60_000.0 - big) / 60_000.0)
