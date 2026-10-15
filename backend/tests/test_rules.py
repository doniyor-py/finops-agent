"""Rule engine, statutory interest and email routing."""

import pytest

import agent
from agent import apply_rules, calculate_uk_late_payment_interest, route_for_action


# ---------- apply_rules ----------

@pytest.mark.parametrize(
    "days, expected",
    [
        (0, "ready"),
        (1, "overdue_30"),
        (30, "overdue_30"),
        (59, "overdue_30"),
        (60, "overdue_60"),
        (89, "overdue_60"),
        (90, "overdue_90_plus"),
        (400, "overdue_90_plus"),
    ],
)
def test_overdue_bands(days, expected):
    assert apply_rules({"amount_gbp": 100, "days_overdue": days}) == expected


def test_aml_flagged_status_always_hard_blocks():
    inv = {"status": "aml_flagged", "days_overdue": 120, "hold_reason": "dispute"}
    assert apply_rules(inv) == "hard_block_aml"


def test_paid_pending_beats_overdue():
    assert apply_rules({"status": "paid_pending", "days_overdue": 95}) == "paid_pending"


@pytest.mark.parametrize(
    "hold, expected",
    [("customer dispute", "hold_dispute"), ("payment plan agreed", "hold_payment_plan"), ("instalments", "hold_payment_plan")],
)
def test_hold_reasons(hold, expected):
    assert apply_rules({"hold_reason": hold, "days_overdue": 45}) == expected


@pytest.mark.parametrize(
    "po_status, expected",
    [("missing", "po_missing"), ("expired", "po_expired"), ("expiring_soon", "po_expiring_soon")],
)
def test_purchase_order_states(po_status, expected):
    assert apply_rules({"po_status": po_status, "days_overdue": 10}) == expected


def test_required_po_without_number_is_missing():
    assert apply_rules({"po_required": True, "days_overdue": 10}) == "po_missing"


# ---------- UK Late Payment Act interest ----------

def test_no_interest_within_30_days():
    inv = {"amount_gbp": 10_000, "days_overdue": 30}
    assert calculate_uk_late_payment_interest(inv) == 0.0
    assert inv["late_payment_interest"] == 0.0


def test_interest_after_30_days_uses_13_5_percent_annual_rate():
    inv = {"amount_gbp": 10_000, "days_overdue": 73}
    # 10,000 * 0.135 / 365 * 73 = 270.00
    assert calculate_uk_late_payment_interest(inv) == 270.0
    assert inv["late_payment_rate_pct"] == pytest.approx(13.5)


def test_interest_can_be_switched_off():
    agent.autonomy_config["uk_late_payment_act"] = False
    assert calculate_uk_late_payment_interest({"amount_gbp": 10_000, "days_overdue": 90}) == 0.0


# ---------- routing ----------

CONTACTS = {"procurement_email": "buyer@acme.co.uk", "accounts_payable_email": "ap@acme.co.uk"}


def test_po_actions_go_to_procurement():
    to, _ = route_for_action(CONTACTS, "po_missing")
    assert to == "buyer@acme.co.uk"


def test_overdue_actions_go_to_accounts_payable():
    to, _ = route_for_action(CONTACTS, "overdue_60")
    assert to == "ap@acme.co.uk"


def test_routing_falls_back_when_a_contact_is_missing():
    to, reason = route_for_action({"accounts_payable_email": "ap@acme.co.uk"}, "po_expired")
    assert to == "ap@acme.co.uk"
    assert "procurement contact missing" in reason


def test_no_contacts_returns_empty_address():
    to, _ = route_for_action({}, "overdue_30")
    assert to == ""
