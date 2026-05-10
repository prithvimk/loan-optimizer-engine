"""
Entry point for the Loan Optimization Engine.
Loads the YAML configuration, runs both baseline and optimized simulations,
and generates the final HTML and CSV reports.
"""

import yaml
from decimal import Decimal
from datetime import datetime, date
from loan_optimizer.models import Loan, InterestMethod, RepaymentType
from loan_optimizer.cashflow import CashFlowProfile
from loan_optimizer.optimizers import AvalancheOptimizer, ManualOptimizer
from loan_optimizer.engine import SimulationEngine
from loan_optimizer.reporter import Reporter


def load_config(filepath: str):
    with open(filepath, "r") as f:
        data = yaml.safe_load(f)

    cashflow_data = data.get("cashflow", {})
    sim_start_date = date(2026, 1, 1)

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

    return loans, cashflow


def run_scenario():
    print("Loading configuration from config.yaml...")
    loans, cashflow = load_config("config.yaml")

    print("Running Baseline Simulation (No Prepayments)...")
    baseline_optimizer = ManualOptimizer({})
    baseline_engine = SimulationEngine(
        loans=loans,
        cashflow=cashflow,
        optimizer=baseline_optimizer,
        start_date=date(2026, 1, 1),
    )
    baseline_engine.run()

    print("Running Optimized Simulation (Avalanche Strategy)...")
    optimizer = AvalancheOptimizer()
    engine = SimulationEngine(
        loans=loans, cashflow=cashflow, optimizer=optimizer, start_date=date(2026, 1, 1)
    )
    engine.run()

    # Reporting
    reporter = Reporter(engine.history, baseline_engine.history, cashflow, loans)
    df = reporter.to_dataframe(engine.history)

    print("\nSimulation complete. Generating report...")
    df.to_csv("output_history.csv", index=False)
    reporter.generate_html_report("report.html")

    print(f"Total months simulated (Optimized): {df['month_index'].max()}")
    print("Reports generated: output_history.csv and report.html")


if __name__ == "__main__":
    run_scenario()
