from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Any
from copy import deepcopy

from .models import Loan, RepaymentType
from .cashflow import CashFlowProfile
from .optimizers import BaseOptimizer
from .math_utils import calculate_emi, calculate_monthly_interest, round_currency

class SimulationEngine:
    """
    The core deterministic simulation engine.
    Orchestrates the month-by-month financial projection of loan balances
    based on cash flow constraints and optimization strategies.
    """
    def __init__(self, loans: List[Loan], cashflow: CashFlowProfile, optimizer: BaseOptimizer, start_date: date):
        # We deepcopy loans so we don't mutate the user's initial state
        self.loans = deepcopy(loans)
        self.cashflow = cashflow
        self.optimizer = optimizer
        self.start_date = start_date
        
        self.current_month_index = 1
        self.current_date = start_date
        
        self.history: List[Dict[str, Any]] = []
        
        # Pre-calculate mandatory EMI for each loan based on original terms
        self.mandatory_emi: Dict[str, Decimal] = {}
        for loan in self.loans:
            if loan.repayment_type == RepaymentType.EMI:
                self.mandatory_emi[loan.loan_id] = calculate_emi(
                    loan.principal, 
                    loan.annual_interest_rate, 
                    loan.tenure_months
                )
            else:
                self.mandatory_emi[loan.loan_id] = Decimal('0')

    def run(self, max_months: int = 400):
        while any(not loan.is_closed for loan in self.loans) and self.current_month_index <= max_months:
            self._simulate_month()
            self.current_month_index += 1
            self.current_date += relativedelta(months=1)

    def _simulate_month(self):
        month_record = {
            'month_index': self.current_month_index,
            'date': self.current_date,
            'loans': {}
        }
        
        available_cash = self.cashflow.get_available_cash_for_debt(self.current_month_index)
        open_loans = [loan for loan in self.loans if not loan.is_closed]
        
        # Initialize records
        for loan in open_loans:
            month_record['loans'][loan.loan_id] = {
                'starting_balance': loan.current_balance,
                'interest': Decimal('0'),
                'mandatory_payment': Decimal('0'),
                'extra_payment': Decimal('0'),
                'principal_paid': Decimal('0'),
                'ending_balance': loan.current_balance,
                'is_closed': False,
                'rolled_over': False
            }

        # 1. Calculate Interest for all loans
        for loan in open_loans:
            interest = calculate_monthly_interest(
                loan.current_balance, 
                loan.annual_interest_rate, 
                loan.interest_method, 
                self.current_date
            )
            month_record['loans'][loan.loan_id]['interest'] = interest
            # Interest adds to balance immediately
            loan.current_balance += interest

        # 2. Process Mandatory Payments (Interest and EMIs) within cash flow
        # We prioritize EMIs, then interest-only payments.
        total_mandatory_emi = Decimal('0')
        for loan in open_loans:
            interest_due = month_record['loans'][loan.loan_id]['interest']
            target_payment = Decimal('0')
            
            if loan.repayment_type == RepaymentType.EMI:
                emi = self.mandatory_emi[loan.loan_id]
                target_payment = min(emi, loan.current_balance)
            elif loan.repayment_type == RepaymentType.INTEREST_ONLY:
                target_payment = interest_due
            elif loan.repayment_type == RepaymentType.BULLET:
                target_payment = Decimal('0')

            # Constrain by available cash
            actual_payment = min(target_payment, available_cash)
            available_cash -= actual_payment
            total_mandatory_emi += actual_payment
            
            loan.current_balance -= actual_payment
            loan.current_balance = round_currency(loan.current_balance)
            
            interest_paid = min(actual_payment, interest_due)
            principal_paid = actual_payment - interest_paid
            
            month_record['loans'][loan.loan_id]['mandatory_payment'] += actual_payment
            month_record['loans'][loan.loan_id]['principal_paid'] += principal_paid

        # 3. Process Term-End Principal Repayments (Bullet / Interest-Only)
        for loan in open_loans:
            if loan.repayment_type in (RepaymentType.INTEREST_ONLY, RepaymentType.BULLET):
                if self.current_month_index >= loan.tenure_months:
                    # Principal is due
                    principal_due = loan.current_balance
                    actual_payment = min(principal_due, available_cash)
                    
                    if actual_payment > Decimal('0'):
                        available_cash -= actual_payment
                        loan.current_balance -= actual_payment
                        loan.current_balance = round_currency(loan.current_balance)
                        
                        month_record['loans'][loan.loan_id]['mandatory_payment'] += actual_payment
                        month_record['loans'][loan.loan_id]['principal_paid'] += actual_payment
                        total_mandatory_emi += actual_payment
                    
                    # Rollover logic: If not fully paid off, roll it over for another 12 months
                    if loan.current_balance > Decimal('0'):
                        loan.tenure_months += 12
                        month_record['loans'][loan.loan_id]['rolled_over'] = True

        # 4. Determine Surplus
        surplus = available_cash
        month_record['surplus_available'] = surplus

        # 5. Allocate Surplus
        allocations = self.optimizer.allocate_surplus(open_loans, surplus, self.current_month_index)
        
        # 6. Apply Extra Payments & Update Balances
        for loan in open_loans:
            extra_payment = allocations.get(loan.loan_id, Decimal('0'))
            
            if extra_payment > Decimal('0'):
                extra_payment = min(extra_payment, loan.current_balance)
                loan.current_balance -= extra_payment
                loan.current_balance = round_currency(loan.current_balance)
                
                month_record['loans'][loan.loan_id]['extra_payment'] = extra_payment
                month_record['loans'][loan.loan_id]['principal_paid'] += extra_payment

            # 7. Close loans
            if loan.current_balance <= Decimal('0'):
                loan.current_balance = Decimal('0')
                loan.is_closed = True
                
            # Finalize month record
            month_record['loans'][loan.loan_id]['ending_balance'] = loan.current_balance
            month_record['loans'][loan.loan_id]['is_closed'] = loan.is_closed
            
        self.history.append(month_record)
