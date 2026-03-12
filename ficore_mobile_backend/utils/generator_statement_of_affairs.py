# Statement of Affairs PDF Generator
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import TableStyle
from reportlab.lib.enums import TA_CENTER

from utils.generator_core import (
    BaseReportGenerator, format_currency, get_nigerian_time, format_tin_display,
    create_table, parse_date_safe, ReportColors, safe_float, wrap_text_for_table
)

class StatementOfAffairsGenerator(BaseReportGenerator):
    """Specialized generator for Statement of Affairs"""
    
    def generate_statement_of_affairs(self, user_data, financial_data, tax_data, assets_data, 
                                      start_date=None, end_date=None, tax_type='PIT', profile_tax_type='PIT', tag_filter='business'):
        """
        Generate comprehensive Statement of Affairs PDF
        
        CRITICAL: This report calculates asset values (NBV) as of the endDate parameter.
        If endDate is provided, depreciation is calculated only up to that date.
        This ensures historical accuracy for mid-period reports.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        nigerian_time = get_nigerian_time()
        
        # Calculate key metrics
        incomes = financial_data.get('incomes', [])
        expenses = financial_data.get('expenses', [])
        
        # Use enhanced 3-Step P&L from tax_data
        sales_revenue = tax_data.get('sales_revenue', 0)
        other_income = tax_data.get('other_income', 0)
        total_income = tax_data.get('total_income', sales_revenue + other_income)
        total_cogs = tax_data.get('cost_of_goods_sold', 0)
        gross_profit = tax_data.get('gross_profit', (sales_revenue + other_income) - total_cogs)
        gross_margin = tax_data.get('gross_margin_percentage', 0)
        total_operating_expenses = tax_data.get('operating_expenses', 0)
        operating_profit = tax_data.get('operating_profit', gross_profit - total_operating_expenses)
        net_profit = tax_data.get('net_income', operating_profit)
        total_expenses = total_cogs + total_operating_expenses
        profit_margin = (net_profit / total_income * 100) if total_income > 0 else 0
        
        # VAS Breakdown
        vas_breakdown = tax_data.get('vas_breakdown', {})
        
        # Asset metrics
        total_assets_cost = sum(safe_float(asset.get('purchasePrice', 0) or asset.get('purchaseCost', 0)) for asset in assets_data)
        total_assets_nbv = sum(safe_float(asset.get('currentValue', 0)) for asset in assets_data)
        total_depreciation = total_assets_cost - total_assets_nbv
        asset_count = len(assets_data)
        
        # Current assets and liabilities
        inventory_value = tax_data.get('inventory_value', 0)
        debtors_value = tax_data.get('debtors_value', 0)
        creditors_value = tax_data.get('creditors_value', 0)
        inventory_count = tax_data.get('inventory_count', 0)
        debtors_count = tax_data.get('debtors_count', 0)
        creditors_count = tax_data.get('creditors_count', 0)
        
        # Cash/Bank balance
        cash_balance = tax_data.get('cash_balance', 0)
        
        # Opening equity and drawings
        opening_equity = tax_data.get('opening_equity', 0)
        drawings = tax_data.get('drawings', 0)
        capital = tax_data.get('capital', 0)
        loans_outstanding = tax_data.get('loans_outstanding', 0)
        
        # FC Credit and Subscription liabilities
        fc_credit_liabilities = tax_data.get('fc_credit_liabilities', 0)
        subscription_liabilities = tax_data.get('subscription_liabilities', 0)
        fee_waiver_liabilities = tax_data.get('fee_waiver_liabilities', 0)
        
        # Total assets including current assets
        total_current_assets = inventory_value + debtors_value + cash_balance
        total_all_assets = total_assets_nbv + total_current_assets
        
        # Total liabilities including all liability types
        total_current_liabilities = creditors_value + fc_credit_liabilities + subscription_liabilities + fee_waiver_liabilities
        
        # Calculate closing equity with capital contributions
        closing_equity = opening_equity + net_profit - drawings + capital
        
        # Tax calculation
        if tax_type == 'CIT':
            qualifies_for_exemption = (total_income <= 100000000) and (total_assets_nbv <= 250000000)
            if qualifies_for_exemption:
                estimated_tax = 0
                tax_rate_display = "0% (Exempt - Revenue ≤₦100M AND Assets ≤₦250M)"
            else:
                estimated_tax = net_profit * 0.30 if net_profit > 0 else 0
                tax_rate_display = "30% (CIT)"
        else:
            if net_profit <= 800000:
                estimated_tax = 0
            else:
                taxable = net_profit - 800000
                estimated_tax = taxable * 0.15
            tax_rate_display = "Progressive (PIT)"
        
        effective_rate = (estimated_tax / net_profit * 100) if net_profit > 0 else 0
        
        # Add estimated tax to current liabilities
        tax_liability = tax_data.get('tax_paid', 0)
        unpaid_tax = max(0, estimated_tax - tax_liability)
        
        # Include loans and all liabilities in total
        total_current_liabilities = creditors_value + unpaid_tax + loans_outstanding + fc_credit_liabilities + subscription_liabilities + fee_waiver_liabilities
        
        # Period text
        period_text = f"{start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}" if start_date and end_date else "All Time"
        
        # Build report sections
        story.extend(self._build_cover_page(user_data, period_text, nigerian_time, tax_type, 
                                          total_income, total_cogs, gross_profit, gross_margin,
                                          total_operating_expenses, net_profit, total_assets_nbv,
                                          total_current_assets, asset_count))
        
        story.extend(self._build_executive_summary(sales_revenue, other_income, total_income,
                                                 total_cogs, gross_profit, gross_margin,
                                                 total_operating_expenses, operating_profit,
                                                 net_profit, profit_margin, incomes,
                                                 total_assets_cost, total_assets_nbv, total_depreciation,
                                                 asset_count, inventory_value, debtors_value,
                                                 creditors_value, inventory_count, debtors_count,
                                                 creditors_count, cash_balance, loans_outstanding,
                                                 fc_credit_liabilities, subscription_liabilities,
                                                 fee_waiver_liabilities, total_current_assets,
                                                 total_current_liabilities, vas_breakdown, unpaid_tax,
                                                 tax_type, estimated_tax, effective_rate, tax_rate_display))
        
        story.extend(self._build_balance_sheet(total_assets_nbv, cash_balance, inventory_value,
                                             debtors_value, total_current_assets, total_all_assets,
                                             creditors_value, fc_credit_liabilities, subscription_liabilities,
                                             fee_waiver_liabilities, loans_outstanding, unpaid_tax,
                                             total_current_liabilities, opening_equity, net_profit,
                                             capital, drawings, closing_equity, inventory_count,
                                             debtors_count, creditors_count, end_date))
        
        story.extend(self._build_documentation_notes(tax_type, total_income, total_assets_nbv,
                                                   estimated_tax, cash_balance, inventory_count,
                                                   debtors_count, creditors_count, opening_equity,
                                                   nigerian_time, tax_type, profile_tax_type))
        
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def _build_cover_page(self, user_data, period_text, nigerian_time, tax_type, 
                         total_income, total_cogs, gross_profit, gross_margin,
                         total_operating_expenses, net_profit, total_assets_nbv,
                         total_current_assets, asset_count):
        """Build cover page section"""
        elements = []
        
        # Title
        title = Paragraph("STATEMENT OF AFFAIRS", ParagraphStyle(
            'CoverTitle',
            parent=self.styles['CustomTitle'],
            fontSize=28,
            textColor=ReportColors.FINANCIAL_GOLDEN,
            alignment=TA_CENTER
        ))
        elements.append(title)
        elements.append(Spacer(1, 20))
        
        # Business/User Info
        business_name = user_data.get('businessName', '')
        cover_info = f"""
<b>Business Name:</b> {business_name}<br/>
<b>Prepared For:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
<b>TIN:</b> {format_tin_display(user_data.get('tin'))}<br/>
<b>Email:</b> {user_data.get('email', '')}<br/>
<b>Reporting Period:</b> {period_text}<br/>
<b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}<br/>
<b>Tax Type:</b> {tax_type}
"""
        elements.append(Paragraph(cover_info, self.styles['InfoText']))
        elements.append(Spacer(1, 30))
        
        # Business Summary Dashboard
        elements.append(Paragraph("Business Summary", self.styles['SectionHeader']))
        
        summary_data = [
            ['Metric', 'Value'],
            ['Financial Period', period_text],
            ['Total Revenue', format_currency(total_income)],
            ['Cost of Goods Sold', format_currency(total_cogs)],
            ['Gross Profit', format_currency(gross_profit)],
            ['Gross Margin %', f'{gross_margin:.1f}%'],
            ['Operating Expenses', format_currency(total_operating_expenses)],
            ['Net Profit/(Loss)', format_currency(net_profit)],
            ['Total Assets (NBV)', format_currency(total_assets_nbv)],
            ['Current Assets', format_currency(total_current_assets)],
            ['Asset Count', f'{asset_count} assets'],
            ['Tax Type', tax_type],
        ]
        
        summary_table = create_table(summary_data, col_widths=[3*inch, 3*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.FINANCIAL_GOLDEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige)
        ]))
        
        elements.append(summary_table)
        elements.append(PageBreak())
        
        return elements
    
    def _build_executive_summary(self, sales_revenue, other_income, total_income,
                               total_cogs, gross_profit, gross_margin,
                               total_operating_expenses, operating_profit,
                               net_profit, profit_margin, incomes,
                               total_assets_cost, total_assets_nbv, total_depreciation,
                               asset_count, inventory_value, debtors_value,
                               creditors_value, inventory_count, debtors_count,
                               creditors_count, cash_balance, loans_outstanding,
                               fc_credit_liabilities, subscription_liabilities,
                               fee_waiver_liabilities, total_current_assets,
                               total_current_liabilities, vas_breakdown, unpaid_tax,
                               tax_type, estimated_tax, effective_rate, tax_rate_display):
        """Build executive summary section"""
        elements = []
        
        elements.append(Paragraph("Executive Summary", self.styles['CustomTitle']))
        elements.append(Spacer(1, 12))
        
        # Financial Overview
        elements.append(Paragraph("Financial Overview", self.styles['SectionHeader']))
        
        financial_overview = [
            ['Metric', 'Amount (N)', 'Notes'],
            ['REVENUE', '', ''],
            ['Sales Revenue', format_currency(sales_revenue), wrap_text_for_table('Product sales', 20)],
            ['Other Income', format_currency(other_income), wrap_text_for_table('Services, grants, interest', 20)],
            ['Total Revenue', format_currency(total_income), wrap_text_for_table(f'{len(incomes)} transactions', 20)],
            ['', '', ''],
            ['Less: Cost of Goods Sold (COGS)', format_currency(total_cogs), wrap_text_for_table('Direct product costs', 20)],
            ['GROSS PROFIT', format_currency(gross_profit), wrap_text_for_table(f'{gross_margin:.1f}% margin', 20)],
            ['', '', ''],
            ['Less: Operating Expenses', format_currency(total_operating_expenses), wrap_text_for_table('Rent, salaries, utilities', 20)],
            ['OPERATING PROFIT', format_currency(operating_profit), wrap_text_for_table('Before tax', 20)],
            ['', '', ''],
            ['NET PROFIT/(LOSS)', format_currency(net_profit), wrap_text_for_table(f'{profit_margin:.1f}% margin', 20)],
        ]
        
        financial_table = create_table(financial_overview, col_widths=[2*inch, 2*inch, 2*inch])
        financial_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.FINANCIAL_GOLDEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (0, 1), 'Helvetica-Bold'),  # REVENUE
            ('FONTNAME', (0, 7), (-1, 7), 'Helvetica-Bold'),  # GROSS PROFIT
            ('BACKGROUND', (0, 7), (-1, 7), colors.HexColor('#FFF9C4')),
            ('FONTNAME', (0, 10), (-1, 10), 'Helvetica-Bold'),  # OPERATING PROFIT
            ('BACKGROUND', (0, 10), (-1, 10), colors.HexColor('#FFE082')),
            ('FONTNAME', (0, 12), (-1, 12), 'Helvetica-Bold'),  # NET PROFIT
            ('BACKGROUND', (0, 12), (-1, 12), ReportColors.FINANCIAL_GOLDEN),
            ('TEXTCOLOR', (0, 12), (-1, 12), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(financial_table)
        elements.append(Spacer(1, 12))
        
        # Add helpful notes about Gross Margin
        if total_cogs == 0 and sales_revenue > 0:
            margin_note = """
<i><b>Note:</b> Your Gross Margin is 100% because you have no Cost of Goods Sold (COGS).
This is typical for service-based businesses that don't sell physical products.</i>
"""
            elements.append(Paragraph(margin_note, self.styles['InfoText']))
        elif sales_revenue == 0:
            margin_note = """
<i><b>Note:</b> Gross Margin is not applicable because there are no product sales recorded.
If you sell products, ensure they are categorized as "Sales Revenue" for accurate margin calculation.</i>
"""
            elements.append(Paragraph(margin_note, self.styles['InfoText']))
        
        elements.append(Spacer(1, 20))
        
        # Asset Overview
        elements.append(Paragraph("Fixed Assets Overview", self.styles['SectionHeader']))
        
        asset_overview = [
            ['Metric', 'Amount (N)', 'Notes'],
            ['Total Assets (Original)', format_currency(total_assets_cost), wrap_text_for_table(f'{asset_count} assets', 20)],
            ['Total Assets (NBV)', format_currency(total_assets_nbv), wrap_text_for_table('After depreciation', 20)],
            ['Total Depreciation', format_currency(total_depreciation), wrap_text_for_table('Accumulated', 20)],
        ]
        
        asset_table = create_table(asset_overview, col_widths=[2*inch, 2*inch, 2*inch])
        asset_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(asset_table)
        elements.append(Spacer(1, 20))
        
        # Current Assets & Liabilities Overview
        elements.append(Paragraph("Current Assets & Liabilities", self.styles['SectionHeader']))
        
        # Display helpers for zero values
        inventory_display = format_currency(inventory_value) if inventory_count > 0 else "N0.00 (Not tracked)"
        debtors_display = format_currency(debtors_value) if debtors_count > 0 else "N0.00 (Not tracked)"
        creditors_display = format_currency(creditors_value) if creditors_count > 0 else "N0.00 (Not tracked)"
        loans_display = format_currency(loans_outstanding) if loans_outstanding > 0 else "N0.00 (Not tracked)"
        fc_credit_display = format_currency(fc_credit_liabilities) if fc_credit_liabilities > 0 else "N0.00 (Not tracked)"
        subscription_display = format_currency(subscription_liabilities) if subscription_liabilities > 0 else "N0.00 (Not tracked)"
        fee_waiver_display = format_currency(fee_waiver_liabilities) if fee_waiver_liabilities > 0 else "N0.00 (Not tracked)"
        cash_display = format_currency(cash_balance) if cash_balance != 0 else "N0.00 (Not tracked)"
        
        current_assets_liabilities = [
            ['Item', 'Amount (N)', 'Notes'],
            ['CURRENT ASSETS', '', ''],
            ['Cash & Bank', cash_display, wrap_text_for_table('Liquid funds', 15)],
            ['Inventory (Stock)', inventory_display, wrap_text_for_table(f'{inventory_count} items' if inventory_count > 0 else '', 15)],
            ['Accounts Receivable (Debtors)', debtors_display, wrap_text_for_table(f'{debtors_count} customers' if debtors_count > 0 else '', 15)],
            ['Total Current Assets', format_currency(total_current_assets), ''],
            ['', '', ''],
            ['CURRENT LIABILITIES', '', ''],
            ['Accounts Payable (Creditors)', creditors_display, wrap_text_for_table(f'{creditors_count} vendors' if creditors_count > 0 else '', 15)],
            ['FC Credit Liabilities', fc_credit_display, wrap_text_for_table('Outstanding FC Credit obligations', 15)],
            ['Subscription Liabilities', subscription_display, wrap_text_for_table('Outstanding subscription obligations', 15)],
            ['Fee Waiver Liabilities', fee_waiver_display, wrap_text_for_table('Outstanding fee waiver obligations', 15)],
            ['Loans Payable', loans_display, wrap_text_for_table('Outstanding loan balances', 15)],
            ['Estimated Tax Payable', format_currency(unpaid_tax), wrap_text_for_table('Unpaid tax obligation', 15)],
            ['Total Current Liabilities', format_currency(total_current_liabilities), ''],
            ['', '', ''],
            ['NET CURRENT ASSETS', format_currency(total_current_assets - total_current_liabilities), wrap_text_for_table('Working Capital', 15)],
        ]
        
        current_table = create_table(current_assets_liabilities, col_widths=[2.5*inch, 2*inch, 1.5*inch])
        current_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.INVENTORY_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (0, 1), 'Helvetica-Bold'),  # CURRENT ASSETS
            ('FONTNAME', (0, 7), (0, 7), 'Helvetica-Bold'),  # CURRENT LIABILITIES
            ('FONTNAME', (0, 15), (-1, 15), 'Helvetica-Bold'),  # NET CURRENT ASSETS
            ('BACKGROUND', (0, 15), (-1, 15), colors.HexColor('#E8F5E9')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(current_table)
        elements.append(Spacer(1, 20))
        
        # VAS Breakdown Section (Granular Utility Reporting)
        if vas_breakdown and vas_breakdown.get('total', 0) > 0:
            elements.append(Paragraph("Value Added Services (VAS) Breakdown", self.styles['SectionHeader']))
            
            vas_data = [
                ['Service Type', 'Amount (N)', 'Notes'],
            ]
            
            if vas_breakdown.get('airtime', 0) > 0:
                vas_data.append(['Airtime', format_currency(vas_breakdown['airtime']), wrap_text_for_table('Mobile airtime purchases', 20)])
            if vas_breakdown.get('data', 0) > 0:
                vas_data.append(['Data', format_currency(vas_breakdown['data']), wrap_text_for_table('Mobile data bundles', 20)])
            if vas_breakdown.get('electricity', 0) > 0:
                vas_data.append(['Electricity', format_currency(vas_breakdown['electricity']), wrap_text_for_table('Power/utility bills', 20)])
            if vas_breakdown.get('cable_tv', 0) > 0:
                vas_data.append(['Cable TV', format_currency(vas_breakdown['cable_tv']), wrap_text_for_table('TV subscriptions', 20)])
            if vas_breakdown.get('internet', 0) > 0:
                vas_data.append(['Internet', format_currency(vas_breakdown['internet']), wrap_text_for_table('Internet services', 20)])
            if vas_breakdown.get('water', 0) > 0:
                vas_data.append(['Water', format_currency(vas_breakdown['water']), wrap_text_for_table('Water bills', 20)])
            if vas_breakdown.get('transportation', 0) > 0:
                vas_data.append(['Transportation', format_currency(vas_breakdown['transportation']), wrap_text_for_table('Transport services', 20)])
            if vas_breakdown.get('other', 0) > 0:
                vas_data.append(['Other VAS', format_currency(vas_breakdown['other']), wrap_text_for_table('Other services', 20)])
            
            vas_data.append(['', '', ''])
            vas_data.append(['Total VAS Expenses', format_currency(vas_breakdown['total']), wrap_text_for_table('All digital services', 20)])
            
            vas_table = create_table(vas_data, col_widths=[2*inch, 2*inch, 2*inch])
            vas_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9C27B0')),  # Purple for VAS
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),  # Total row
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E1BEE7')),  # Light purple
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            elements.append(vas_table)
            elements.append(Spacer(1, 20))
        
        # Tax Overview
        elements.append(Paragraph("Tax Overview", self.styles['SectionHeader']))
        
        # Calculate tax savings message when profitable but exempt
        tax_without_exemption = 0
        if tax_type == 'CIT' and net_profit > 0:
            tax_without_exemption = net_profit * 0.30  # 30% CIT rate
        elif tax_type == 'PIT' and net_profit > 800000:
            tax_without_exemption = (net_profit - 800000) * 0.15  # Simplified PIT
        
        tax_savings = tax_without_exemption - estimated_tax
        
        tax_overview = [
            ['Metric', 'Amount (N)', 'Notes'],
            ['Taxable Income', format_currency(net_profit), wrap_text_for_table('After deductions', 20)],
            ['Estimated Tax', format_currency(estimated_tax), wrap_text_for_table(tax_rate_display, 20)],
            ['Effective Rate', f"{effective_rate:.2f}%", ''],
        ]
        
        # Add tax savings message if applicable
        if tax_savings > 0 and estimated_tax == 0:
            tax_overview.append(['Tax Savings', format_currency(tax_savings), wrap_text_for_table('Amount saved through exemption', 20)])
        
        # Add CIT exemption context
        if tax_type == 'CIT':
            tax_overview.append(['Revenue Status', format_currency(total_income), wrap_text_for_table('≤N100M for exemption', 20)])
            tax_overview.append(['Assets NBV Status', format_currency(total_assets_nbv), wrap_text_for_table('≤N250M for exemption', 20)])
        
        tax_table = create_table(tax_overview, col_widths=[2*inch, 2*inch, 2*inch])
        tax_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.TAX_BROWN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(tax_table)
        
        return elements
    
    def _build_balance_sheet(self, total_assets_nbv, cash_balance, inventory_value,
                           debtors_value, total_current_assets, total_all_assets,
                           creditors_value, fc_credit_liabilities, subscription_liabilities,
                           fee_waiver_liabilities, loans_outstanding, unpaid_tax,
                           total_current_liabilities, opening_equity, net_profit,
                           capital, drawings, closing_equity, inventory_count,
                           debtors_count, creditors_count, end_date):
        """Build balance sheet section"""
        elements = []
        
        elements.append(Paragraph("Balance Sheet", self.styles['CustomTitle']))
        elements.append(Spacer(1, 12))
        
        # Display helpers for zero values
        inventory_display = format_currency(inventory_value) if inventory_count > 0 else "N0.00 (Not tracked)"
        debtors_display = format_currency(debtors_value) if debtors_count > 0 else "N0.00 (Not tracked)"
        creditors_display = format_currency(creditors_value) if creditors_count > 0 else "N0.00 (Not tracked)"
        loans_display = format_currency(loans_outstanding) if loans_outstanding > 0 else "N0.00 (Not tracked)"
        fc_credit_display = format_currency(fc_credit_liabilities) if fc_credit_liabilities > 0 else "N0.00 (Not tracked)"
        subscription_display = format_currency(subscription_liabilities) if subscription_liabilities > 0 else "N0.00 (Not tracked)"
        fee_waiver_display = format_currency(fee_waiver_liabilities) if fee_waiver_liabilities > 0 else "N0.00 (Not tracked)"
        cash_display = format_currency(cash_balance) if cash_balance != 0 else "N0.00 (Not tracked)"
        
        # ASSETS Section
        elements.append(Paragraph("ASSETS", self.styles['SectionHeader']))
        
        assets_section = [
            ['Asset Category', 'Amount (N)'],
            ['NON-CURRENT ASSETS', ''],
            ['Fixed Assets (Net Book Value)', format_currency(total_assets_nbv)],
            ['', ''],
            ['CURRENT ASSETS', ''],
            ['Cash & Bank', cash_display],
            ['Inventory', inventory_display],
            ['Accounts Receivable (Debtors)', debtors_display],
            ['Total Current Assets', format_currency(total_current_assets)],
            ['', ''],
            ['TOTAL ASSETS', format_currency(total_all_assets)],
        ]
        
        assets_bs_table = create_table(assets_section, col_widths=[3*inch, 3*inch])
        assets_bs_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (0, 1), 'Helvetica-Bold'),  # NON-CURRENT ASSETS
            ('FONTNAME', (0, 4), (0, 4), 'Helvetica-Bold'),  # CURRENT ASSETS
            ('FONTNAME', (0, 9), (-1, 9), 'Helvetica-Bold'),  # TOTAL ASSETS
            ('BACKGROUND', (0, 9), (-1, 9), colors.HexColor('#E3F2FD')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(assets_bs_table)
        elements.append(Spacer(1, 20))
        
        # LIABILITIES & EQUITY Section
        elements.append(Paragraph("LIABILITIES & EQUITY", self.styles['SectionHeader']))
        
        liabilities_section = [
            ['Category', 'Amount (N)'],
            ['CURRENT LIABILITIES', ''],
            ['Accounts Payable (Creditors)', creditors_display],
            ['FC Credit Liabilities', fc_credit_display],
            ['Subscription Liabilities', subscription_display],
            ['Fee Waiver Liabilities', fee_waiver_display],
            ['Loans Payable', loans_display],
            ['Estimated Tax Payable', format_currency(unpaid_tax)],
            ['Total Current Liabilities', format_currency(total_current_liabilities)],
            ['', ''],
            ['OWNER\'S EQUITY', ''],
            ['Opening Equity', format_currency(opening_equity)],
            ['Add: Net Profit/(Loss) for Period', format_currency(net_profit)],
            ['Add: Capital Contributions', format_currency(capital)],
            ['Less: Drawings/Withdrawals', format_currency(drawings)],
            ['Closing Equity', format_currency(closing_equity)],
            ['', ''],
            ['TOTAL LIABILITIES & EQUITY', format_currency(total_current_liabilities + closing_equity)],
        ]
        
        liabilities_bs_table = create_table(liabilities_section, col_widths=[3*inch, 3*inch])
        liabilities_bs_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.EXPENSE_RED),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (0, 1), 'Helvetica-Bold'),  # CURRENT LIABILITIES
            ('FONTNAME', (0, 9), (0, 9), 'Helvetica-Bold'),  # OWNER'S EQUITY
            ('FONTNAME', (0, 14), (-1, 14), 'Helvetica-Bold'),  # Closing Equity
            ('BACKGROUND', (0, 14), (-1, 14), colors.HexColor('#E8F5E9')),
            ('FONTNAME', (0, 16), (-1, 16), 'Helvetica-Bold'),  # TOTAL
            ('BACKGROUND', (0, 16), (-1, 16), colors.HexColor('#FFEBEE')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(liabilities_bs_table)
        
        # Accounting equation verification
        accounting_balance = total_all_assets - (total_current_liabilities + closing_equity)
        balance_status = "✓ Balanced" if abs(accounting_balance) < 0.01 else f"⚠ Difference: ₦{safe_float(accounting_balance):,.2f}"
        
        # Note about tracking and accounting equation
        note_text = f"""
<i><b>Note:</b> Items marked as "Not tracked" indicate that no data has been recorded for these categories.
Most SMEs focus on income and expenses tracking. Inventory, Debtors, Creditors, and Cash tracking is optional
but recommended for a complete financial picture.<br/>
<br/>
<b>Understanding Drawings:</b> Drawings represent money withdrawn by the owner for personal use. 
These are NOT business expenses and do NOT reduce profit. Instead, they reduce Owner's Equity.<br/>
<br/>
<b>Accounting Equation Check:</b> Assets (₦{safe_float(total_all_assets):,.2f}) = Liabilities (₦{safe_float(total_current_liabilities):,.2f}) + Equity (₦{safe_float(closing_equity):,.2f}) [{balance_status}]<br/>
<br/>
<b>Important:</b> This Statement of Affairs is calculated as of {end_date.strftime('%B %d, %Y') if end_date else 'the current date'}.
Asset depreciation and all values reflect the position at that specific date.</i>
"""
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(note_text, self.styles['InfoText']))
        elements.append(PageBreak())
        
        return elements
    
    def _build_documentation_notes(self, tax_type, total_income, total_assets_nbv,
                                 estimated_tax, cash_balance, inventory_count,
                                 debtors_count, creditors_count, opening_equity,
                                 nigerian_time, selected_tax_type, profile_tax_type):
        """Build documentation notes section"""
        elements = []
        
        elements.append(Paragraph("Documentation Notes & Best Practices", self.styles['CustomTitle']))
        elements.append(Spacer(1, 12))
        
        # Tax Filing Requirements
        elements.append(Paragraph("Tax Filing Requirements", self.styles['SectionHeader']))
        
        if tax_type == 'CIT':
            tax_requirements = f"""
<b>Corporate Income Tax (CIT) Filing Requirements:</b><br/>
<br/>
1. <b>Annual Returns:</b> File within 6 months of financial year-end<br/>
2. <b>Tax Rate:</b> 30% flat rate on taxable profits<br/>
3. <b>Small Company Exemption (0% CIT):</b><br/>
   • BOTH conditions must be met:<br/>
   • Annual revenue ≤ ₦100,000,000 AND<br/>
   • Fixed assets NBV ≤ ₦250,000,000<br/>
<br/>
<b>Your Business Status:</b><br/>
• Revenue: ₦{safe_float(total_income):,.2f} ({('≤' if total_income <= 100000000 else '>')} ₦100M)<br/>
• Assets NBV: ₦{safe_float(total_assets_nbv):,.2f} ({('≤' if total_assets_nbv <= 250000000 else '>')} ₦250M)<br/>
• Estimated Tax: ₦{safe_float(estimated_tax):,.2f}
"""
        else:
            tax_requirements = f"""
<b>Personal Income Tax (PIT) Filing Requirements:</b><br/>
<br/>
1. <b>Annual Returns:</b> File by March 31st of following year<br/>
2. <b>Tax-Free Threshold:</b> First ₦800,000 is tax-exempt<br/>
3. <b>Progressive Rates:</b> 0% to 25% based on income bands<br/>
<br/>
<b>Your Estimated Tax:</b> ₦{safe_float(estimated_tax):,.2f}
"""
        
        elements.append(Paragraph(tax_requirements, self.styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Record Keeping Recommendations
        elements.append(Paragraph("Record Keeping Recommendations", self.styles['SectionHeader']))
        
        recommendations_list = [
            "• Keep all receipts and invoices for at least 6 years",
            "• Maintain separate records for business and personal transactions",
            "• Update asset register regularly with new purchases",
            "• Review and reconcile accounts monthly",
            "• Back up financial records digitally"
        ]
        
        if cash_balance == 0:
            recommendations_list.append("• <b>Set up Cash/Bank tracking</b> in Business Suite → Cash/Bank Management for accurate financial position")
        if inventory_count == 0:
            recommendations_list.append("• Consider tracking Inventory if you sell physical products")
        if debtors_count == 0:
            recommendations_list.append("• Consider tracking Debtors if you offer credit sales")
        if creditors_count == 0:
            recommendations_list.append("• Consider tracking Creditors if you purchase on credit")
        if opening_equity == 0:
            recommendations_list.append("• <b>Set Opening Equity</b> to reflect capital contributions and prior period profits")
        
        recommendations = "<br/>".join(recommendations_list)
        elements.append(Paragraph(recommendations, self.styles['Normal']))
        elements.append(Spacer(1, 30))
        
        # Footer
        report_id = f"SOA-{nigerian_time.strftime('%Y%m%d%H%M%S')}"
        
        # Add tax override watermark if needed
        if selected_tax_type != profile_tax_type:
            elements.append(Spacer(1, 0.3*inch))
            elements.append(self._create_tax_override_watermark(selected_tax_type, profile_tax_type))
            elements.append(Spacer(1, 0.2*inch))
        
        footer_text = f"""
<i><b>DISCLAIMER:</b><br/>
This Statement of Affairs is generated from your FiCore Mobile App data for informational purposes only.<br/>
It does not constitute professional tax or financial advice.<br/>
<br/>
For official tax filing and compliance, please consult with:<br/>
• A certified tax professional<br/>
• A chartered accountant<br/>
• The Nigeria Revenue Service (NRS)<br/>
<br/>
Generated by FiCore Mobile App | team@ficoreafrica.com<br/>
Report ID: {report_id} | Generated: {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}</i>
"""
        
        elements.append(Paragraph(footer_text, self.styles['InfoText']))
        
        return elements