from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from calendar import monthrange

# Define standard quantizer for currency
CENTS = Decimal('.01')

def round_currency(val: Decimal) -> Decimal:
    """Rounds a decimal to two decimal places."""
    return val.quantize(CENTS, rounding=ROUND_HALF_UP)

def calculate_emi(principal: Decimal, annual_rate: Decimal, tenure_months: int) -> Decimal:
    """Calculates the standard Equated Monthly Installment."""
    if principal <= 0 or tenure_months <= 0:
        return Decimal('0.00')
    if annual_rate == Decimal('0'):
        return round_currency(principal / Decimal(tenure_months))
        
    monthly_rate = annual_rate / Decimal('12')
    factor = (Decimal('1') + monthly_rate) ** tenure_months
    emi = principal * monthly_rate * factor / (factor - Decimal('1'))
    return round_currency(emi)

def calculate_monthly_interest(balance: Decimal, annual_rate: Decimal, interest_method, current_date: date) -> Decimal:
    """
    Calculates the interest for a given month.
    If daily, uses the actual number of days in the current_date's month.
    """
    if balance <= 0 or annual_rate == Decimal('0'):
        return Decimal('0.00')
    
    if interest_method.name == 'MONTHLY':
        interest = balance * (annual_rate / Decimal('12'))
    elif interest_method.name == 'DAILY':
        days_in_month = Decimal(monthrange(current_date.year, current_date.month)[1])
        daily_rate = annual_rate / Decimal('365')
        interest = balance * daily_rate * days_in_month
    else:
        raise ValueError(f"Unknown interest method: {interest_method}")

    return round_currency(interest)
