"""The three-tier autonomy gate: AUTO / ESCALATE / HARD_BLOCK.

This is the core safety idea of Finoks: the model only acts alone where it is
safe to, escalates when unsure, and is hard-blocked from the rest.
"""

import pytest

import agent
from agent import AutonomyTier, determine_autonomy_tier


def invoice(**overrides):
    base = {
        "invoice_id": "INV-1",
        "amount_gbp": 200.0,
        "chase_count": 0,
        "aml_result": {},
        "specter_signal": {"risk_classification": "LOW", "cdd_status": "PASSED"},
    }
    base.update(overrides)
    return base


def test_small_clean_invoice_is_auto():
    assert determine_autonomy_tier(invoice()) == AutonomyTier.AUTO.value


# ---------- HARD_BLOCK ----------

def test_aml_hard_block_wins_over_everything():
    inv = invoice(aml_result={"hard_block_required": True})
    assert determine_autonomy_tier(inv) == AutonomyTier.HARD_BLOCK.value


def test_failed_cdd_is_hard_block():
    inv = invoice(specter_signal={"cdd_status": "FAILED"})
    assert determine_autonomy_tier(inv) == AutonomyTier.HARD_BLOCK.value


def test_flagged_counterparty_over_5k_is_hard_block():
    inv = invoice(amount_gbp=5000.01, specter_signal={"risk_classification": "FLAGGED"})
    assert determine_autonomy_tier(inv) == AutonomyTier.HARD_BLOCK.value


def test_hard_block_applies_even_in_full_auto_mode():
    agent.autonomy_config["mode"] = "full_auto"
    inv = invoice(aml_result={"hard_block_required": True})
    assert determine_autonomy_tier(inv) == AutonomyTier.HARD_BLOCK.value


# ---------- ESCALATE ----------

def test_amount_over_threshold_escalates():
    agent.autonomy_config["threshold_gbp"] = 500.0
    assert determine_autonomy_tier(invoice(amount_gbp=500.01)) == AutonomyTier.ESCALATE.value


def test_amount_exactly_at_threshold_stays_auto():
    agent.autonomy_config["threshold_gbp"] = 500.0
    assert determine_autonomy_tier(invoice(amount_gbp=500.0)) == AutonomyTier.AUTO.value


@pytest.mark.parametrize(
    "signal",
    [
        {"cdd_status": "REQUIRES_REVIEW"},
        {"risk_classification": "HIGH"},
    ],
)
def test_risky_counterparty_escalates(signal):
    assert determine_autonomy_tier(invoice(specter_signal=signal)) == AutonomyTier.ESCALATE.value


def test_third_chase_escalates():
    assert determine_autonomy_tier(invoice(chase_count=3)) == AutonomyTier.ESCALATE.value


def test_human_all_mode_escalates_everything():
    agent.autonomy_config["mode"] = "human_all"
    assert determine_autonomy_tier(invoice()) == AutonomyTier.ESCALATE.value


@pytest.mark.parametrize("action", ["escalate_legal", "escalate_account_manager"])
def test_guided_mode_escalates_legal_and_account_manager_actions(action):
    agent.autonomy_config["mode"] = "guided"
    assert determine_autonomy_tier(invoice(_pending_action=action)) == AutonomyTier.ESCALATE.value


def test_full_auto_mode_does_not_escalate_legal_action():
    agent.autonomy_config["mode"] = "full_auto"
    assert determine_autonomy_tier(invoice(_pending_action="escalate_legal")) == AutonomyTier.AUTO.value


def test_unknown_mode_fails_safe_to_escalate():
    agent.autonomy_config["mode"] = "something-else"
    assert determine_autonomy_tier(invoice()) == AutonomyTier.ESCALATE.value
