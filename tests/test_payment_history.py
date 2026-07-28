from datetime import date
from decimal import Decimal

import pytest

from main import load_config
from loan_optimizer.cashflow import CashFlowProfile
from loan_optimizer.engine import SimulationEngine
from loan_optimizer.models import InterestMethod, Loan, RepaymentType
from loan_optimizer.optimizers import ManualOptimizer
from loan_optimizer.payment_utils import load_payment_history
from loan_optimizer.reporter import Reporter


def loan(loan_id="loan", principal="300", start=date(2026, 1, 10), tenure=3):
    return Loan(
        loan_id=loan_id,
        principal=Decimal(principal),
        annual_interest_rate=Decimal("0"),
        interest_method=InterestMethod.MONTHLY,
        repayment_type=RepaymentType.EMI,
        tenure_months=tenure,
        start_date=start,
    )


def engine(loans, income="1000", as_of_date=date(2026, 7, 28)):
    return SimulationEngine(
        loans=loans,
        cashflow=CashFlowProfile(Decimal(income), Decimal("0")),
        optimizer=ManualOptimizer({}),
        start_date=min(item.start_date for item in loans),
        as_of_date=as_of_date,
    )


def test_config_uses_oldest_loan_and_indexes_inflows_from_it(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        """cashflow:
  irregular_inflows:
    - date: "2025-02-01"
      amount: 25
loans:
  - loan_id: new
    principal: 100
    annual_interest_rate: 0
    tenure_months: 1
    start_date: "2026-01-01"
  - loan_id: old
    principal: 100
    annual_interest_rate: 0
    tenure_months: 1
    start_date: "2025-01-15"
"""
    )
    loans, cashflow, start = load_config(config)
    assert start == date(2025, 1, 15)
    assert [item.loan_id for item in loans] == ["new", "old"]
    assert cashflow.irregular_inflows == {2: Decimal("25")}


def test_month_keyed_payments_aggregate_and_replace_projection(tmp_path):
    item = loan()
    payments = tmp_path / "payments.csv"
    payments.write_text("loan_id,date,amount\nloan,2026-01-01,40\nloan,2026-01-31,60\n")
    load_payment_history(payments, [item])

    simulation = engine([item])
    simulation.run(max_months=1)
    record = simulation.history[0]["loans"]["loan"]

    assert record["actual_required_payment"] == Decimal("100.00")
    assert record["actual_payment"] == Decimal("100.00")
    assert record["projected_mandatory_payment"] == Decimal("0")
    assert record["projected_extra_payment"] == Decimal("0")
    assert record["actual_ending_balance"] == Decimal("200.00")
    assert record["projected_ending_balance"] == Decimal("200.00")


def test_recorded_payment_consumes_cash_only_once():
    first = loan("first", "300")
    second = loan("second", "300")
    first.payment_history[(2026, 1)] = Decimal("100")

    simulation = engine([first, second], income="100")
    simulation.run(max_months=1)
    first_record = simulation.history[0]["loans"]["first"]
    second_record = simulation.history[0]["loans"]["second"]

    assert first_record["actual_payment"] == Decimal("100")
    assert first_record["projected_mandatory_payment"] == Decimal("0")
    assert second_record["actual_payment"] == Decimal("0")
    assert second_record["actual_pending_payment"] == Decimal("100.00")


def test_accumulated_pending_carries_forward_and_can_be_cleared():
    item = loan()
    item.payment_history[(2026, 1)] = Decimal("50")
    item.payment_history[(2026, 2)] = Decimal("150")

    simulation = engine([item])
    simulation.run(max_months=2)
    january = simulation.history[0]["loans"]["loan"]
    february = simulation.history[1]["loans"]["loan"]

    assert january["actual_pending_payment"] == Decimal("50.00")
    assert january["actual_accumulated_pending_payment"] == Decimal("50.00")
    assert february["actual_pending_payment"] == Decimal("0")
    assert february["actual_accumulated_pending_payment"] == Decimal("0.00")


def test_unrecorded_projected_payment_is_not_an_actual_payment():
    item = loan()
    simulation = engine([item])
    simulation.run(max_months=1)
    record = simulation.history[0]["loans"]["loan"]

    assert record["projected_mandatory_payment"] == Decimal("100.00")
    assert record["actual_payment"] == Decimal("0")
    assert record["actual_pending_payment"] == Decimal("100.00")
    assert record["actual_accumulated_pending_payment"] == Decimal("100.00")


def test_actual_ledger_does_not_use_projected_payments():
    item = Loan(
        loan_id="crop",
        principal=Decimal("160000"),
        annual_interest_rate=Decimal("0.08"),
        interest_method=InterestMethod.MONTHLY,
        repayment_type=RepaymentType.INTEREST_ONLY,
        tenure_months=12,
        start_date=date(2026, 1, 10),
    )
    simulation = engine([item], as_of_date=date(2026, 2, 28))
    simulation.run(max_months=2)
    january = simulation.history[0]["loans"]["crop"]
    february = simulation.history[1]["loans"]["crop"]

    assert january["projected_ending_balance"] < january["actual_ending_balance"]
    assert february["actual_starting_balance"] == january["actual_ending_balance"]
    assert february["actual_starting_balance"] == Decimal("161066.67")


def test_actual_columns_are_blank_after_as_of_month():
    item = loan(tenure=4)
    simulation = engine([item], as_of_date=date(2026, 1, 31))
    simulation.run(max_months=2)
    february = simulation.history[1]["loans"]["loan"]

    assert february["projected_mandatory_payment"] == Decimal("75.00")
    assert february["actual_payment"] is None
    assert february["actual_ending_balance"] is None


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("loan_id,date,amount\nmissing,2026-01-01,10\n", "unknown loan_id"),
        ("loan_id,date,amount\nloan,not-a-date,10\n", "Invalid payments.csv row"),
        ("loan_id,date,amount\nloan,2026-01-01,0\n", "amount must be positive"),
    ],
)
def test_invalid_payment_history_is_rejected(tmp_path, contents, message):
    payments = tmp_path / "payments.csv"
    payments.write_text(contents)
    with pytest.raises(ValueError, match=message):
        load_payment_history(payments, [loan()])


def test_reporter_exports_and_renders_arrears_columns(tmp_path):
    item = loan()
    item.payment_history[(2026, 1)] = Decimal("50")
    simulation = engine([item])
    simulation.run(max_months=1)
    reporter = Reporter(simulation.history, simulation.history, simulation.cashflow, [item])

    dataframe = reporter.to_dataframe(simulation.history)
    assert {
        "projected_starting_balance",
        "projected_ending_balance",
        "actual_starting_balance",
        "actual_payment",
        "actual_accumulated_pending_payment",
    }.issubset(dataframe.columns)

    report_path = tmp_path / "report.html"
    reporter.generate_html_report(report_path)
    report = report_path.read_text(encoding="utf-8")
    assert "Actual Accumulated Pending" in report
    assert "Projected Required" in report
    assert 'class="table-scroll"' in report
