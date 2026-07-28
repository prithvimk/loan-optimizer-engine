import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from loan_optimizer.models import Loan

REQUIRED_COLUMNS = {"loan_id", "date", "amount"}


def load_payment_history(csv_filepath: str | Path, loans: list[Loan]) -> None:
    """
    Ingests payment history from a CSV file.
    Expects columns: loan_id, date, amount
    """
    loans_by_id = {loan.loan_id: loan for loan in loans}
    with open(csv_filepath, mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError("payments.csv must contain columns: loan_id,date,amount")

        for row_number, row in enumerate(reader, start=2):
            try:
                loan_id = row["loan_id"].strip()
                payment_date = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
                amount = Decimal(row["amount"].strip())
            except (AttributeError, ValueError, ArithmeticError) as exc:
                raise ValueError(
                    f"Invalid payments.csv row {row_number}: expected loan_id, YYYY-MM-DD date, and amount"
                ) from exc

            if loan_id not in loans_by_id:
                raise ValueError(f"Invalid payments.csv row {row_number}: unknown loan_id {loan_id!r}")
            if not amount.is_finite() or amount <= Decimal("0"):
                raise ValueError(f"Invalid payments.csv row {row_number}: amount must be positive")

            loan = loans_by_id[loan_id]
            if (payment_date.year, payment_date.month) < (loan.start_date.year, loan.start_date.month):
                raise ValueError(
                    f"Invalid payments.csv row {row_number}: payment predates loan {loan_id!r}"
                )
            key = (payment_date.year, payment_date.month)
            loan.payment_history[key] = loan.payment_history.get(key, Decimal("0")) + amount
