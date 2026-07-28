from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List

from dateutil.relativedelta import relativedelta

from .cashflow import CashFlowProfile
from .math_utils import calculate_emi, calculate_monthly_interest, round_currency
from .models import Loan, RepaymentType
from .optimizers import BaseOptimizer


class SimulationEngine:
    """Run independent projected and actual loan ledgers month by month."""

    def __init__(
        self,
        loans: List[Loan],
        cashflow: CashFlowProfile,
        optimizer: BaseOptimizer,
        start_date: date,
        as_of_date: date | None = None,
    ):
        self.loans = deepcopy(loans)  # projected ledger
        self.actual_loans = deepcopy(loans)
        self.cashflow = cashflow
        self.optimizer = optimizer
        self.start_date = start_date
        self.as_of_date = as_of_date or date.today()
        self.current_month_index = 1
        self.current_date = start_date
        self.history: List[Dict[str, Any]] = []
        self.actual_accumulated_pending = {
            loan.loan_id: Decimal("0") for loan in self.actual_loans
        }
        self.mandatory_emi = {
            loan.loan_id: (
                calculate_emi(loan.principal, loan.annual_interest_rate, loan.tenure_months)
                if loan.repayment_type == RepaymentType.EMI
                else Decimal("0")
            )
            for loan in self.loans
        }

    def run(self, max_months: int = 400):
        while self.current_month_index <= max_months and self._has_remaining_work():
            self._simulate_month()
            self.current_month_index += 1
            self.current_date += relativedelta(months=1)

    def _has_remaining_work(self) -> bool:
        projected_open = any(not loan.is_closed for loan in self.loans)
        actual_open = (
            self._is_actual_month()
            and any(not loan.is_closed for loan in self.actual_loans)
        )
        return projected_open or actual_open

    def _is_actual_month(self) -> bool:
        return (self.current_date.year, self.current_date.month) <= (
            self.as_of_date.year,
            self.as_of_date.month,
        )

    def _active_loans(self, loans: List[Loan]) -> List[Loan]:
        return [
            loan
            for loan in loans
            if not loan.is_closed and loan.start_date <= self.current_date
        ]

    def _loan_month_index(self, loan: Loan) -> int:
        return (
            (self.current_date.year - loan.start_date.year) * 12
            + self.current_date.month
            - loan.start_date.month
            + 1
        )

    def _required_payment(self, loan: Loan, interest: Decimal) -> Decimal:
        if loan.repayment_type == RepaymentType.EMI:
            required = min(self.mandatory_emi[loan.loan_id], loan.current_balance)
        elif loan.repayment_type == RepaymentType.INTEREST_ONLY:
            required = interest
        else:
            required = Decimal("0")

        if (
            loan.repayment_type in (RepaymentType.INTEREST_ONLY, RepaymentType.BULLET)
            and self._loan_month_index(loan) >= loan.tenure_months
        ):
            return loan.current_balance
        return required

    def _roll_over_if_needed(self, loan: Loan) -> bool:
        if (
            loan.repayment_type in (RepaymentType.INTEREST_ONLY, RepaymentType.BULLET)
            and self._loan_month_index(loan) >= loan.tenure_months
            and loan.current_balance > Decimal("0")
        ):
            loan.tenure_months += 12
            return True
        return False

    @staticmethod
    def _close_if_paid(loan: Loan) -> None:
        if loan.current_balance <= Decimal("0"):
            loan.current_balance = Decimal("0")
            loan.is_closed = True

    @staticmethod
    def _empty_actual_fields() -> Dict[str, Any]:
        return {
            "actual_starting_balance": None,
            "actual_interest": None,
            "actual_required_payment": None,
            "actual_payment": None,
            "actual_pending_payment": None,
            "actual_accumulated_pending_payment": None,
            "actual_ending_balance": None,
        }

    def _simulate_actual_ledger(self, records: Dict[str, Dict[str, Any]]) -> None:
        if not self._is_actual_month():
            return

        monthly_key = (self.current_date.year, self.current_date.month)
        for loan in self._active_loans(self.actual_loans):
            record = records.setdefault(loan.loan_id, self._empty_projected_fields())
            record["actual_starting_balance"] = loan.current_balance
            interest = calculate_monthly_interest(
                loan.current_balance,
                loan.annual_interest_rate,
                loan.interest_method,
                self.current_date,
            )
            loan.current_balance += interest
            required = self._required_payment(loan, interest)
            recorded_payment = loan.payment_history.get(monthly_key, Decimal("0"))
            actual_payment = min(recorded_payment, loan.current_balance)
            loan.current_balance = round_currency(loan.current_balance - actual_payment)

            payment_delta = required - actual_payment
            pending = max(Decimal("0"), payment_delta)
            accumulated = max(
                Decimal("0"),
                self.actual_accumulated_pending[loan.loan_id] + payment_delta,
            )
            self.actual_accumulated_pending[loan.loan_id] = round_currency(accumulated)
            self._roll_over_if_needed(loan)
            self._close_if_paid(loan)

            record.update(
                {
                    "actual_starting_balance": record["actual_starting_balance"],
                    "actual_interest": interest,
                    "actual_required_payment": required,
                    "actual_payment": actual_payment,
                    "actual_pending_payment": pending,
                    "actual_accumulated_pending_payment": self.actual_accumulated_pending[
                        loan.loan_id
                    ],
                    "actual_ending_balance": loan.current_balance,
                }
            )

    @staticmethod
    def _empty_projected_fields() -> Dict[str, Any]:
        return {
            "projected_starting_balance": None,
            "projected_interest": None,
            "projected_required_payment": None,
            "projected_mandatory_payment": None,
            "projected_extra_payment": None,
            "projected_principal_paid": None,
            "projected_ending_balance": None,
            "projected_is_closed": None,
            "projected_rolled_over": None,
            **SimulationEngine._empty_actual_fields(),
        }

    def _simulate_projected_ledger(self, records: Dict[str, Dict[str, Any]]) -> Decimal:
        available_cash = self.cashflow.get_available_cash_for_debt(self.current_month_index)
        monthly_key = (self.current_date.year, self.current_date.month)
        projected_loans = self._active_loans(self.loans)
        requirements: Dict[str, Decimal] = {}
        recorded_loans = set()

        for loan in projected_loans:
            record = records.setdefault(loan.loan_id, self._empty_projected_fields())
            record["projected_starting_balance"] = loan.current_balance
            interest = calculate_monthly_interest(
                loan.current_balance,
                loan.annual_interest_rate,
                loan.interest_method,
                self.current_date,
            )
            loan.current_balance += interest
            required = self._required_payment(loan, interest)
            requirements[loan.loan_id] = required
            record.update(
                {
                    "projected_interest": interest,
                    "projected_required_payment": required,
                    "projected_mandatory_payment": Decimal("0"),
                    "projected_extra_payment": Decimal("0"),
                    "projected_principal_paid": Decimal("0"),
                }
            )

        for loan in projected_loans:
            recorded_payment = loan.payment_history.get(monthly_key)
            if recorded_payment is None:
                continue
            payment = min(recorded_payment, loan.current_balance)
            loan.current_balance = round_currency(loan.current_balance - payment)
            available_cash = max(Decimal("0"), available_cash - payment)
            interest_paid = min(payment, records[loan.loan_id]["projected_interest"])
            records[loan.loan_id]["projected_principal_paid"] = payment - interest_paid
            recorded_loans.add(loan.loan_id)

        for loan in projected_loans:
            if loan.loan_id in recorded_loans:
                continue
            payment = min(requirements[loan.loan_id], available_cash, loan.current_balance)
            available_cash -= payment
            loan.current_balance = round_currency(loan.current_balance - payment)
            interest_paid = min(payment, records[loan.loan_id]["projected_interest"])
            records[loan.loan_id]["projected_mandatory_payment"] = payment
            records[loan.loan_id]["projected_principal_paid"] = payment - interest_paid

        for loan in projected_loans:
            records[loan.loan_id]["projected_rolled_over"] = self._roll_over_if_needed(loan)

        allocations = self.optimizer.allocate_surplus(
            [loan for loan in projected_loans if loan.loan_id not in recorded_loans],
            available_cash,
            self.current_month_index,
        )
        for loan in projected_loans:
            extra_payment = min(
                allocations.get(loan.loan_id, Decimal("0")), loan.current_balance
            )
            if extra_payment > Decimal("0"):
                loan.current_balance = round_currency(loan.current_balance - extra_payment)
                records[loan.loan_id]["projected_extra_payment"] = extra_payment
                records[loan.loan_id]["projected_principal_paid"] += extra_payment
            self._close_if_paid(loan)
            records[loan.loan_id]["projected_ending_balance"] = loan.current_balance
            records[loan.loan_id]["projected_is_closed"] = loan.is_closed
        return available_cash

    def _simulate_month(self):
        records: Dict[str, Dict[str, Any]] = {}
        surplus = self._simulate_projected_ledger(records)
        self._simulate_actual_ledger(records)
        self.history.append(
            {
                "month_index": self.current_month_index,
                "date": self.current_date,
                "surplus_available": surplus,
                "loans": records,
            }
        )
