from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from datetime import date


class InterestMethod(Enum):
    """Defines how interest is compounded/calculated."""

    MONTHLY = auto()
    DAILY = auto()


class RepaymentType(Enum):
    """Defines the repayment structure of the loan."""

    EMI = auto()  # Equated Monthly Installment
    INTEREST_ONLY = auto()  # Pay interest monthly, principal due at end of tenure
    BULLET = auto()  # No payments until end of tenure, then Principal + Interest


@dataclass
class Loan:
    """
    Core data structure representing a single debt instrument.

    Attributes:
        loan_id: Unique string identifier for the loan
        principal: Initial loan amount
        annual_interest_rate: The annual percentage rate (e.g., 0.085 for 8.5%)
        interest_method: Strategy for calculating interest accrual
        repayment_type: Structure of mandatory monthly payments
        tenure_months: Contractual length of the loan in months
        start_date: Origination date of the loan
        allows_prepayment: Whether the optimizer is allowed to allocate surplus to this loan
    """

    loan_id: str
    principal: Decimal
    annual_interest_rate: Decimal
    interest_method: InterestMethod
    repayment_type: RepaymentType
    tenure_months: int
    start_date: date
    allows_prepayment: bool = True
    current_balance: Decimal = field(init=False)
    is_closed: bool = field(default=False, init=False)

    def __post_init__(self):
        self.current_balance = self.principal
