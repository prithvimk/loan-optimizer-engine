import pandas as pd
from typing import List, Dict, Any
from jinja2 import Environment, select_autoescape
import json
import io

from decimal import Decimal

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


def format_inr(value):
    if value is None or pd.isna(value):
        return "—"
    try:
        val = float(value)
    except:
        return value
    num_str = f"{val:.2f}"
    integer_part, decimal_part = num_str.split(".")
    if integer_part.startswith("-"):
        is_negative = True
        integer_part = integer_part[1:]
    else:
        is_negative = False

    if len(integer_part) > 3:
        last_three = integer_part[-3:]
        other_digits = integer_part[:-3]

        parts = []
        while len(other_digits) > 2:
            parts.insert(0, other_digits[-2:])
            other_digits = other_digits[:-2]
        if other_digits:
            parts.insert(0, other_digits)

        integer_part = ",".join(parts) + "," + last_three

    res = f"₹{integer_part}.{decimal_part}"
    if is_negative:
        res = "-" + res
    return res


class Reporter:
    """
    Consolidates the output of baseline and optimized simulations into
    pandas DataFrames and generates the final interactive HTML report.
    """

    def __init__(
        self,
        optimized_history: List[Dict[str, Any]],
        baseline_history: List[Dict[str, Any]],
        cashflow,
        loans,
    ):
        self.optimized_history = optimized_history
        self.baseline_history = baseline_history
        self.cashflow = cashflow
        self.loans = {loan.loan_id: loan for loan in loans}

    def to_dataframe(self, history: List[Dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for month_data in history:
            base_row = {
                "month_index": month_data["month_index"],
                "date": month_data["date"],
                "surplus_available": float(month_data["surplus_available"]),
            }
            for loan_id, loan_data in month_data["loans"].items():
                row = base_row.copy()
                row["loan_id"] = loan_id
                for field, value in loan_data.items():
                    row[field] = float(value) if isinstance(value, Decimal) else value
                rows.append(row)
        return pd.DataFrame(rows)

    def _generate_payoff_chart_svg(self, opt_df: pd.DataFrame) -> str:
        """
        Generates the Loan Payoff chart as an inline SVG string
        using matplotlib, for vector-quality rendering in PDF.
        """
        months = sorted(opt_df["month_index"].unique())
        colors = [
            "#3498db", "#e74c3c", "#2ecc71", "#f1c40f",
            "#9b59b6", "#34495e", "#e67e22", "#1abc9c",
        ]

        fig, ax = plt.subplots(figsize=(10, 4.5))

        for idx, loan_id in enumerate(self.loans.keys()):
            loan_data = opt_df[opt_df["loan_id"] == loan_id].sort_values("month_index")
            balances = []
            for m in months:
                row = loan_data[loan_data["month_index"] == m]
                value = row["projected_ending_balance"].iloc[0] if not row.empty else None
                balances.append(float(value) if value is not None and not pd.isna(value) else 0)
            color = colors[idx % len(colors)]
            ax.fill_between(months, balances, alpha=0.25, color=color)
            ax.plot(months, balances, label=loan_id, color=color, linewidth=1.5)

        ax.set_xlabel("Month")
        ax.set_ylabel("Outstanding Balance (\u20b9)")
        ax.set_title("Loan Payoff Over Time")
        ax.legend(loc="upper right", fontsize=8)
        ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"\u20b9{x:,.0f}")
        )
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        # Export to SVG string
        buf = io.StringIO()
        fig.savefig(buf, format="svg")
        plt.close(fig)
        return buf.getvalue()

    def generate_pdf_report(self, html_path: str, pdf_path: str):
        """
        Opens the HTML report in headless Chromium via Playwright
        and prints to PDF with the @media print styles applied.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            # Load the fully self-contained HTML file
            page.goto(f"file:///{html_path}", wait_until="networkidle")

            # Force all tab-content visible (belt-and-suspenders with CSS)
            page.evaluate("""
                document.querySelectorAll('.tab-content').forEach(el => {
                    el.style.display = 'block';
                    el.style.animation = 'none';
                    el.style.opacity = '1';
                });
                const tabs = document.querySelector('.tabs');
                if (tabs) tabs.remove();
            """)

            # Wait deterministically for full render before printing:
            # 1. All tab-content sections are visible with laid-out content
            # 2. The SVG chart element is present in the DOM
            # 3. All fonts are loaded (affects text metrics / layout)
            page.wait_for_function("""
                () => {
                    const sections = document.querySelectorAll('.tab-content');
                    if (sections.length === 0) return false;
                    const allVisible = [...sections].every(
                        el => el.offsetHeight > 0
                    );
                    const svgReady = document.querySelector('svg') !== null;
                    return allVisible && svgReady;
                }
            """, timeout=10000)
            page.evaluate("() => document.fonts.ready")

            page.pdf(
                path=pdf_path,
                format="A4",
                landscape=False,
                print_background=True,
                margin={
                    "top": "15mm",
                    "bottom": "15mm",
                    "left": "10mm",
                    "right": "10mm",
                },
            )
            browser.close()
        print(f"PDF report saved to {pdf_path}")

    def generate_html_report(self, output_path: str):
        opt_df = self.to_dataframe(self.optimized_history)
        base_df = self.to_dataframe(self.baseline_history)

        # Overall Summary
        opt_total_int = opt_df["projected_interest"].sum()
        base_total_int = base_df["projected_interest"].sum()
        interest_saved = base_total_int - opt_total_int

        opt_months = opt_df["month_index"].max()
        base_months = base_df["month_index"].max()
        months_saved = base_months - opt_months

        debt_free_date = opt_df["date"].max()

        summary_stats = {
            "total_interest": format_inr(opt_total_int),
            "interest_saved": format_inr(interest_saved),
            "total_months": int(opt_months) if not pd.isna(opt_months) else 0,
            "months_saved": int(months_saved) if not pd.isna(months_saved) else 0,
            "debt_free_date": (
                debt_free_date.strftime("%Y-%m-%d")
                if not pd.isna(debt_free_date)
                else "N/A"
            ),
        }

        # First month allocation details
        m1_df = opt_df[opt_df["month_index"] == 1]
        base_income = float(self.cashflow.monthly_income)
        base_expenses = float(self.cashflow.fixed_living_expenses)

        total_mandatory = m1_df["projected_mandatory_payment"].sum()
        total_extra = m1_df["projected_extra_payment"].sum()

        allocations = []
        allocations.append(
            {
                "category": "Fixed Living Expenses",
                "amount": format_inr(base_expenses),
                "percentage": (
                    f"{(base_expenses / base_income * 100):.1f}%"
                    if base_income
                    else "0%"
                ),
            }
        )

        for _, row in m1_df.iterrows():
            total_pay = row["projected_mandatory_payment"] + row["projected_extra_payment"]
            allocations.append(
                {
                    "category": f"Loan: {row['loan_id']}",
                    "amount": format_inr(total_pay),
                    "percentage": (
                        f"{(total_pay / base_income * 100):.1f}%"
                        if base_income
                        else "0%"
                    ),
                }
            )

        remaining = base_income - base_expenses - total_mandatory - total_extra
        allocations.append(
            {
                "category": "Unallocated / Retained",
                "amount": format_inr(remaining),
                "percentage": (
                    f"{(remaining / base_income * 100):.1f}%" if base_income else "0%"
                ),
            }
        )

        # Loan level summary
        opt_loan_grp = opt_df.groupby("loan_id").agg(
            {
                "projected_interest": "sum",
                "projected_mandatory_payment": "sum",
                "projected_extra_payment": "sum",
                "month_index": "max",
            }
        )
        base_loan_grp = base_df.groupby("loan_id").agg(
            {"projected_interest": "sum", "month_index": "max"}
        )

        loans_data = []
        for loan_id, opt_row in opt_loan_grp.iterrows():
            base_row = base_loan_grp.loc[loan_id]
            int_saved = base_row["projected_interest"] - opt_row["projected_interest"]
            m_saved = base_row["month_index"] - opt_row["month_index"]
            rollovers = opt_df[
                (opt_df["loan_id"] == loan_id) & (opt_df["projected_rolled_over"] == True)
            ].shape[0]

            closure_m = int(opt_row["month_index"])
            closure_str = f"{closure_m} ({closure_m/12:.1f} years)"

            loans_data.append(
                {
                    "loan_id": loan_id,
                    "principal": format_inr(self.loans[loan_id].principal),
                    "total_interest": format_inr(opt_row["projected_interest"]),
                    "interest_saved": format_inr(int_saved),
                    "total_payments": format_inr(
                        opt_row["projected_mandatory_payment"] + opt_row["projected_extra_payment"]
                    ),
                    "closure_month": closure_str,
                    "months_saved": int(m_saved),
                    "rollovers": int(rollovers),
                }
            )

        # Generate master amortization schedule (grouped by month)
        opt_df_sorted = opt_df.sort_values(by=["month_index", "loan_id"])
        master_schedule = []

        for (m_idx, m_date), group in opt_df_sorted.groupby(["month_index", "date"]):
            month_str = m_date.strftime("%B %Y")
            loans_list = []
            for _, row in group.iterrows():
                loans_list.append(
                    {
                        "loan_id": row["loan_id"],
                        "projected_start": format_inr(row["projected_starting_balance"]),
                        "projected_interest": format_inr(row["projected_interest"]),
                        "projected_required": format_inr(row["projected_required_payment"]),
                        "projected_mandatory": format_inr(row["projected_mandatory_payment"]),
                        "projected_extra": format_inr(row["projected_extra_payment"]),
                        "projected_principal": format_inr(row["projected_principal_paid"]),
                        "projected_end": format_inr(row["projected_ending_balance"]),
                        "projected_closed": "Yes" if row.get("projected_is_closed", False) else "",
                        "projected_rolled_over": "Yes" if row.get("projected_rolled_over", False) else "",
                        "actual_start": format_inr(row["actual_starting_balance"]),
                        "actual_interest": format_inr(row["actual_interest"]),
                        "actual_required": format_inr(row["actual_required_payment"]),
                        "actual_payment": format_inr(row["actual_payment"]),
                        "actual_pending": format_inr(row["actual_pending_payment"]),
                        "actual_accumulated_pending": format_inr(row["actual_accumulated_pending_payment"]),
                        "actual_end": format_inr(row["actual_ending_balance"]),
                    }
                )
            master_schedule.append(
                {
                    "month_index": int(m_idx),
                    "month_str": f"Month {int(m_idx)} &bull; {month_str}",
                    "loans": loans_list,
                }
            )

        # Generate vector SVG chart
        chart_svg = self._generate_payoff_chart_svg(opt_df)

        template_str = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Detailed Loan Optimization Report</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }
                .container { max-width: 1100px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
                h2 { color: #2980b9; margin-top: 30px; border-bottom: 1px solid #eee; padding-bottom: 5px;}
                
                /* Tabs */
                .tabs { display: flex; overflow-x: auto; border-bottom: 2px solid #ecf0f1; margin-bottom: 20px; }
                .tab-button { background: none; border: none; padding: 12px 20px; font-size: 15px; cursor: pointer; color: #7f8c8d; border-bottom: 2px solid transparent; transition: all 0.3s ease; white-space: nowrap; }
                .tab-button:hover { color: #2c3e50; background: #f9fbfc; }
                .tab-button.active { color: #3498db; border-bottom-color: #3498db; font-weight: bold; }
                .tab-content { display: none; animation: fadeEffect 0.3s; }
                @keyframes fadeEffect { from {opacity: 0;} to {opacity: 1;} }
                .tab-content.active { display: block; }
                
                .summary-cards { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 30px; }
                .card { background: #ecf0f1; padding: 20px; border-radius: 8px; flex: 1; min-width: 150px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
                .card.highlight { background: #d4efdf; border: 1px solid #27ae60; }
                .card h3 { margin: 0 0 10px 0; font-size: 13px; color: #7f8c8d; text-transform: uppercase; }
                .card.highlight h3 { color: #27ae60; }
                .card p { margin: 0; font-size: 22px; font-weight: bold; color: #2c3e50; }
                table { width: 100%; border-collapse: collapse; margin-top: 15px; }
                th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; font-size: 14px;}
                th { background-color: #34495e; color: #fff; text-transform: uppercase; font-size: 13px; }
                tr:hover { background-color: #f5f5f5; }
                .positive { color: #27ae60; font-weight: bold; }
                .warning { color: #e67e22; font-weight: bold; }
                .month-group { margin-bottom: 30px; background: #fff; border-radius: 8px; border: 1px solid #e1e8ed; overflow: visible; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
                .month-header { background-color: #34495e; color: #fff; padding: 12px 20px; font-weight: bold; font-size: 15px; }
                .table-scroll { overflow-x: auto; border-radius: 0 0 8px 8px; }
                .month-group table { min-width: 2050px; margin-top: 0; border: none; box-shadow: none; }
                .month-group th { background-color: #f8fafc; color: #7f8c8d; border-bottom: 2px solid #e1e8ed; font-size: 12px; }
                .month-group td, .month-group th { padding: 10px 20px; }
                .footer { margin-top: 40px; text-align: center; font-size: 12px; color: #bdc3c7; }

                /* ---------- Print / PDF layout ---------- */
                @media print {
                    @page {
                        size: A4 portrait;
                        margin: 15mm 10mm;
                    }

                    /* Show all content linearly — hide tab nav, kill fade animation */
                    .tabs            { display: none !important; }
                    .tab-content     { display: block !important; animation: none !important; opacity: 1 !important; }

                    /* Page-break hygiene */
                    .summary-cards   { break-inside: avoid; }
                    .card            { break-inside: avoid; }
                    table            { break-inside: auto; }
                    tr               { break-inside: avoid; }
                    thead            { display: table-header-group; }
                    .month-group     { break-inside: avoid; }
                    .month-group table tr { break-inside: avoid; }
                    .table-scroll    { overflow: visible; }
                    .month-group table { min-width: 0; }

                    /* Chart container */
                    .chart-container { break-inside: avoid; }

                    /* Portrait-friendly: shrink table text to fit 8 columns */
                    .month-group td, .month-group th { padding: 6px 8px; font-size: 11px; }
                    th, td { padding: 8px 10px; font-size: 12px; }

                    /* Clean print appearance */
                    .container       { box-shadow: none; padding: 0; }
                    .month-group     { box-shadow: none; }
                    body             { background: #fff; padding: 10px; }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Loan Optimization Report</h1>
                
                <div class="tabs">
                    <button class="tab-button active" onclick="openTab(event, 'Summary')">Portfolio Summary</button>
                    <button class="tab-button" onclick="openTab(event, 'MasterSchedule')">Master Schedule</button>
                </div>
                
                <!-- SUMMARY TAB -->
                <div id="Summary" class="tab-content active">
                    <h2>Portfolio Summary</h2>
                    <div class="summary-cards">
                        <div class="card">
                            <h3>Total Interest Paid</h3>
                            <p>{{ summary.total_interest }}</p>
                        </div>
                        <div class="card highlight">
                            <h3>Total Interest Saved</h3>
                            <p class="positive">{{ summary.interest_saved }}</p>
                        </div>
                        <div class="card">
                            <h3>Debt-Free Date</h3>
                            <p>{{ summary.debt_free_date }}</p>
                        </div>
                        <div class="card">
                            <h3>Months to Payoff</h3>
                            <p>{{ summary.total_months }}</p>
                        </div>
                        <div class="card highlight">
                            <h3>Months Saved</h3>
                            <p class="positive">{{ summary.months_saved }}</p>
                        </div>
                    </div>

                    <h2>Loan Payoff Graph</h2>
                    <div class="chart-container" style="width:100%; margin-bottom: 30px; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); border: 1px solid #e1e8ed; box-sizing: border-box;">
                        {{ chart_svg|safe }}
                    </div>

                    <h2>Month 1: Income Allocation Breakdown</h2>
                    <p style="font-size: 14px; color: #555;">Based on your starting monthly income of {{ base_income }}. Payments are strictly bound by available cash.</p>
                    <table>
                        <thead>
                            <tr>
                                <th>Category</th>
                                <th>Amount Allocated</th>
                                <th>% of Monthly Income</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for item in allocations %}
                            <tr>
                                <td>{{ item.category }}</td>
                                <td>{{ item.amount }}</td>
                                <td>{{ item.percentage }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>

                    <h2>Detailed Loan Breakdown</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>Loan ID</th>
                                <th>Principal</th>
                                <th>Interest Paid</th>
                                <th>Interest Saved</th>
                                <th>Total Payments</th>
                                <th>Closure Month</th>
                                <th>Rollovers</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for loan in loans %}
                            <tr>
                                <td><strong>{{ loan.loan_id }}</strong></td>
                                <td>{{ loan.principal }}</td>
                                <td>{{ loan.total_interest }}</td>
                                <td class="positive">{{ loan.interest_saved }}</td>
                                <td>{{ loan.total_payments }}</td>
                                <td>{{ loan.closure_month }}</td>
                                {% if loan.rollovers > 0 %}
                                <td class="warning">{{ loan.rollovers }}</td>
                                {% else %}
                                <td>0</td>
                                {% endif %}
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <!-- MASTER SCHEDULE TAB -->
                <div id="MasterSchedule" class="tab-content">
                    <h2>Master Amortization Schedule</h2>
                    {% for month_group in master_schedule %}
                    <div class="month-group">
                        <div class="month-header">{{ month_group.month_str|safe }}</div>
                        <div class="table-scroll">
                        <table>
                            <thead>
                                <tr>
                                    <th>Loan ID</th>
                                    <th>Projected Start</th>
                                    <th>Projected Interest</th>
                                    <th>Projected Required</th>
                                    <th>Projected Mandatory</th>
                                    <th>Projected Extra</th>
                                    <th>Projected Principal</th>
                                    <th>Projected End</th>
                                    <th>Projected Closed</th>
                                    <th>Projected Rollover</th>
                                    <th>Actual Start</th>
                                    <th>Actual Interest</th>
                                    <th>Actual Required</th>
                                    <th>Actual Payment</th>
                                    <th>Actual Pending</th>
                                    <th>Actual Accumulated Pending</th>
                                    <th>Actual End</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for row in month_group.loans %}
                                <tr>
                                    <td><strong>{{ row.loan_id }}</strong></td>
                                    <td>{{ row.projected_start }}</td>
                                    <td>{{ row.projected_interest }}</td>
                                    <td>{{ row.projected_required }}</td>
                                    <td>{{ row.projected_mandatory }}</td>
                                    <td>{{ row.projected_extra }}</td>
                                    <td>{{ row.projected_principal }}</td>
                                    <td>{{ row.projected_end }}</td>
                                    <td>{{ row.projected_closed }}</td>
                                    {% if row.projected_rolled_over == 'Yes' %}
                                    <td class="warning">Rolled Over</td>
                                    {% else %}
                                    <td></td>
                                    {% endif %}
                                    <td>{{ row.actual_start }}</td>
                                    <td>{{ row.actual_interest }}</td>
                                    <td>{{ row.actual_required }}</td>
                                    <td>{{ row.actual_payment }}</td>
                                    <td>{{ row.actual_pending }}</td>
                                    <td><strong>{{ row.actual_accumulated_pending }}</strong></td>
                                    <td>{{ row.actual_end }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                        </div>
                    </div>
                    {% endfor %}
                </div>
                
                <div class="footer">
                    Generated by Python Loan Optimization Engine
                </div>
            </div>

            <script>
            function openTab(evt, tabName) {
                var i, tabcontent, tablinks;
                // Hide all tab content
                tabcontent = document.getElementsByClassName("tab-content");
                for (i = 0; i < tabcontent.length; i++) {
                    tabcontent[i].style.display = "none";
                    tabcontent[i].classList.remove("active");
                }
                // Deactivate all tab buttons
                tablinks = document.getElementsByClassName("tab-button");
                for (i = 0; i < tablinks.length; i++) {
                    tablinks[i].classList.remove("active");
                }
                // Show target tab and activate button
                document.getElementById(tabName).style.display = "block";
                document.getElementById(tabName).classList.add("active");
                evt.currentTarget.classList.add("active");
            }
            </script>
        </body>
        </html>
        """

        env = Environment(autoescape=select_autoescape(["html", "xml"]))
        template = env.from_string(template_str)
        html_content = template.render(
            summary=summary_stats,
            allocations=allocations,
            loans=loans_data,
            master_schedule=master_schedule,
            base_income=format_inr(base_income),
            chart_svg=chart_svg,
        )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
