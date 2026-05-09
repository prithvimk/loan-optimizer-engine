from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict
from .math_utils import round_currency

@dataclass
class CashFlowProfile:
    """
    Tracks the user's overall financial capacity.
    Accounts for inflation, income growth, and irregular one-off inflows (like bonuses)
    to strictly bound the maximum available cash for debt service each month.
    """
    monthly_income: Decimal
    fixed_living_expenses: Decimal
    emergency_buffer: Decimal = Decimal('0')
    income_growth_rate_annual: Decimal = Decimal('0')
    expense_inflation_rate_annual: Decimal = Decimal('0')
    irregular_inflows: Dict[int, Decimal] = field(default_factory=dict) # month_index -> amount
    irregular_outflows: Dict[int, Decimal] = field(default_factory=dict) # month_index -> amount

    def get_available_cash_for_debt(self, month_index: int) -> Decimal:
        """
        Calculate maximum available cash for debt service for a specific month.
        """
        years_elapsed = (month_index - 1) // 12
        
        current_income = self.monthly_income * ((Decimal('1') + self.income_growth_rate_annual) ** years_elapsed)
        current_expenses = self.fixed_living_expenses * ((Decimal('1') + self.expense_inflation_rate_annual) ** years_elapsed)
        
        current_income = round_currency(current_income)
        current_expenses = round_currency(current_expenses)
        
        inflow = self.irregular_inflows.get(month_index, Decimal('0'))
        outflow = self.irregular_outflows.get(month_index, Decimal('0'))
        
        total_in = current_income + inflow
        total_out = current_expenses + outflow + self.emergency_buffer
        
        return max(Decimal('0'), total_in - total_out)

    def get_surplus(self, month_index: int, total_mandatory_emi: Decimal) -> Decimal:
        """
        Calculate available surplus for a specific month index (1-based).
        """
        available_cash = self.get_available_cash_for_debt(month_index)
        surplus = available_cash - total_mandatory_emi
        return max(Decimal('0'), surplus)
