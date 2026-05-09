# Loan Optimization Engine 🚀

A highly deterministic, precision-based Python simulation engine designed to help you crush debt by visualizing your financial timeline and systematically allocating surplus cash flow to optimize loan payoffs. 

It generates beautiful, interactive HTML reports with detailed month-by-month amortization schedules, allowing you to instantly see exactly how much money and time you'll save using optimization strategies like the Debt Avalanche method.

## Features
- **Penny-Perfect Precision**: Built entirely using Python's `decimal` library to prevent floating-point errors.
- **Realistic Cash Flow Limits**: The engine strictly bounds optimization efforts by your actual wallet (income minus expenses).
- **Rollover Mechanics**: Correctly handles short-term renewable lines of credit (like Indian Gold or Crop Loans) by rolling over principal if cash flow constraints prevent a bullet payment.
- **Dynamic Cash Flow Tracking**: Supports mapping exact dates for one-off bonuses (`irregular_inflows`) or annual expenses (`irregular_outflows`).
- **Professional Interactive Reports**: Outputs an HTML dashboard with a consolidated Master Amortization Schedule grouped by month.

## Installation

This project uses `uv` for lightning-fast dependency management.

```bash
# Clone the repository
git clone https://github.com/yourusername/loan-optimizer.git
cd loan-optimizer

# Sync dependencies using uv
uv sync
```

## Quick Start

1. Copy the example configuration to create your own:
   ```bash
   cp example_config.yaml config.yaml
   ```
2. Edit `config.yaml` with your actual income, expenses, and loans.
3. Run the engine!
   ```bash
   uv run main.py
   ```

A fresh `report.html` file will be generated in your project directory. Open it in any web browser to view your optimized amortization schedule!

## Supported Loan Types

- **`EMI`**: Standard Equated Monthly Installment loans (e.g., Home Loans, Car Loans).
- **`INTEREST_ONLY`**: Pay only the interest every month, with the principal due at the end of the `tenure_months` (e.g., Gold Loans). If your cash flow can't cover the principal, it rolls over automatically for another term.
- **`BULLET`**: No payments until the end of the `tenure_months`, where Principal + Interest is demanded.

## Strategies

By default, the engine uses the **Avalanche Optimizer** (Highest Interest Rate priority). It also runs a hidden Baseline simulation (No Prepayments) to calculate your exact Total Interest Saved and Months Saved!

## Disclaimer
*This engine is provided for informational and educational purposes only. It is not professional financial advice.*
