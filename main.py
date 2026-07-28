"""
Entry point for the Loan Optimization Engine.
Loads the YAML configuration, runs both baseline and optimized simulations,
and generates the final HTML and CSV reports.
"""

import yaml
from decimal import Decimal
from datetime import datetime, date
from pathlib import Path
from loan_optimizer.models import Loan, InterestMethod, RepaymentType
from loan_optimizer.cashflow import CashFlowProfile
from loan_optimizer.optimizers import AvalancheOptimizer, ManualOptimizer
from loan_optimizer.engine import SimulationEngine
from loan_optimizer.reporter import Reporter
from loan_optimizer.payment_utils import load_payment_history
import os


def load_config(filepath: str | Path, payments_filepath: str | Path | None = None):
    config_path = Path(filepath)
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cashflow_data = data.get("cashflow", {})

    loans = []
    for loan_data in data.get("loans", []):
        start_date_str = loan_data.get("start_date")
        start_date = (
            datetime.strptime(start_date_str, "%Y-%m-%d").date()
            if start_date_str
            else date.today()
        )

        loan = Loan(
            loan_id=loan_data["loan_id"],
            principal=Decimal(str(loan_data["principal"])),
            annual_interest_rate=Decimal(str(loan_data["annual_interest_rate"])),
            interest_method=InterestMethod[
                loan_data.get("interest_method", "MONTHLY").upper()
            ],
            repayment_type=RepaymentType[
                loan_data.get("repayment_type", "EMI").upper()
            ],
            tenure_months=loan_data["tenure_months"],
            start_date=start_date,
        )
        loans.append(loan)

    if not loans:
        raise ValueError("config.yaml must define at least one loan")

    # All schedules and date-indexed cash-flow events share the oldest loan's
    # month as their anchor.
    sim_start_date = min(loan.start_date for loan in loans)

    irregular_inflows_dict = {}
    for inflow in cashflow_data.get("irregular_inflows", []):
        inflow_date = datetime.strptime(inflow["date"], "%Y-%m-%d").date()
        months_diff = (inflow_date.year - sim_start_date.year) * 12 + (
            inflow_date.month - sim_start_date.month
        )
        month_index = months_diff + 1
        if month_index > 0:
            irregular_inflows_dict[month_index] = irregular_inflows_dict.get(
                month_index, Decimal("0")
            ) + Decimal(str(inflow["amount"]))

    cashflow = CashFlowProfile(
        monthly_income=Decimal(str(cashflow_data.get("monthly_income", "0"))),
        fixed_living_expenses=Decimal(
            str(cashflow_data.get("fixed_living_expenses", "0"))
        ),
        emergency_buffer=Decimal(str(cashflow_data.get("emergency_buffer", "0"))),
        income_growth_rate_annual=Decimal(
            str(cashflow_data.get("income_growth_rate_annual", "0"))
        ),
        expense_inflation_rate_annual=Decimal(
            str(cashflow_data.get("expense_inflation_rate_annual", "0"))
        ),
        irregular_outflows={
            k: Decimal(str(v))
            for k, v in cashflow_data.get("irregular_outflows", {}).items()
        },
        irregular_inflows=irregular_inflows_dict,
    )

    payment_path = Path(payments_filepath) if payments_filepath else config_path.with_name("payments.csv")
    if payment_path.exists():
        load_payment_history(payment_path, loans)

    return loans, cashflow, sim_start_date


def run_scenario():
    print("Loading configuration from config.yaml...")
    loans, cashflow, sim_start_date = load_config("config.yaml")

    print("Running Baseline Simulation (No Prepayments)...")
    baseline_optimizer = ManualOptimizer({})
    baseline_engine = SimulationEngine(
        loans=loans,
        cashflow=cashflow,
        optimizer=baseline_optimizer,
        start_date=sim_start_date,
    )
    baseline_engine.run()

    print("Running Optimized Simulation (Avalanche Strategy)...")
    optimizer = AvalancheOptimizer()
    engine = SimulationEngine(
        loans=loans, cashflow=cashflow, optimizer=optimizer, start_date=sim_start_date
    )
    engine.run()

    # Reporting
    reporter = Reporter(engine.history, baseline_engine.history, cashflow, loans)
    df = reporter.to_dataframe(engine.history)

    print("\nSimulation complete. Generating report...")
    df.to_csv("output_history.csv", index=False)
    reporter.generate_html_report("report.html")

    html_abs_path = os.path.abspath("report.html").replace("\\", "/")
    reporter.generate_pdf_report(html_abs_path, "report.pdf")

    print(f"Total months simulated (Optimized): {df['month_index'].max()}")
    print("Reports generated: output_history.csv, report.html, and report.pdf")


if __name__ == "__main__":
    run_scenario()
