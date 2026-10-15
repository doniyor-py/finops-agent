"""AML signal detectors (MLR 2017 / NCA typology heuristics)."""

from aml_detector import (
    _uk_vat_valid_gb_nine_digits,
    check_routing_anomaly,
    check_structuring,
    run_aml_checks,
)


def inv(invoice_id, amount, client="Acme Ltd", **extra):
    return {"invoice_id": invoice_id, "amount_gbp": amount, "client_name": client, **extra}


def test_uk_vat_format():
    assert _uk_vat_valid_gb_nine_digits("GB123456789")
    assert _uk_vat_valid_gb_nine_digits("GB 123 4567 89")
    assert not _uk_vat_valid_gb_nine_digits("GB12345")
    assert not _uk_vat_valid_gb_nine_digits("FR123456789")


def test_two_invoices_just_under_threshold_flag_high():
    invoices = [inv("A", 9_600), inv("B", 9_800)]
    flags = check_structuring(invoices, invoices[0])
    assert [f["severity"] for f in flags] == ["HIGH"]


def test_four_invoices_just_under_threshold_flag_critical():
    invoices = [inv(i, 9_500 + n * 100) for n, i in enumerate("ABCD")]
    flags = check_structuring(invoices, invoices[0])
    assert flags[0]["severity"] == "CRITICAL"


def test_single_invoice_under_threshold_is_not_structuring():
    invoices = [inv("A", 9_900)]
    assert check_structuring(invoices, invoices[0]) == []


def test_other_clients_do_not_count_towards_structuring():
    invoices = [inv("A", 9_600, client="Acme Ltd"), inv("B", 9_800, client="Other plc")]
    assert check_structuring(invoices, invoices[0]) == []


def test_same_org_on_different_tld_is_not_a_routing_anomaly():
    flags = check_routing_anomaly(
        {"procurement_email": "buyer@acme.co.uk", "accounts_payable_email": "ap@acme.com"}
    )
    assert flags == []


def test_unrelated_payment_domain_is_a_routing_anomaly():
    flags = check_routing_anomaly(
        {"procurement_email": "buyer@acme.co.uk", "accounts_payable_email": "pay@fastcash-ltd.biz"}
    )
    assert [f["check_name"] for f in flags] == ["routing_domain_divergence"]


def test_high_severity_flag_requires_hard_block():
    invoices = [inv("A", 9_600), inv("B", 9_800)]
    result = run_aml_checks(invoices[0], invoices)
    assert result["hard_block_required"] is True
    assert result["flag_count"] >= 1


def test_sar_consideration_needs_a_critical_flag():
    invoices = [inv(i, 9_500 + n * 100) for n, i in enumerate("ABCD")]
    result = run_aml_checks(invoices[0], invoices)
    assert result["highest_severity"] == "CRITICAL"
    assert result["sar_consideration"] is (result["flag_count"] >= 2)
