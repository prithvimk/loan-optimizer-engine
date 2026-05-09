from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Dict
from .models import Loan

class BaseOptimizer(ABC):
    """
    Abstract base class for all debt repayment strategies.
    Defines the contract for allocating extra surplus cash to loans.
    """
    @abstractmethod
    def allocate_surplus(self, loans: List[Loan], surplus: Decimal, month_index: int) -> Dict[str, Decimal]:
        """
        Calculates how to distribute the available extra cash.
        
        Args:
            loans: List of currently active (unclosed) loans.
            surplus: Maximum available extra cash for prepayment this month.
            month_index: The current simulation month index (1-based).
            
        Returns:
            Dict mapping loan_id to the allocated prepayment Decimal amount.
        """
        pass

class AvalancheOptimizer(BaseOptimizer):
    """
    Strategy A (Debt Avalanche): 
    Allocates surplus strictly to the loan with the highest annual interest rate first.
    Mathematically guarantees the least amount of total interest paid over time.
    """
    def allocate_surplus(self, loans: List[Loan], surplus: Decimal, month_index: int) -> Dict[str, Decimal]:
        allocation = {loan.loan_id: Decimal('0') for loan in loans}
        remaining_surplus = surplus
        
        # Sort by interest rate descending
        sorted_loans = sorted(loans, key=lambda l: l.annual_interest_rate, reverse=True)
        
        for loan in sorted_loans:
            if remaining_surplus <= 0:
                break
            if not loan.allows_prepayment:
                continue
            
            # Amount we can pay is limited by the current balance
            pay_amount = min(remaining_surplus, loan.current_balance)
            if pay_amount > 0:
                allocation[loan.loan_id] += pay_amount
                remaining_surplus -= pay_amount
                
        return allocation

class SnowballOptimizer(BaseOptimizer):
    """Strategy B: Allocate to lowest balance first."""
    def allocate_surplus(self, loans: List[Loan], surplus: Decimal, month_index: int) -> Dict[str, Decimal]:
        allocation = {loan.loan_id: Decimal('0') for loan in loans}
        remaining_surplus = surplus
        
        # Sort by balance ascending
        sorted_loans = sorted(loans, key=lambda l: l.current_balance)
        
        for loan in sorted_loans:
            if remaining_surplus <= 0:
                break
            if not loan.allows_prepayment:
                continue
            
            pay_amount = min(remaining_surplus, loan.current_balance)
            if pay_amount > 0:
                allocation[loan.loan_id] += pay_amount
                remaining_surplus -= pay_amount
                
        return allocation

class ManualOptimizer(BaseOptimizer):
    """Strategy C: Manual allocation."""
    def __init__(self, manual_allocations: Dict[int, Dict[str, Decimal]]):
        self.manual_allocations = manual_allocations

    def allocate_surplus(self, loans: List[Loan], surplus: Decimal, month_index: int) -> Dict[str, Decimal]:
        allocation = {loan.loan_id: Decimal('0') for loan in loans}
        month_allocs = self.manual_allocations.get(month_index, {})
        
        remaining_surplus = surplus
        for loan in loans:
            if remaining_surplus <= 0:
                break
            if not loan.allows_prepayment:
                continue
                
            wanted_alloc = month_allocs.get(loan.loan_id, Decimal('0'))
            pay_amount = min(wanted_alloc, remaining_surplus, loan.current_balance)
            if pay_amount > 0:
                allocation[loan.loan_id] += pay_amount
                remaining_surplus -= pay_amount
                
        return allocation
