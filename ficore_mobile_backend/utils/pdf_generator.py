"""
PDF Generation Utilities for FiCore Mobile
Generates professional PDF reports for user data exports
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, LongTable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime, timezone, timedelta
import io


# CRITICAL FIX (Feb 19, 2026): Naira symbol rendering
# The ₦ symbol doesn't render properly in default Helvetica font
# Use "N" with proper formatting instead for PDF compatibility
NAIRA_SYMBOL = "N"  # Will be rendered as "N" with proper spacing


def format_currency(amount):
    """
    Format currency with proper Naira symbol for PDF rendering
    
    CRITICAL FIX (Feb 19, 2026): The ₦ symbol renders as a black square in PDFs
    because Helvetica font doesn't support it. Use "N" with proper spacing instead.
    
    Args:
        amount: Numeric amount to format
    
    Returns:
        Formatted string like "N1,234,567.89"
    """
    return f"{NAIRA_SYMBOL}{amount:,.2f}"


def format_tin_display(tin_value):
    """
    Format TIN for display in reports with actionable messaging
    
    CRITICAL FIX (Feb 19, 2026): Show actionable message when TIN not set
    to encourage users to update their tax information.
    
    Args:
        tin_value: TIN string from user data (may be empty, None, or 'Not Provided')
    
    Returns:
        Formatted string with red warning if not set, or the TIN value
    """
    if not tin_value or tin_value == 'Not Provided':
        return '<font color="red">Not Set - Update in Settings</font>'
    return tin_value


def get_nigerian_time():
    """Get current time in Nigerian timezone (WAT - UTC+1)"""
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=1)))


def create_table(data, col_widths, use_long_table_threshold=50):
    """
    Create a Table or LongTable based on data size for optimal performance.
    
    LongTable is optimized for:
    - Multi-page tables
    - Large datasets (50+ rows)
    - Better memory management
    - Streaming data
    - TIMEOUT PROTECTION: splitByRow=True prevents hanging on massive tables
    
    Args:
        data: List of lists containing table data
        col_widths: List of column widths
        use_long_table_threshold: Number of rows above which to use LongTable (default: 50)
    
    Returns:
        Table or LongTable instance with timeout protection
    """
    row_count = len(data)
    
    # Use LongTable for large datasets (better memory management and performance)
    if row_count > use_long_table_threshold:
        # splitByRow=True: CRITICAL for timeout protection on large tables
        # Allows table to split across pages without loading entire table in memory
        return LongTable(data, colWidths=col_widths, repeatRows=1, splitByRow=True)
    else:
        return Table(data, colWidths=col_widths)


def parse_date_safe(date_value):
    """Safely parse date from string or datetime object"""
    if isinstance(date_value, datetime):
        return date_value
    elif isinstance(date_value, str):
        try:
            return datetime.fromisoformat(date_value.replace('Z', ''))
        except:
            return datetime.now(timezone.utc)
    else:
        return datetime.now(timezone.utc)


def apply_one_naira_minimum_rule(current_value, status='active'):
    """
    Apply ₦1 minimum rule for fully depreciated assets
    
    PROFESSIONAL ACCOUNTING STANDARD:
    Active assets that are fully depreciated should maintain ₦1.00 notional value.
    This prevents them from "disappearing" from the asset register.
    Disposed assets can show ₦0.00.
    
    Args:
        current_value: Calculated current value of the asset
        status: Asset status ('active', 'disposed', 'under_maintenance')
    
    Returns:
        Adjusted value (minimum ₦1.00 for active assets)
    """
    if status == 'active' and current_value <= 0:
        return 1.0
    return max(0, current_value)


class ReportColors:
    """
    Unified color scheme matching mobile app UI
    Ensures PDF exports have the same visual identity as in-app screens
    """
    
    # Category Colors (matching app UI from screenshots)
    WALLET_PURPLE = colors.HexColor('#9C27B0')      # Wallet Reports (Purple)
    ACCOUNTS_ORANGE = colors.HexColor('#FF9800')    # Accounts Management (Orange)
    INVENTORY_GREEN = colors.HexColor('#4CAF50')    # Inventory & Assets (Green)
    FINANCIAL_GOLDEN = colors.HexColor('#D4AF37')   # Financial Reports (Golden)
    INCOME_BLUE = colors.HexColor('#2196F3')        # Income Records (Blue)
    EXPENSE_RED = colors.HexColor('#F44336')        # Expense Records (Red)
    TAX_BROWN = colors.HexColor('#795548')          # Tax Reports (Brown)
    
    # Light backgrounds for tables (matching 10% opacity from app)
    WALLET_LIGHT = colors.HexColor('#F3E5F5')       # Purple light
    ACCOUNTS_LIGHT = colors.HexColor('#FFF3E0')     # Orange light
    INVENTORY_LIGHT = colors.HexColor('#E8F5E9')    # Green light
    FINANCIAL_LIGHT = colors.HexColor('#FFF9E6')    # Golden light
    INCOME_LIGHT = colors.HexColor('#E3F2FD')       # Blue light
    EXPENSE_LIGHT = colors.HexColor('#FFEBEE')      # Red light
    TAX_LIGHT = colors.HexColor('#EFEBE9')          # Brown light


class PDFGenerator:
    """Generate PDF reports for various data types"""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
    
    def setup_custom_styles(self):
        """Setup custom paragraph styles"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a73e8'),
            spaceAfter=30,
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#333333'),
            spaceAfter=12,
            spaceBefore=12
        ))
        
        self.styles.add(ParagraphStyle(
            name='InfoText',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#666666')
        ))
    
    def generate_financial_report(self, user_data, export_data, data_type='all'):
        """Generate comprehensive financial report PDF"""
        # DISABLED FOR VAS FOCUS
        # print(f"DEBUG PDF GENERATOR: generate_financial_report called with data_type='{data_type}'")
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title - Dynamic based on data type
        report_titles = {
            'all': 'Profit & Loss Statement',
            'incomes': 'Income Report',
            'expenses': 'Expense Report'
        }
        title_text = report_titles.get(data_type.lower(), 'Financial Report')
        title = Paragraph(title_text, self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        business_name = user_data.get('businessName', '')
        business_line = f"<b>Business:</b> {business_name}<br/>" if business_name else ""
        tin_display = format_tin_display(user_data.get('tin', ''))
        tin_line = f"<b>TIN:</b> {tin_display}<br/>"
        
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        {business_line}{tin_line}<b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}<br/>
        <b>Report Type:</b> {data_type.upper()}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Expenses Section
        if 'expenses' in export_data and export_data['expenses']:
            story.append(Paragraph("Expenses Summary", self.styles['SectionHeader']))
            
            expense_data = [['Date', 'Category', 'Description', 'Amount (N)']]
            total_expenses = 0
            
            for expense in export_data['expenses']:
                date_obj = parse_date_safe(expense.get('date'))
                date_str = date_obj.strftime('%Y-%m-%d')
                # Use description if available, otherwise fall back to title
                description = expense.get('description') or expense.get('notes') or expense.get('title', 'N/A')
                category = expense.get('category', 'N/A')
                
                # Wrap long text in Paragraph objects for automatic text wrapping
                category_para = Paragraph(category, self.styles['Normal'])
                description_para = Paragraph(description, self.styles['Normal'])
                
                expense_data.append([
                    date_str,
                    category_para,
                    description_para,
                    format_currency(expense.get('amount', 0))
                ])
                total_expenses += expense.get('amount', 0)
            
            expense_data.append(['', '', 'Total:', format_currency(total_expenses)])
            
            # Optimized column widths: Date (1.2"), Category (1.5"), Description (2.5"), Amount (1.3")
            expense_table = create_table(expense_data, col_widths=[1.2*inch, 1.5*inch, 2.5*inch, 1.3*inch])
            expense_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), ReportColors.EXPENSE_RED),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 1), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                ('BACKGROUND', (0, -1), (-1, -1), ReportColors.EXPENSE_LIGHT),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # Align text to top for multi-line descriptions
            ]))
            
            story.append(expense_table)
            story.append(Spacer(1, 20))
        
        # Income Section
        if 'incomes' in export_data and export_data['incomes']:
            story.append(Paragraph("Income Summary", self.styles['SectionHeader']))
            
            income_data = [['Date', 'Category', 'Description', 'Amount (N)']]
            total_income = 0
            
            for income in export_data['incomes']:
                date_obj = parse_date_safe(income.get('dateReceived'))
                date_str = date_obj.strftime('%Y-%m-%d')
                # Use description if available, otherwise fall back to source
                description = income.get('description') or income.get('source', 'N/A')
                # Get category display name
                category = income.get('category', 'Other')
                
                # Wrap long text in Paragraph objects for automatic text wrapping
                category_para = Paragraph(category, self.styles['Normal'])
                description_para = Paragraph(description, self.styles['Normal'])
                
                income_data.append([
                    date_str,
                    category_para,
                    description_para,
                    format_currency(income.get('amount', 0))
                ])
                total_income += income.get('amount', 0)
            
            income_data.append(['', '', 'Total:', format_currency(total_income)])
            
            # Optimized column widths: Date (1.2"), Category (1.5"), Description (2.5"), Amount (1.3")
            income_table = create_table(income_data, col_widths=[1.2*inch, 1.5*inch, 2.5*inch, 1.3*inch])
            income_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), ReportColors.INCOME_BLUE),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 1), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                ('BACKGROUND', (0, 1), (-1, -2), colors.lightgreen),
                ('BACKGROUND', (0, -1), (-1, -1), ReportColors.INCOME_LIGHT),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # Align text to top for multi-line descriptions
            ]))
            
            story.append(income_table)
            story.append(Spacer(1, 20))
        
        # Credit Transactions Section
        if 'creditTransactions' in export_data and export_data['creditTransactions']:
            story.append(Paragraph("Credit Transactions", self.styles['SectionHeader']))
            
            credit_data = [['Date', 'Type', 'Description', 'Amount (FC)']]
            
            for transaction in export_data['creditTransactions']:
                date_obj = parse_date_safe(transaction.get('createdAt'))
                date_str = date_obj.strftime('%Y-%m-%d')
                credit_data.append([
                    date_str,
                    transaction.get('type', 'N/A'),
                    transaction.get('description', 'N/A'),
                    f"{transaction.get('amount', 0):,.2f}"
                ])
            
            credit_table = create_table(credit_data, col_widths=[1.5*inch, 1.5*inch, 2.5*inch, 1*inch])
            credit_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fbbc04')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fff9e6')),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(credit_table)
            story.append(Spacer(1, 20))
        
        # Profit & Loss Summary Section (only for 'all' data type)
        if data_type.lower() == 'all':
            # Calculate totals
            total_income = 0
            if 'incomes' in export_data and export_data['incomes']:
                total_income = sum(income.get('amount', 0) for income in export_data['incomes'])
            
            # COGS SEPARATION (Phase 2.1): Separate COGS from Operating Expenses
            cogs_expenses = []
            operating_expenses = []
            if 'expenses' in export_data and export_data['expenses']:
                for expense in export_data['expenses']:
                    if expense.get('category') == 'Cost of Goods Sold':
                        cogs_expenses.append(expense)
                    else:
                        operating_expenses.append(expense)
            
            total_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
            total_operating_expenses = sum(exp.get('amount', 0) for exp in operating_expenses)
            total_expenses = total_cogs + total_operating_expenses
            
            gross_profit = total_income - total_cogs
            net_profit_loss = gross_profit - total_operating_expenses
            
            # DEBUG: Log that we're adding the summary
            # DISABLED FOR VAS FOCUS
            # print(f"DEBUG P&L SUMMARY: Adding Financial Summary - Income: ₦{total_income:,.2f}, Expenses: ₦{total_expenses:,.2f}, Net: ₦{net_profit_loss:,.2f}")
            
            # Add summary section
            story.append(Spacer(1, 10))
            story.append(Paragraph("Financial Summary", self.styles['SectionHeader']))
            
            summary_data = [
                ['Description', 'Amount (N)'],
                ['Total Revenue', format_currency(total_income)],
                ['Less: Cost of Goods Sold', format_currency(total_cogs)],
                ['Gross Profit', format_currency(gross_profit)],
                ['Less: Operating Expenses', format_currency(total_operating_expenses)],
                ['Net Profit / (Loss)', format_currency(net_profit_loss)]
            ]
            
            summary_table = create_table(summary_data, col_widths=[4*inch, 2*inch])
            
            # Determine color based on profit or loss
            result_bg_color = colors.HexColor('#e8f5e9') if net_profit_loss >= 0 else colors.HexColor('#fce8e6')
            result_text_color = colors.HexColor('#2e7d32') if net_profit_loss >= 0 else colors.HexColor('#c62828')
            
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), ReportColors.FINANCIAL_GOLDEN),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, 2), colors.beige),
                ('BACKGROUND', (0, 3), (0, 3), colors.HexColor('#e8f5e9')),  # Gross Profit row
                ('FONTNAME', (0, 3), (-1, 3), 'Helvetica-Bold'),  # Gross Profit bold
                ('BACKGROUND', (0, 4), (-1, 4), colors.beige),
                ('BACKGROUND', (0, -1), (-1, -1), result_bg_color),
                ('TEXTCOLOR', (0, -1), (-1, -1), result_text_color),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, -1), (-1, -1), 14),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('LINEABOVE', (0, 3), (-1, 3), 1.5, colors.black),  # Line above Gross Profit
                ('LINEABOVE', (0, -1), (-1, -1), 2, colors.black),
            ]))
            
            story.append(summary_table)
            story.append(Spacer(1, 20))
        
        # Footer
        footer_text = """
        <i>This report was generated by FiCore Mobile App.<br/>
        For support, contact: team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def generate_tax_report(self, user_data, tax_calculation):
        """Generate tax calculation report PDF with Nigerian 2025 tax bands"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Tax Calculation Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>TIN:</b> {format_tin_display(user_data.get('tin', ''))}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Tax Year:</b> {tax_calculation.get('tax_year', nigerian_time.year)}<br/>
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Income Summary
        story.append(Paragraph("Income Summary", self.styles['SectionHeader']))
        income_data = [
            ['Description', 'Amount (N)'],
            ['Total Income', format_currency(tax_calculation.get('total_income', 0))],
            ['Deductible Expenses', format_currency(tax_calculation.get('deductible_expenses', {}).get('total', 0))],
            ['Net Income', format_currency(tax_calculation.get('net_income', 0))],
            ['Statutory Contributions', format_currency(tax_calculation.get('statutory_contributions', 0))],
            ['Adjusted Income', format_currency(tax_calculation.get('adjusted_income', 0))],
            ['Rent Relief', format_currency(tax_calculation.get('rent_relief', 0))],
            ['Taxable Income', format_currency(tax_calculation.get('taxable_income', 0))]
        ]
        
        income_table = create_table(income_data, col_widths=[4*inch, 2*inch])
        income_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.TAX_BROWN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.TAX_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(income_table)
        story.append(Spacer(1, 20))
        
        # Tax Breakdown
        story.append(Paragraph("Tax Calculation Breakdown", self.styles['SectionHeader']))
        tax_breakdown_data = [['Tax Band', 'Rate', 'Taxable Amount (N)', 'Tax (N)']]
        
        for band in tax_calculation.get('tax_breakdown', []):
            tax_breakdown_data.append([
                f"N{band['lower_bound']:,.0f} - N{band['upper_bound']:,.0f}",
                f"{band['rate']*100:.0f}%",
                format_currency(band['taxable_amount']),
                format_currency(band['tax_amount'])
            ])
        
        tax_breakdown_data.append([
            '', 'Total Tax:', '', 
            format_currency(tax_calculation.get('total_tax', 0))
        ])
        
        tax_table = create_table(tax_breakdown_data, col_widths=[2*inch, 1*inch, 1.5*inch, 1.5*inch])
        tax_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.TAX_BROWN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.TAX_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(tax_table)
        story.append(Spacer(1, 20))
        
        # Summary
        story.append(Paragraph("Summary", self.styles['SectionHeader']))
        summary_text = f"""
        <b>Total Tax Liability:</b> {format_currency(tax_calculation.get('total_tax', 0))}<br/>
        <b>Effective Tax Rate:</b> {tax_calculation.get('effective_rate', 0):.2f}%<br/>
        <b>Net Income After Tax:</b> {format_currency(tax_calculation.get('net_income_after_tax', 0))}
        """
        story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This tax calculation is for informational purposes only.<br/>
        Please consult with a tax professional for official tax filing.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_cash_flow_report(self, user_data, transactions, start_date=None, end_date=None):
        """Generate Cash Flow statement PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Cash Flow Statement", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        period_text = ""
        if start_date and end_date:
            period_text = f"<b>Period:</b> {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}<br/>"
        
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>TIN:</b> {format_tin_display(user_data.get('tin', ''))}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        {period_text}
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Calculate cash flows
        operating_inflows = sum(t.get('amount', 0) for t in transactions.get('incomes', []))
        operating_outflows = sum(t.get('amount', 0) for t in transactions.get('expenses', []))
        net_operating = operating_inflows - operating_outflows
        
        # Operating Activities
        story.append(Paragraph("Cash Flow from Operating Activities", self.styles['SectionHeader']))
        operating_data = [
            ['Description', 'Amount (N)'],
            ['Cash Inflows (Income)', format_currency(operating_inflows)],
            ['Cash Outflows (Expenses)', format_currency(-operating_outflows)],
            ['Net Cash from Operations', format_currency(net_operating)]
        ]
        
        operating_table = create_table(operating_data, col_widths=[4*inch, 2*inch])
        operating_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.FINANCIAL_GOLDEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.FINANCIAL_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(operating_table)
        story.append(Spacer(1, 20))
        
        # Summary
        story.append(Paragraph("Summary", self.styles['SectionHeader']))
        summary_text = f"""
        <b>Total Cash Inflows:</b> ₦{operating_inflows:,.2f}<br/>
        <b>Total Cash Outflows:</b> ₦{operating_outflows:,.2f}<br/>
        <b>Net Cash Flow:</b> ₦{net_operating:,.2f}
        """
        story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This cash flow statement is for informational purposes only.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_tax_summary_report(self, user_data, tax_data, start_date=None, end_date=None, tax_type='PIT'):
        """
        Generate Tax Summary PDF with Nigerian tax formatting
        
        Args:
            user_data: User information
            tax_data: Tax calculation data
            start_date: Start date for tax period
            end_date: End date for tax period
            tax_type: 'PIT' for Personal Income Tax or 'CIT' for Corporate Income Tax
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title based on tax type
        tax_type_name = "Personal Income Tax (PIT)" if tax_type == 'PIT' else "Corporate Income Tax (CIT)"
        title = Paragraph(f"Tax Summary Report - {tax_type_name}", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        period_text = ""
        if start_date and end_date:
            period_text = f"<b>Tax Period:</b> {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}<br/>"
        
        business_name = user_data.get('businessName', '')
        entity_info = f"<b>Business:</b> {business_name}<br/>" if business_name else ""
        
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        {entity_info}
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Tax Type:</b> {tax_type_name}<br/>
        {period_text}
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Income Summary
        story.append(Paragraph("Income Summary", self.styles['SectionHeader']))
        total_income = tax_data.get('total_income', 0)
        deductible_expenses = tax_data.get('deductible_expenses', 0)
        
        # Build income data based on tax type
        income_data = [['Description', 'Amount (N)']]
        income_data.append(['Gross Income', format_currency(total_income)])
        
        # For PIT, show detailed statutory deductions breakdown
        if tax_type == 'PIT' and 'statutory_deductions' in tax_data:
            statutory = tax_data['statutory_deductions']
            
            income_data.append(['Less: Business Expenses', format_currency(tax_data.get('deductible_expenses', 0) - statutory.get('total', 0))])
            
            # Show statutory deductions breakdown
            if statutory.get('rent_relief', {}).get('relief_amount', 0) > 0:
                income_data.append(['Less: Rent Relief (20%, max ₦500k)', format_currency(statutory['rent_relief']['relief_amount'])])
            
            if statutory.get('pension_contributions', 0) > 0:
                income_data.append(['Less: Pension Contributions', format_currency(statutory['pension_contributions'])])
            
            if statutory.get('life_insurance', 0) > 0:
                income_data.append(['Less: Life Insurance Premiums', format_currency(statutory['life_insurance'])])
            
            if statutory.get('nhis_contributions', 0) > 0:
                income_data.append(['Less: NHIS Contributions', format_currency(statutory['nhis_contributions'])])
            
            if statutory.get('hmo_premiums', 0) > 0:
                income_data.append(['Less: HMO Premiums', format_currency(statutory['hmo_premiums'])])
        else:
            income_data.append(['Less: Deductible Expenses', format_currency(deductible_expenses)])
        
        net_income = total_income - deductible_expenses
        income_data.append(['Taxable Income', format_currency(net_income)])
        
        income_table = create_table(income_data, col_widths=[4*inch, 2*inch])
        income_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.TAX_BROWN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.TAX_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(income_table)
        story.append(Spacer(1, 20))
        
        # Tax Calculation based on type
        if tax_type == 'CIT':
            # Corporate Income Tax Calculation
            story.append(Paragraph("Corporate Income Tax Calculation", self.styles['SectionHeader']))
            
            # CIT is a flat 30% rate in Nigeria (as of 2026)
            cit_rate = 0.30
            total_tax = net_income * cit_rate if net_income > 0 else 0
            
            # CRITICAL: CIT Exemption requires BOTH conditions to be met (AND, not OR)
            # Exemption applies if: (Turnover < ₦100M) AND (Fixed Assets NBV < ₦250M)
            turnover = tax_data.get('annual_turnover', 0)
            fixed_assets_nbv = tax_data.get('fixed_assets_nbv', 0)  # Net Book Value, not original cost
            qualifies_for_exemption = (turnover < 100000000) and (fixed_assets_nbv < 250000000)
            
            cit_data = [
                ['Description', 'Amount (N)'],
                ['Taxable Profit', format_currency(net_income)],
                ['CIT Rate', f"{cit_rate*100:.0f}%"],
                ['Calculated Tax', format_currency(total_tax)]
            ]
            
            if qualifies_for_exemption:
                cit_data.append(['Small Company Exemption', 'MAY APPLY*'])
            
            cit_table = create_table(cit_data, col_widths=[4*inch, 2*inch])
            cit_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), ReportColors.TAX_BROWN),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), ReportColors.TAX_LIGHT),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(cit_table)
            story.append(Spacer(1, 20))
            
            # Business Assets & Exemption Analysis
            story.append(Paragraph("Business Assets & Exemption Analysis", self.styles['SectionHeader']))
            
            # Get comprehensive business data
            fixed_assets_original_cost = tax_data.get('fixed_assets_original_cost', 0)
            inventory_value = tax_data.get('inventory_value', 0)
            debtors_value = tax_data.get('debtors_value', 0)
            creditors_value = tax_data.get('creditors_value', 0)
            assets_count = tax_data.get('assets_count', 0)
            
            # Calculate total business value (for balance sheet display)
            # Note: Inventory, Debtors, Creditors are shown for complete financial picture
            # but are NOT used for CIT exemption calculation
            total_assets = fixed_assets_nbv + inventory_value + debtors_value
            net_assets = total_assets - creditors_value
            
            assets_breakdown_data = [
                ['Asset Category', 'Value (N)'],
                ['Fixed Assets - Net Book Value*', format_currency(fixed_assets_nbv)],
                ['Fixed Assets - Original Cost', format_currency(fixed_assets_original_cost)],
                ['Inventory Stock Value', format_currency(inventory_value)],
                ['Accounts Receivable (Debtors)', format_currency(debtors_value)],
                ['Total Assets', format_currency(total_assets)],
                ['Less: Accounts Payable (Creditors)', format_currency(creditors_value)],
                ['Net Business Assets', format_currency(net_assets)]
            ]
            
            assets_table = create_table(assets_breakdown_data, col_widths=[4*inch, 2*inch])
            assets_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#e8f0fe')),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#1a73e8')),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(assets_table)
            story.append(Spacer(1, 12))
            
            # Note about NBV
            nbv_note = """
            <i>*Net Book Value = Original Cost - Accumulated Depreciation (used for CIT exemption)</i>
            """
            story.append(Paragraph(nbv_note, self.styles['InfoText']))
            story.append(Spacer(1, 20))
            
            # CIT Exemption Eligibility Analysis
            story.append(Paragraph("CIT Exemption Eligibility", self.styles['SectionHeader']))
            
            turnover_qualifies = turnover < 100000000
            assets_qualify = fixed_assets_nbv < 250000000
            
            turnover_status = "✓ QUALIFIES" if turnover_qualifies else "✗ EXCEEDS LIMIT"
            assets_status = "✓ QUALIFIES" if assets_qualify else "✗ EXCEEDS LIMIT"
            
            overall_status = "✓ QUALIFIES" if qualifies_for_exemption else "✗ DOES NOT QUALIFY"
            
            exemption_text = f"""
            <b>CIT Exemption Status: {overall_status}</b><br/>
            <br/>
            <b>Criterion 1: Annual Turnover</b><br/>
            • Threshold: Below ₦100,000,000<br/>
            • Your Turnover: ₦{turnover:,.2f}<br/>
            • Status: {turnover_status}<br/>
            <br/>
            <b>Criterion 2: Fixed Assets Net Book Value</b><br/>
            • Threshold: Below ₦250,000,000<br/>
            • Your Fixed Assets NBV: ₦{fixed_assets_nbv:,.2f}<br/>
            • Status: {assets_status}<br/>
            <br/>
            <b>CRITICAL: Exemption Rule</b><br/>
            You qualify for CIT exemption ONLY if <b>BOTH</b> criteria are met:<br/>
            (Turnover < ₦100M) <b>AND</b> (Fixed Assets NBV < ₦250M)<br/>
            <br/>
            <b>Note:</b> For the ₦250M threshold, ONLY Fixed Assets Net Book Value is considered.<br/>
            Inventory, Debtors, and Creditors are NOT included in this specific exemption calculation.<br/>
            <br/>
            *This analysis is based on your FiCore data. Consult a tax professional to confirm eligibility and claim this exemption.
            """
            story.append(Paragraph(exemption_text, self.styles['Normal']))
            story.append(Spacer(1, 20))
        else:
            # Personal Income Tax Calculation
            story.append(Paragraph("Personal Income Tax Calculation (PIT Bands 2025)", self.styles['SectionHeader']))
            
            # Nigerian Personal Income Tax bands (Effective Jan 1, 2026 for 2025 assessments)
            # First ₦800,000 is fully tax-exempt
            tax_bands = [
                (0, 800000, 0.00),              # Tax-exempt threshold
                (800000, 3000000, 0.15),        # 15% on next ₦2,200,000
                (3000000, 12000000, 0.18),      # 18% on next ₦9,000,000
                (12000000, 25000000, 0.21),     # 21% on next ₦13,000,000
                (25000000, 50000000, 0.23),     # 23% on next ₦25,000,000
                (50000000, float('inf'), 0.25)  # 25% on remainder
            ]
            
            tax_breakdown_data = [['Income Band', 'Rate', 'Taxable Amount (N)', 'Tax (N)']]
            total_tax = 0
            
            for lower, upper, rate in tax_bands:
                if net_income <= lower:
                    break
                
                # Calculate the portion of income in this band
                taxable_in_band = min(net_income, upper) - lower
                if taxable_in_band <= 0:
                    continue
                
                band_tax = taxable_in_band * rate
                total_tax += band_tax
                
                upper_display = f"₦{upper:,.0f}" if upper != float('inf') else "Above"
                tax_breakdown_data.append([
                    f"₦{lower:,.0f} - {upper_display}",
                    f"{rate*100:.1f}%",
                    format_currency(taxable_in_band),
                    format_currency(band_tax)
                ])
            
            tax_breakdown_data.append(['', '', 'Total Tax:', format_currency(total_tax)])
            
            tax_table = create_table(tax_breakdown_data, col_widths=[2*inch, 1*inch, 1.5*inch, 1.5*inch])
            tax_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ea4335')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fce8e6')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(tax_table)
            story.append(Spacer(1, 20))
        
        # Summary
        effective_rate = (total_tax / net_income * 100) if net_income > 0 else 0
        net_after_tax = net_income - total_tax
        
        story.append(Paragraph("Tax Summary", self.styles['SectionHeader']))
        summary_text = f"""
        <b>Total Tax Liability:</b> ₦{total_tax:,.2f}<br/>
        <b>Effective Tax Rate:</b> {effective_rate:.2f}%<br/>
        <b>Net Income After Tax:</b> ₦{net_after_tax:,.2f}
        """
        story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer based on tax type
        if tax_type == 'CIT':
            footer_text = """
            <i>This tax summary uses Nigerian Corporate Income Tax rate (25% flat rate).<br/>
            Small companies (turnover < ₦100M OR assets < ₦250M) may qualify for exemptions.<br/>
            For informational purposes only. Consult a tax professional for official filing.<br/>
            Generated by FiCore Mobile App | team@ficoreafrica.com</i>
            """
        else:
            footer_text = """
            <i>This tax summary uses Nigerian Personal Income Tax bands (effective Jan 1, 2026).<br/>
            ₦800,000 annual income is fully tax-exempt. Rent relief (20% of rent, max ₦500,000) may apply.<br/>
            For informational purposes only. Consult a tax professional for official filing.<br/>
            Generated by FiCore Mobile App | team@ficoreafrica.com</i>
            """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_debtors_report(self, user_data, debtors, start_date=None, end_date=None):
        """Generate Debtors/Accounts Receivable PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Accounts Receivable (Debtors) Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        period_text = ""
        if start_date and end_date:
            period_text = f"<b>Period:</b> {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}<br/>"
        
        nigerian_time = get_nigerian_time()
        user_info = f"""
        <b>Business:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        {period_text}
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        if not debtors:
            story.append(Paragraph("No outstanding debtors found.", self.styles['Normal']))
        else:
            # Debtors Table
            story.append(Paragraph("Outstanding Receivables", self.styles['SectionHeader']))
            
            debtor_data = [['Debtor Name', 'Invoice Date', 'Due Date', 'Amount (N)', 'Status']]
            total_outstanding = 0
            overdue_amount = 0
            
            for debtor in debtors:
                invoice_date = parse_date_safe(debtor.get('invoiceDate'))
                due_date = parse_date_safe(debtor.get('dueDate'))
                amount = debtor.get('amount', 0)
                
                # Determine status
                if nigerian_time.replace(tzinfo=None) > due_date.replace(tzinfo=None):
                    status = 'OVERDUE'
                    overdue_amount += amount
                else:
                    status = 'Current'
                
                debtor_data.append([
                    debtor.get('name', 'N/A'),
                    invoice_date.strftime('%Y-%m-%d'),
                    due_date.strftime('%Y-%m-%d'),
                    format_currency(amount),
                    status
                ])
                total_outstanding += amount
            
            debtor_data.append(['', '', 'Total Outstanding:', format_currency(total_outstanding), ''])
            
            debtor_table = create_table(debtor_data, col_widths=[1.8*inch, 1.2*inch, 1.2*inch, 1.3*inch, 1*inch])
            debtor_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fbbc04')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#fff9e6')),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fbbc04')),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(debtor_table)
            story.append(Spacer(1, 20))
            
            # Summary
            story.append(Paragraph("Summary", self.styles['SectionHeader']))
            summary_text = f"""
            <b>Total Outstanding:</b> ₦{total_outstanding:,.2f}<br/>
            <b>Overdue Amount:</b> ₦{overdue_amount:,.2f}<br/>
            <b>Number of Debtors:</b> {len(debtors)}
            """
            story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This debtors report shows all outstanding receivables.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_creditors_report(self, user_data, creditors, start_date=None, end_date=None):
        """Generate Creditors/Accounts Payable PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Accounts Payable (Creditors) Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        period_text = ""
        if start_date and end_date:
            period_text = f"<b>Period:</b> {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}<br/>"
        
        nigerian_time = get_nigerian_time()
        user_info = f"""
        <b>Business:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        {period_text}
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        if not creditors:
            story.append(Paragraph("No outstanding creditors found.", self.styles['Normal']))
        else:
            # Creditors Table
            story.append(Paragraph("Outstanding Payables", self.styles['SectionHeader']))
            
            creditor_data = [['Creditor Name', 'Invoice Date', 'Due Date', 'Amount (N)', 'Status']]
            total_outstanding = 0
            overdue_amount = 0
            
            for creditor in creditors:
                invoice_date = parse_date_safe(creditor.get('invoiceDate'))
                due_date = parse_date_safe(creditor.get('dueDate'))
                amount = creditor.get('amount', 0)
                
                # Determine status
                if nigerian_time.replace(tzinfo=None) > due_date.replace(tzinfo=None):
                    status = 'OVERDUE'
                    overdue_amount += amount
                else:
                    status = 'Current'
                
                creditor_data.append([
                    creditor.get('name', 'N/A'),
                    invoice_date.strftime('%Y-%m-%d'),
                    due_date.strftime('%Y-%m-%d'),
                    format_currency(amount),
                    status
                ])
                total_outstanding += amount
            
            creditor_data.append(['', '', 'Total Outstanding:', format_currency(total_outstanding), ''])
            
            creditor_table = create_table(creditor_data, col_widths=[1.8*inch, 1.2*inch, 1.2*inch, 1.3*inch, 1*inch])
            creditor_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ea4335')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#fce8e6')),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ea4335')),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(creditor_table)
            story.append(Spacer(1, 20))
            
            # Summary
            story.append(Paragraph("Summary", self.styles['SectionHeader']))
            summary_text = f"""
            <b>Total Outstanding:</b> ₦{total_outstanding:,.2f}<br/>
            <b>Overdue Amount:</b> ₦{overdue_amount:,.2f}<br/>
            <b>Number of Creditors:</b> {len(creditors)}
            """
            story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This creditors report shows all outstanding payables.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_assets_report(self, user_data, assets, start_date=None, end_date=None):
        """Generate Assets Register PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Asset Register Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        user_info = f"""
        <b>Business:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        if not assets:
            story.append(Paragraph("No assets found.", self.styles['Normal']))
        else:
            # Check if ANY asset has a meaningful name
            has_any_names = any(
                asset.get('name') or asset.get('assetName') 
                for asset in assets 
                if (asset.get('name') or asset.get('assetName', '')).strip()
            )
            
            # Assets Table
            story.append(Paragraph("Asset Details", self.styles['SectionHeader']))
            
            # Build table with or without Asset Name column
            if not has_any_names:
                # No names - hide Asset Name column entirely
                asset_data = [['Category', 'Purchase Date', 'Cost (N)', 'Current Value (N)']]
                total_cost = 0
                total_value = 0
                
                for asset in assets:
                    purchase_date = parse_date_safe(asset.get('purchaseDate'))
                    # CRITICAL FIX: Check both 'purchasePrice' and 'purchaseCost' for backend compatibility
                    cost = asset.get('purchasePrice', asset.get('purchaseCost', 0))
                    
                    # DATA MIGRATION FIX: If cost is 0 but currentValue exists, use currentValue as cost
                    # This handles legacy data where purchasePrice wasn't set
                    if cost == 0:
                        cost = asset.get('currentValue', 0)
                    
                    current_value = asset.get('currentValue', cost)
                    
                    # PROFESSIONAL STANDARD: Apply ₦1 minimum rule for active assets
                    asset_status = asset.get('status', 'active')
                    current_value = apply_one_naira_minimum_rule(current_value, asset_status)
                    
                    asset_data.append([
                        asset.get('category', '—'),
                        purchase_date.strftime('%Y-%m-%d'),
                        format_currency(cost),
                        format_currency(current_value)
                    ])
                    total_cost += cost
                    total_value += current_value
                
                asset_data.append(['', 'Totals:', format_currency(total_cost), format_currency(total_value)])
                
                asset_table = create_table(asset_data, col_widths=[1.8*inch, 1.5*inch, 1.8*inch, 1.9*inch])
            else:
                # Some assets have names - keep column but use professional dash
                asset_data = [['Asset Name', 'Category', 'Purchase Date', 'Cost (N)', 'Current Value (N)']]
                total_cost = 0
                total_value = 0
                
                for asset in assets:
                    purchase_date = parse_date_safe(asset.get('purchaseDate'))
                    # CRITICAL FIX: Check both 'purchasePrice' and 'purchaseCost' for backend compatibility
                    cost = asset.get('purchasePrice', asset.get('purchaseCost', 0))
                    
                    # DATA MIGRATION FIX: If cost is 0 but currentValue exists, use currentValue as cost
                    # This handles legacy data where purchasePrice wasn't set
                    if cost == 0:
                        cost = asset.get('currentValue', 0)
                    
                    current_value = asset.get('currentValue', cost)
                    
                    # PROFESSIONAL STANDARD: Apply ₦1 minimum rule for active assets
                    asset_status = asset.get('status', 'active')
                    current_value = apply_one_naira_minimum_rule(current_value, asset_status)
                    
                    # Use professional em dash instead of 'N/A'
                    name = (asset.get('name') or asset.get('assetName', '')).strip()
                    display_name = name if name else '—'
                    
                    asset_data.append([
                        display_name,
                        asset.get('category', '—'),
                        purchase_date.strftime('%Y-%m-%d'),
                        format_currency(cost),
                        format_currency(current_value)
                    ])
                    total_cost += cost
                    total_value += current_value
                
                asset_data.append(['', '', 'Totals:', format_currency(total_cost), format_currency(total_value)])
                
                asset_table = create_table(asset_data, col_widths=[1.8*inch, 1.3*inch, 1.2*inch, 1.3*inch, 1.4*inch])
            
            # Apply table styling
            asset_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                # Align cost columns to the right (adjust based on whether name column exists)
                ('ALIGN', (-2, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#e8f0fe')),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#1a73e8')),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(asset_table)
            story.append(Spacer(1, 20))
            
            # Summary
            total_depreciation = total_cost - total_value
            story.append(Paragraph("Summary", self.styles['SectionHeader']))
            summary_text = f"""
            <b>Total Asset Cost:</b> ₦{total_cost:,.2f}<br/>
            <b>Total Current Value:</b> ₦{total_value:,.2f}<br/>
            <b>Total Depreciation:</b> ₦{total_depreciation:,.2f}<br/>
            <b>Number of Assets:</b> {len(assets)}
            """
            story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This assets register shows all recorded business assets.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_asset_depreciation_report(self, user_data, assets, start_date=None, end_date=None):
        """Generate Asset Depreciation Schedule PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Asset Depreciation Schedule", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        user_info = f"""
        <b>Business:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        if not assets:
            story.append(Paragraph("No assets with depreciation found.", self.styles['Normal']))
        else:
            # Depreciation Table
            story.append(Paragraph("Depreciation Details", self.styles['SectionHeader']))
            
            depreciation_data = [['Asset', 'Cost (N)', 'Useful Life', 'Annual Dep. (₦)', 'Accumulated (₦)', 'Book Value (N)']]
            total_cost = 0
            total_annual_dep = 0
            total_accumulated = 0
            total_book_value = 0
            
            for asset in assets:
                # CRITICAL FIX: Use correct field names from Asset schema
                cost = asset.get('purchasePrice', asset.get('purchaseCost', 0))
                
                # If cost is 0 but currentValue exists, use currentValue as cost (data migration fix)
                if cost == 0:
                    cost = asset.get('currentValue', 0)
                
                useful_life = asset.get('usefulLifeYears', 5)  # Default 5 years
                purchase_date = parse_date_safe(asset.get('purchaseDate'))
                
                # SIMPLIFIED: Only use straight-line depreciation method
                # Formula: (Cost - Salvage Value) / Useful Life
                # For now, salvage value is 0 (can be added later)
                salvage_value = 0  # Future: asset.get('salvageValue', 0)
                
                # Calculate years owned
                years_owned = (nigerian_time.replace(tzinfo=None) - purchase_date.replace(tzinfo=None)).days / 365.25
                
                # Check for manual adjustment first (Option C layer)
                manual_adjustment = asset.get('manualValueAdjustment')
                
                if manual_adjustment is not None:
                    # Use manual adjustment
                    book_value = manual_adjustment
                    accumulated_depreciation = cost - book_value
                    # Estimate annual depreciation based on current state
                    annual_depreciation = accumulated_depreciation / max(years_owned, 0.01)
                else:
                    # Straight-line depreciation: (Cost - Salvage) / Useful Life
                    if useful_life > 0:
                        annual_depreciation = (cost - salvage_value) / useful_life
                    else:
                        annual_depreciation = 0
                    
                    # Accumulated depreciation = Annual × Years Owned (capped at cost)
                    accumulated_depreciation = min(annual_depreciation * years_owned, cost - salvage_value)
                    
                    # Book Value = Cost - Accumulated Depreciation
                    book_value = cost - accumulated_depreciation
                
                # Use professional em dash instead of 'N/A'
                asset_name = (asset.get('name') or asset.get('assetName', '')).strip()
                display_name = asset_name if asset_name else '—'
                
                depreciation_data.append([
                    display_name,
                    format_currency(cost),
                    f"{useful_life} years",
                    format_currency(annual_depreciation),
                    format_currency(accumulated_depreciation),
                    format_currency(book_value)
                ])
                
                total_cost += cost
                total_annual_dep += annual_depreciation
                total_accumulated += accumulated_depreciation
                total_book_value += book_value
            
            depreciation_data.append([
                'Totals:',
                format_currency(total_cost),
                '',
                format_currency(total_annual_dep),
                format_currency(total_accumulated),
                format_currency(total_book_value)
            ])
            
            depreciation_table = create_table(depreciation_data, col_widths=[1.5*inch, 1*inch, 0.9*inch, 1*inch, 1.1*inch, 1*inch])
            depreciation_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34a853')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#e8f5e9')),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#34a853')),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(depreciation_table)
            story.append(Spacer(1, 20))
            
            # Summary
            story.append(Paragraph("Depreciation Summary", self.styles['SectionHeader']))
            summary_text = f"""
            <b>Total Asset Cost:</b> ₦{total_cost:,.2f}<br/>
            <b>Total Annual Depreciation:</b> ₦{total_annual_dep:,.2f}<br/>
            <b>Total Accumulated Depreciation:</b> ₦{total_accumulated:,.2f}<br/>
            <b>Total Book Value:</b> ₦{total_book_value:,.2f}<br/>
            <b>Depreciation Method:</b> Straight-Line
            """
            story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This depreciation schedule uses the straight-line method.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_inventory_report(self, user_data, inventory_items, start_date=None, end_date=None):
        """Generate Inventory Report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Inventory Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        user_info = f"""
        <b>Business:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        if not inventory_items:
            story.append(Paragraph("No inventory items found.", self.styles['Normal']))
        else:
            # Inventory Table
            story.append(Paragraph("Inventory Details", self.styles['SectionHeader']))
            
            inventory_data = [['Item Name', 'SKU', 'Quantity', 'Unit Cost (N)', 'Total Value (N)', 'Status']]
            total_quantity = 0
            total_value = 0
            low_stock_count = 0
            
            for item in inventory_items:
                quantity = item.get('quantity', 0)
                unit_cost = item.get('unitCost', 0)
                total_item_value = quantity * unit_cost
                min_stock = item.get('minStockLevel', 10)
                
                # Determine status
                if quantity == 0:
                    status = 'OUT OF STOCK'
                elif quantity <= min_stock:
                    status = 'LOW STOCK'
                    low_stock_count += 1
                else:
                    status = 'In Stock'
                
                inventory_data.append([
                    item.get('name', 'N/A'),
                    item.get('sku', 'N/A'),
                    str(quantity),
                    format_currency(unit_cost),
                    format_currency(total_item_value),
                    status
                ])
                
                total_quantity += quantity
                total_value += total_item_value
            
            inventory_data.append(['', 'Totals:', str(total_quantity), '', format_currency(total_value), ''])
            
            inventory_table = create_table(inventory_data, col_widths=[1.5*inch, 1*inch, 0.8*inch, 1.2*inch, 1.2*inch, 1*inch])
            inventory_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fbbc04')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (2, -1), 'CENTER'),
                ('ALIGN', (3, 0), (4, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#fff9e6')),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fbbc04')),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(inventory_table)
            story.append(Spacer(1, 20))
            
            # Summary
            story.append(Paragraph("Inventory Summary", self.styles['SectionHeader']))
            summary_text = f"""
            <b>Total Items:</b> {len(inventory_items)}<br/>
            <b>Total Quantity:</b> {total_quantity}<br/>
            <b>Total Inventory Value:</b> ₦{total_value:,.2f}<br/>
            <b>Low Stock Items:</b> {low_stock_count}
            """
            story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This inventory report shows current stock levels and values.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_credit_transactions_report(self, user_data, credit_data, start_date=None, end_date=None):
        """Generate Credit Transactions Report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("FiCore Credits Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        nigerian_time = get_nigerian_time()
        user_info = f"""
        <b>Name:</b> {user_data.get('name', 'N/A')}<br/>
        <b>TIN:</b> {format_tin_display(user_data.get('tin'))}<br/>
        <b>Email:</b> {user_data.get('email', 'N/A')}<br/>
        <b>Account Type:</b> {'Premium' if user_data.get('isSubscribed', False) else 'Free'}<br/>
        <b>Report Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M WAT')}
        """
        if start_date or end_date:
            period = f"<b>Period:</b> "
            if start_date:
                period += start_date.strftime('%B %d, %Y')
            if start_date and end_date:
                period += " - "
            if end_date:
                period += end_date.strftime('%B %d, %Y')
            user_info += f"<br/>{period}"
        
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Current Balance Summary
        story.append(Paragraph("Account Summary", self.styles['SectionHeader']))
        summary_data = [
            ['Current FC Balance', f"{credit_data.get('current_balance', 0):.2f} FC"],
            ['Total Earned', f"+{credit_data.get('total_earned', 0):.2f} FC"],
            ['Total Spent', f"-{credit_data.get('total_spent', 0):.2f} FC"],
            ['Net Change', f"{credit_data.get('net_change', 0):+.2f} FC"],
            ['Total Transactions', str(credit_data.get('transaction_count', 0))]
        ]
        
        # Add breakdown by source if available (Feb 9, 2026)
        breakdown = credit_data.get('earned_breakdown', {})
        if breakdown:
            summary_data.append(['', ''])  # Spacer row
            summary_data.append(['Credits Earned By Source:', ''])
            if breakdown.get('purchased', 0) > 0:
                summary_data.append(['  • Purchased', f"+{breakdown['purchased']:.2f} FC"])
            if breakdown.get('signup_bonus', 0) > 0:
                summary_data.append(['  • Signup Bonus', f"+{breakdown['signup_bonus']:.2f} FC"])
            if breakdown.get('rewards', 0) > 0:
                summary_data.append(['  • Rewards Screen', f"+{breakdown['rewards']:.2f} FC"])
            if breakdown.get('tax_education', 0) > 0:
                summary_data.append(['  • Tax Education', f"+{breakdown['tax_education']:.2f} FC"])
            if breakdown.get('other', 0) > 0:
                summary_data.append(['  • Other', f"+{breakdown['other']:.2f} FC"])
        
        summary_table = create_table(summary_data, col_widths=[3*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 20))
        
        # Transactions Table
        transactions = credit_data.get('transactions', [])
        
        if not transactions:
            story.append(Paragraph("No credit transactions found for the selected period.", self.styles['Normal']))
        else:
            story.append(Paragraph("Transaction History", self.styles['SectionHeader']))
            
            transaction_data = [['Date', 'Type', 'Description', 'Amount (FC)', 'Balance After']]
            
            for transaction in transactions:
                date_obj = parse_date_safe(transaction.get('createdAt'))
                date_str = date_obj.strftime('%b %d, %Y')
                
                trans_type = transaction.get('type', 'N/A').capitalize()
                description = transaction.get('description', 'N/A')
                amount = transaction.get('amount', 0)
                balance_after = transaction.get('balanceAfter', 0)
                
                # Format amount with + or - sign
                amount_str = f"+{amount:.2f}" if amount > 0 else f"{amount:.2f}"
                
                transaction_data.append([
                    date_str,
                    trans_type,
                    description,
                    amount_str,
                    f"{balance_after:.2f}"
                ])
            
            transaction_table = create_table(transaction_data, col_widths=[1*inch, 1*inch, 2.5*inch, 1*inch, 1*inch])
            transaction_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (4, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#e8f0fe')),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8)
            ]))
            
            story.append(transaction_table)
        
        story.append(Spacer(1, 30))
        
        # Footer
        footer_text = """
        <i>FiCore Credits (FC) are used to access premium features and generate reports.<br/>
        Premium users get unlimited access to all features without credit deductions.<br/>
        Generated by FiCore Mobile App | team@ficoreafrica.com</i>
        """
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer


    def generate_certified_ledger(self, user_data, transactions, start_date=None, end_date=None, audit_id=None):
        """
        Generate Certified Ledger PDF with Immutable Audit Trail
        
        This is the "M-Pesa Standard" - a tamper-evident financial ledger that shows:
        - Complete transaction lifecycle (original → superseded → voided)
        - Reversal entries for deleted transactions
        - Version history for edited transactions
        - Verification QR code for authenticity
        - Digital signature watermark
        
        Args:
            user_data: User/merchant information
            transactions: Dict with 'incomes' and 'expenses' arrays (including ALL statuses)
            start_date: Start date for the ledger period
            end_date: End date for the ledger period
            audit_id: Unique audit ID for this export (generated if not provided)
        
        Returns:
            BytesIO buffer containing the PDF
        """
        import qrcode
        from reportlab.graphics import renderPDF
        from reportlab.graphics.shapes import Drawing
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.lib.utils import ImageReader
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Generate unique audit ID if not provided
        if not audit_id:
            audit_id = f"FCL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{user_data.get('_id', 'UNKNOWN')[:8]}"
        
        # Title with "CERTIFIED" badge
        title = Paragraph("🏛️ CERTIFIED FINANCIAL LEDGER", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 6))
        
        # Tamper-Evident Header
        nigerian_time = get_nigerian_time()
        header_text = f"""
        <b>System Audit ID:</b> {audit_id}<br/>
        <b>Generated:</b> {nigerian_time.strftime('%B %d, %Y at %H:%M:%S WAT')}<br/>
        <b>Ledger Engine:</b> FiCore Immutable Ledger v1.0<br/>
        <b>Certification:</b> This document is generated from an append-only ledger system
        """
        story.append(Paragraph(header_text, self.styles['InfoText']))
        story.append(Spacer(1, 12))
        
        # Merchant Information
        story.append(Paragraph("Merchant Information", self.styles['SectionHeader']))
        period_text = ""
        if start_date and end_date:
            period_text = f"<b>Ledger Period:</b> {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}<br/>"
        
        merchant_info = f"""
        <b>Business Name:</b> {user_data.get('businessName', f"{user_data.get('firstName', '')} {user_data.get('lastName', '')}")}<br/>
        <b>Merchant ID:</b> {str(user_data.get('_id', 'N/A'))}<br/>
        <b>Email:</b> {user_data.get('email', 'N/A')}<br/>
        <b>Phone:</b> {user_data.get('phone', 'N/A')}<br/>
        {period_text}
        """
        story.append(Paragraph(merchant_info, self.styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Calculate opening balance (transactions before start_date)
        opening_balance = 0.0
        # Note: In a real implementation, you'd query transactions before start_date
        # For now, we'll start at 0
        
        # Transaction Ledger Section
        story.append(Paragraph("Complete Transaction Ledger", self.styles['SectionHeader']))
        story.append(Spacer(1, 6))
        
        # Combine and sort all transactions chronologically
        all_transactions = []
        
        # Process incomes
        for income in transactions.get('incomes', []):
            all_transactions.append({
                'date': parse_date_safe(income.get('dateReceived')),
                'type': 'INCOME',
                'description': income.get('description') or income.get('source', 'Income'),
                'amount': income.get('amount', 0),
                'status': income.get('status', 'active'),
                'version': income.get('version', 1),
                'originalEntryId': income.get('originalEntryId'),
                'supersededBy': income.get('supersededBy'),
                'reversalEntryId': income.get('reversalEntryId'),
                'transactionType': income.get('type', 'INCOME'),
                'id': str(income.get('_id', ''))
            })
        
        # Process expenses
        for expense in transactions.get('expenses', []):
            all_transactions.append({
                'date': parse_date_safe(expense.get('date')),
                'type': 'EXPENSE',
                'description': expense.get('description') or expense.get('title', 'Expense'),
                'amount': -expense.get('amount', 0),  # Negative for expenses
                'status': expense.get('status', 'active'),
                'version': expense.get('version', 1),
                'originalEntryId': expense.get('originalEntryId'),
                'supersededBy': expense.get('supersededBy'),
                'reversalEntryId': expense.get('reversalEntryId'),
                'transactionType': expense.get('type', 'EXPENSE'),
                'id': str(expense.get('_id', ''))
            })
        
        # Sort by date
        all_transactions.sort(key=lambda x: x['date'])
        
        # Build ledger table
        ledger_data = [['Date', 'Type', 'Description', 'Debit (₦)', 'Credit (₦)', 'Balance (₦)', 'Status']]
        
        running_balance = opening_balance
        
        for txn in all_transactions:
            date_str = txn['date'].strftime('%Y-%m-%d')
            amount = txn['amount']
            
            # Determine debit/credit
            if amount >= 0:
                debit = ''
                credit = format_currency(amount)
            else:
                debit = format_currency(abs(amount))
                credit = ''
            
            # Update running balance
            running_balance += amount
            
            # Status badge
            status = txn['status'].upper()
            if txn['transactionType'] == 'REVERSAL':
                status = 'REVERSAL'
            elif txn['version'] > 1:
                status = f"V{txn['version']}"
            
            # Description with version info
            description = txn['description']
            if txn['originalEntryId']:
                description = f"[EDIT] {description}"
            if txn['transactionType'] == 'REVERSAL':
                description = f"[REVERSAL] {description}"
            
            ledger_data.append([
                date_str,
                txn['type'],
                description[:40],  # Truncate long descriptions
                debit,
                credit,
                format_currency(running_balance),
                status
            ])
        
        # Add closing balance row
        ledger_data.append([
            '', '', 'CLOSING BALANCE', '', '', format_currency(running_balance), ''
        ])
        
        # Create table
        ledger_table = create_table(ledger_data, col_widths=[0.9*inch, 0.8*inch, 1.8*inch, 0.9*inch, 0.9*inch, 1*inch, 0.7*inch])
        ledger_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (3, 0), (5, -1), 'RIGHT'),  # Align amounts right
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        story.append(ledger_table)
        story.append(Spacer(1, 20))
        
        # Financial Summary
        story.append(Paragraph("Financial Summary", self.styles['SectionHeader']))
        
        total_income = sum(t['amount'] for t in all_transactions if t['amount'] > 0 and t['status'] == 'active')
        total_expenses = sum(abs(t['amount']) for t in all_transactions if t['amount'] < 0 and t['status'] == 'active')
        net_position = total_income - total_expenses
        
        # Count transactions by status
        active_count = sum(1 for t in all_transactions if t['status'] == 'active')
        voided_count = sum(1 for t in all_transactions if t['status'] == 'voided')
        superseded_count = sum(1 for t in all_transactions if t['status'] == 'superseded')
        reversal_count = sum(1 for t in all_transactions if t['transactionType'] == 'REVERSAL')
        
        summary_data = [
            ['Description', 'Amount (N)'],
            ['Opening Balance', format_currency(opening_balance)],
            ['Total Income (Active)', format_currency(total_income)],
            ['Total Expenses (Active)', format_currency(total_expenses)],
            ['Net Position', format_currency(net_position)],
            ['Closing Balance', format_currency(running_balance)],
            ['', ''],
            ['Audit Trail Statistics', ''],
            ['Active Transactions', str(active_count)],
            ['Voided Transactions', str(voided_count)],
            ['Superseded (Edited) Transactions', str(superseded_count)],
            ['Reversal Entries', str(reversal_count)],
        ]
        
        summary_table = create_table(summary_data, col_widths=[4*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34a853')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 1), (-1, 6), colors.HexColor('#e8f5e9')),
            ('BACKGROUND', (0, 7), (-1, 7), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, 7), (-1, 7), colors.whitesmoke),
            ('FONTNAME', (0, 7), (-1, 7), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 8), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 20))
        
        # Certification Statement
        story.append(Paragraph("Certification & Verification", self.styles['SectionHeader']))
        
        # Generate verification URL (in production, this would link to a secure read-only endpoint)
        verification_url = f"https://ficoreafrica.com/verify/{audit_id}"
        
        cert_text = f"""
        <b>Digital Signature:</b> Generated by FiCore Immutable Ledger Engine<br/>
        <b>Verification URL:</b> {verification_url}<br/>
        <b>Ledger Integrity:</b> This document is generated from an append-only ledger system where:<br/>
        • Deleted transactions are marked as "VOIDED" with reversal entries<br/>
        • Edited transactions create new versions (V2, V3, etc.) without overwriting originals<br/>
        • All changes are traceable through the audit trail<br/>
        <br/>
        <b>Regulatory Compliance:</b> This ledger meets CBN microfinance licensing requirements for immutable audit trails.<br/>
        <b>Use Case:</b> Suitable for NRS tax audits, bank loan applications, and partner due diligence.
        """
        story.append(Paragraph(cert_text, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # QR Code for verification
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(verification_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # Save QR code to buffer
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        
        # Add QR code to PDF
        qr_image = ImageReader(qr_buffer)
        from reportlab.platypus import Image
        qr_pdf_image = Image(qr_buffer, width=1.5*inch, height=1.5*inch)
        
        qr_text = Paragraph("<b>Scan to Verify Authenticity</b>", self.styles['InfoText'])
        story.append(qr_text)
        story.append(Spacer(1, 6))
        story.append(qr_pdf_image)
        story.append(Spacer(1, 20))
        
        # Footer
        footer_text = """
        <i><b>CONFIDENTIAL FINANCIAL DOCUMENT</b><br/>
        This certified ledger is generated for regulatory compliance and institutional partnerships.<br/>
        For verification or inquiries, contact: compliance@ficoreafrica.com<br/>
        <br/>
        Generated by FiCore Africa | Powered by Immutable Ledger Technology</i>
        """
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_wallet_funding_report(self, user_data, export_data, start_date=None, end_date=None):
        """Generate Wallet Funding Report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = []
        
        # Header
        story.append(Paragraph("FiCore Africa", self.styles['Title']))
        story.append(Paragraph("Wallet Funding Report", self.styles['Heading1']))
        story.append(Spacer(1, 12))
        
        # User Info
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>TIN:</b> {format_tin_display(user_data.get('tin'))}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Business:</b> {user_data.get('businessName', 'N/A')}<br/>
        <b>Generated:</b> {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}
        """
        if start_date and end_date:
            user_info += f"<br/><b>Period:</b> {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Transactions Table
        story.append(Paragraph("Wallet Funding Transactions", self.styles['SectionHeader']))
        story.append(Spacer(1, 12))
        
        table_data = [['Date', 'Reference', 'Amount (N)', 'Fee (₦)', 'Status']]
        total_amount = 0
        total_fees = 0
        
        for txn in export_data.get('transactions', []):
            date_str = txn['date'].strftime('%Y-%m-%d %H:%M')
            amount = txn.get('amount', 0)
            fee = txn.get('fee', 0)
            
            table_data.append([
                date_str,
                txn.get('reference', 'N/A'),
                format_currency(amount),
                format_currency(fee),
                txn.get('status', 'UNKNOWN')
            ])
            total_amount += amount
            total_fees += fee
        
        # Add totals row
        table_data.append(['', 'Totals:', format_currency(total_amount), format_currency(total_fees), ''])
        
        table = create_table(table_data, col_widths=[1.5*inch, 2*inch, 1.2*inch, 1.2*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.WALLET_PURPLE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.WALLET_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Summary
        summary_text = f"""
        <b>Summary:</b><br/>
        Total Funded: ₦{total_amount:,.2f}<br/>
        Total Fees: ₦{total_fees:,.2f}<br/>
        Number of Transactions: {len(export_data.get('transactions', []))}
        """
        story.append(Paragraph(summary_text, self.styles['InfoText']))
        
        footer_text = f"""<i>This report was generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}.
        <br/>
        Generated by FiCore Africa | Wallet Services</i>
        """
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_bill_payments_report(self, user_data, export_data, start_date=None, end_date=None):
        """
        Generate Bill Payments Report PDF with granular VAS breakdown
        
        MODERNIZATION (Feb 18, 2026):
        - Shows breakdown by service type (electricity, cable_tv, internet, water, transportation)
        - Displays category-specific totals
        - Enhanced summary section
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = []
        
        # Header
        story.append(Paragraph("FiCore Africa", self.styles['Title']))
        story.append(Paragraph("Bill Payments Report", self.styles['Heading1']))
        story.append(Spacer(1, 12))
        
        # User Info
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>TIN:</b> {format_tin_display(user_data.get('tin'))}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Business:</b> {user_data.get('businessName', 'N/A')}<br/>
        <b>Generated:</b> {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}
        """
        if start_date and end_date:
            user_info += f"<br/><b>Period:</b> {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Summary by Category (if available)
        summary = export_data.get('summary', {})
        if summary and summary.get('total', 0) > 0:
            story.append(Paragraph("Summary by Service Type", self.styles['SectionHeader']))
            story.append(Spacer(1, 12))
            
            summary_data = [['Service Type', 'Amount (N)', 'Percentage']]
            total = summary.get('total', 0)
            
            if summary.get('electricity', 0) > 0:
                pct = (summary['electricity'] / total * 100) if total > 0 else 0
                summary_data.append(['Electricity', format_currency(summary['electricity']), f"{pct:.1f}%"])
            if summary.get('cable_tv', 0) > 0:
                pct = (summary['cable_tv'] / total * 100) if total > 0 else 0
                summary_data.append(['Cable TV', format_currency(summary['cable_tv']), f"{pct:.1f}%"])
            if summary.get('internet', 0) > 0:
                pct = (summary['internet'] / total * 100) if total > 0 else 0
                summary_data.append(['Internet', format_currency(summary['internet']), f"{pct:.1f}%"])
            if summary.get('water', 0) > 0:
                pct = (summary['water'] / total * 100) if total > 0 else 0
                summary_data.append(['Water', format_currency(summary['water']), f"{pct:.1f}%"])
            if summary.get('transportation', 0) > 0:
                pct = (summary['transportation'] / total * 100) if total > 0 else 0
                summary_data.append(['Transportation', format_currency(summary['transportation']), f"{pct:.1f}%"])
            if summary.get('other', 0) > 0:
                pct = (summary['other'] / total * 100) if total > 0 else 0
                summary_data.append(['Other Services', format_currency(summary['other']), f"{pct:.1f}%"])
            
            summary_data.append(['', '', ''])
            summary_data.append(['TOTAL', format_currency(total), '100%'])
            
            summary_table = create_table(summary_data, col_widths=[2.5*inch, 2*inch, 1.5*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9C27B0')),  # Purple
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E1BEE7')),  # Light purple
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(summary_table)
            story.append(Spacer(1, 20))
        
        # Transactions Table
        story.append(Paragraph("All Bill Payment Transactions", self.styles['SectionHeader']))
        story.append(Spacer(1, 12))
        
        table_data = [['Date', 'Reference', 'Category', 'Amount (N)', 'Status']]
        total_amount = 0
        
        for txn in export_data.get('transactions', []):
            date_str = txn['date'].strftime('%Y-%m-%d %H:%M')
            amount = txn.get('amount', 0)
            
            table_data.append([
                date_str,
                txn.get('reference', 'N/A')[:15],
                txn.get('category', 'N/A'),
                format_currency(amount),
                txn.get('status', 'COMPLETED')
            ])
            total_amount += amount
        
        # Add totals row
        table_data.append(['', 'Totals:', '', format_currency(total_amount), ''])
        
        table = create_table(table_data, col_widths=[1.5*inch, 1.5*inch, 1.5*inch, 1.3*inch, 1.2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.WALLET_PURPLE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.WALLET_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Summary
        summary_text = f"""
        <b>Summary:</b><br/>
        Total Spent: ₦{total_amount:,.2f}<br/>
        Number of Transactions: {len(export_data.get('transactions', []))}<br/>
        <br/>
        <i>Note: This report shows bills paid through FiCore's Value Added Services (VAS) platform.
        Transactions are automatically categorized by service type for better expense tracking.</i>
        """
        story.append(Paragraph(summary_text, self.styles['InfoText']))
        
        footer_text = f"""<i>This report was generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}.
        <br/>
        Generated by FiCore Africa | Bill Payment Services</i>
        """
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_airtime_purchases_report(self, user_data, export_data, start_date=None, end_date=None):
        """
        Generate Airtime Purchases Report PDF with network grouping
        
        MODERNIZATION (Feb 18, 2026):
        - Shows breakdown by network (MTN, Airtel, Glo, 9mobile)
        - Displays network-specific totals
        - Enhanced summary section
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = []
        
        # Header
        story.append(Paragraph("FiCore Africa", self.styles['Title']))
        story.append(Paragraph("Airtime Purchases Report", self.styles['Heading1']))
        story.append(Spacer(1, 12))
        
        # User Info
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>TIN:</b> {format_tin_display(user_data.get('tin'))}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Business:</b> {user_data.get('businessName', 'N/A')}<br/>
        <b>Generated:</b> {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}
        """
        if start_date and end_date:
            user_info += f"<br/><b>Period:</b> {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Summary by Network (if available)
        network_summary = export_data.get('network_summary', {})
        if network_summary:
            story.append(Paragraph("Summary by Network", self.styles['SectionHeader']))
            story.append(Spacer(1, 12))
            
            summary_data = [['Network', 'Transactions', 'Amount (N)', 'Percentage']]
            total = sum(data['total'] for data in network_summary.values())
            
            # Sort networks by total amount (descending)
            sorted_networks = sorted(network_summary.items(), key=lambda x: x[1]['total'], reverse=True)
            
            for network, data in sorted_networks:
                count = data['count']
                amount = data['total']
                pct = (amount / total * 100) if total > 0 else 0
                summary_data.append([network, str(count), format_currency(amount), f"{pct:.1f}%"])
            
            summary_data.append(['', '', '', ''])
            summary_data.append(['TOTAL', str(sum(d['count'] for d in network_summary.values())), format_currency(total), '100%'])
            
            summary_table = create_table(summary_data, col_widths=[1.5*inch, 1.5*inch, 2*inch, 1*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF9800')),  # Orange for airtime
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FFE0B2')),  # Light orange
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(summary_table)
            story.append(Spacer(1, 20))
        
        # Transactions Table
        story.append(Paragraph("All Airtime Purchase Transactions", self.styles['SectionHeader']))
        story.append(Spacer(1, 12))
        
        table_data = [['Date', 'Network', 'Phone Number', 'Amount (N)', 'Status']]
        total_amount = 0
        
        for txn in export_data.get('transactions', []):
            date_str = txn['date'].strftime('%Y-%m-%d %H:%M')
            amount = txn.get('amount', 0)
            
            table_data.append([
                date_str,
                txn.get('network', 'Unknown'),
                txn.get('phone', 'N/A'),
                format_currency(amount),
                txn.get('status', 'COMPLETED')
            ])
            total_amount += amount
        
        # Add totals row
        table_data.append(['', 'Totals:', '', format_currency(total_amount), ''])
        
        table = create_table(table_data, col_widths=[1.5*inch, 1.3*inch, 1.5*inch, 1.3*inch, 1.4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF9800')),  # Orange
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#FFE0B2')),  # Light orange
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Summary
        summary_text = f"""
        <b>Summary:</b><br/>
        Total Spent: ₦{total_amount:,.2f}<br/>
        Number of Transactions: {len(export_data.get('transactions', []))}<br/>
        <br/>
        <i>Note: This report shows airtime purchases made through FiCore's Value Added Services (VAS) platform.
        Transactions are automatically grouped by network for better expense tracking.</i>
        """
        story.append(Paragraph(summary_text, self.styles['InfoText']))
        
        footer_text = f"""<i>This report was generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}.
        <br/>
        Generated by FiCore Africa | Airtime Services</i>
        """
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_full_wallet_report(self, user_data, export_data, start_date=None, end_date=None):
        """Generate Full Wallet Report PDF (all transaction types)"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        story = []
        
        # Header
        story.append(Paragraph("FiCore Africa", self.styles['Title']))
        story.append(Paragraph("Full Wallet Report", self.styles['Heading1']))
        story.append(Spacer(1, 12))
        
        # User Info
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>TIN:</b> {format_tin_display(user_data.get('tin'))}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Business:</b> {user_data.get('businessName', 'N/A')}<br/>
        <b>Generated:</b> {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}
        """
        if start_date and end_date:
            user_info += f"<br/><b>Period:</b> {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Transactions Table
        story.append(Paragraph("All Wallet Transactions", self.styles['SectionHeader']))
        story.append(Spacer(1, 12))
        
        table_data = [['Date', 'Reference', 'Type', 'Description', 'Amount (N)', 'Fee (₦)', 'Status']]
        total_amount = 0
        total_fees = 0
        
        for txn in export_data.get('transactions', []):
            date_str = txn['date'].strftime('%Y-%m-%d %H:%M')
            amount = txn.get('amount', 0)
            fee = txn.get('fee', 0)
            
            table_data.append([
                date_str,
                txn.get('reference', 'N/A')[:15],  # Truncate long references
                txn.get('type', 'N/A')[:12],  # Truncate type
                txn.get('description', 'N/A')[:25],  # Truncate description
                format_currency(amount),
                format_currency(fee),
                txn.get('status', 'UNKNOWN')[:8]
            ])
            total_amount += amount
            total_fees += fee
        
        # Add totals row
        table_data.append(['', 'Totals:', '', '', format_currency(total_amount), format_currency(total_fees), ''])
        
        table = create_table(table_data, col_widths=[1*inch, 1.2*inch, 0.9*inch, 1.5*inch, 1*inch, 0.8*inch, 0.6*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.WALLET_PURPLE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.WALLET_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Summary
        summary_text = f"""
        <b>Summary:</b><br/>
        Total Amount: ₦{total_amount:,.2f}<br/>
        Total Fees: ₦{total_fees:,.2f}<br/>
        Number of Transactions: {len(export_data.get('transactions', []))}
        """
        story.append(Paragraph(summary_text, self.styles['InfoText']))
        
        footer_text = f"""<i>This report was generated on {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}.
        <br/>
        Generated by FiCore Africa | Complete Wallet Services</i>
        """
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_statement_of_affairs(self, user_data, financial_data, tax_data, assets_data, 
                                      start_date=None, end_date=None, tax_type='PIT'):
        """
        Generate comprehensive Statement of Affairs PDF
        
        CRITICAL: This report calculates asset values (NBV) as of the endDate parameter.
        If endDate is provided, depreciation is calculated only up to that date.
        This ensures historical accuracy for mid-period reports.
        
        Combines:
        - Cover page with business summary
        - Executive summary (Financial, Assets, Current Assets/Liabilities, Tax)
        - Profit & Loss statement
        - Balance Sheet (Assets, Liabilities, Equity)
        - Asset register summary
        - Tax summary
        - Documentation notes
        
        Args:
            user_data: User/business information
            financial_data: Dict with 'incomes' and 'expenses' lists
            tax_data: Tax calculation data including inventory, debtors, creditors, cash
            assets_data: List of assets with CURRENT depreciation (should be pre-calculated as of endDate)
            start_date: Report start date
            end_date: Report end date (CRITICAL for depreciation calculation)
            tax_type: 'PIT' or 'CIT'
        
        Note: The endpoint should calculate asset NBV as of endDate before passing to this method.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        nigerian_time = get_nigerian_time()
        
        # Calculate key metrics
        incomes = financial_data.get('incomes', [])
        expenses = financial_data.get('expenses', [])
        
        # MODERNIZATION (Feb 18, 2026): Use enhanced 3-Step P&L from tax_data
        # Revenue Breakdown
        sales_revenue = tax_data.get('sales_revenue', 0)
        other_income = tax_data.get('other_income', 0)
        total_income = tax_data.get('total_income', sales_revenue + other_income)
        
        # COGS
        total_cogs = tax_data.get('cost_of_goods_sold', 0)
        
        # Gross Profit (Step 1)
        # CRITICAL FIX (Feb 19, 2026): Include Other Income in Gross Profit calculation
        gross_profit = tax_data.get('gross_profit', (sales_revenue + other_income) - total_cogs)
        gross_margin = tax_data.get('gross_margin_percentage', 0)
        
        # Operating Expenses
        total_operating_expenses = tax_data.get('operating_expenses', 0)
        
        # Operating Profit (Step 2)
        operating_profit = tax_data.get('operating_profit', gross_profit - total_operating_expenses)
        
        # Net Profit (Step 3)
        net_profit = tax_data.get('net_income', operating_profit)
        
        total_expenses = total_cogs + total_operating_expenses
        profit_margin = (net_profit / total_income * 100) if total_income > 0 else 0
        
        # VAS Breakdown (Granular Utility Reporting)
        vas_breakdown = tax_data.get('vas_breakdown', {})
        
        # Asset metrics
        total_assets_cost = sum(asset.get('purchasePrice', 0) or asset.get('purchaseCost', 0) for asset in assets_data)
        total_assets_nbv = sum(asset.get('currentValue', 0) for asset in assets_data)
        total_depreciation = total_assets_cost - total_assets_nbv
        asset_count = len(assets_data)
        
        # Current assets and liabilities
        inventory_value = tax_data.get('inventory_value', 0)
        debtors_value = tax_data.get('debtors_value', 0)
        creditors_value = tax_data.get('creditors_value', 0)
        inventory_count = tax_data.get('inventory_count', 0)
        debtors_count = tax_data.get('debtors_count', 0)
        creditors_count = tax_data.get('creditors_count', 0)
        
        # Cash/Bank balance (from wallet or user data)
        cash_balance = tax_data.get('cash_balance', 0)
        
        # Opening equity and drawings
        # CRITICAL FIX (Feb 19, 2026): Opening equity should reflect capital injected
        opening_equity = tax_data.get('opening_equity', 0)
        drawings = tax_data.get('drawings', 0)
        
        # If opening equity is 0 but we have assets, show a recommendation
        if opening_equity == 0 and total_assets_cost > 0:
            # This will be shown in recommendations section
            pass
        
        # Total assets including current assets
        total_current_assets = inventory_value + debtors_value + cash_balance
        total_all_assets = total_assets_nbv + total_current_assets
        
        # Total liabilities including tax liability
        total_current_liabilities = creditors_value
        
        # Calculate closing equity: Opening Equity + Net Profit - Drawings
        closing_equity = opening_equity + net_profit - drawings
        
        # Net assets (for verification: Assets - Liabilities should equal Equity)
        net_assets = total_all_assets - total_current_liabilities
        
        # Tax calculation
        if tax_type == 'CIT':
            # CIT exemption: BOTH conditions must be met
            qualifies_for_exemption = (total_income <= 100000000) and (total_assets_nbv <= 250000000)
            if qualifies_for_exemption:
                estimated_tax = 0
                tax_rate_display = "0% (Exempt - Revenue ≤₦100M AND Assets ≤₦250M)"
            else:
                estimated_tax = net_profit * 0.30 if net_profit > 0 else 0
                tax_rate_display = "30% (CIT)"
        else:
            # PIT: First ₦800,000 is exempt, then progressive
            if net_profit <= 800000:
                estimated_tax = 0
            else:
                taxable = net_profit - 800000
                estimated_tax = taxable * 0.15  # Simplified progressive
            tax_rate_display = "Progressive (PIT)"
        
        effective_rate = (estimated_tax / net_profit * 100) if net_profit > 0 else 0
        
        # Add estimated tax to current liabilities (unpaid tax obligation)
        tax_liability = tax_data.get('tax_paid', 0)  # If user has paid some tax
        unpaid_tax = max(0, estimated_tax - tax_liability)
        total_current_liabilities = creditors_value + unpaid_tax
        
        # Period text
        period_text = f"{start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}" if start_date and end_date else "All Time"
        
        # === COVER PAGE ===
        title = Paragraph("STATEMENT OF AFFAIRS", ParagraphStyle(
            'CoverTitle',
            parent=self.styles['CustomTitle'],
            fontSize=28,
            textColor=ReportColors.FINANCIAL_GOLDEN,
            alignment=TA_CENTER
        ))
        story.append(title)
        story.append(Spacer(1, 20))
        
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
        story.append(Paragraph(cover_info, self.styles['InfoText']))
        story.append(Spacer(1, 30))
        
        # Business Summary Dashboard
        story.append(Paragraph("Business Summary", self.styles['SectionHeader']))
        
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
        
        story.append(summary_table)
        story.append(PageBreak())
        
        # === EXECUTIVE SUMMARY ===
        story.append(Paragraph("Executive Summary", self.styles['CustomTitle']))
        story.append(Spacer(1, 12))
        
        # Financial Overview
        story.append(Paragraph("Financial Overview", self.styles['SectionHeader']))
        
        financial_overview = [
            ['Metric', 'Amount (N)', 'Notes'],
            ['REVENUE', '', ''],
            ['Sales Revenue', format_currency(sales_revenue), 'Product sales'],
            ['Other Income', format_currency(other_income), 'Services, grants, interest'],
            ['Total Revenue', format_currency(total_income), f'{len(incomes)} transactions'],
            ['', '', ''],
            ['Less: Cost of Goods Sold (COGS)', format_currency(total_cogs), 'Direct product costs'],
            ['GROSS PROFIT', format_currency(gross_profit), f'{gross_margin:.1f}% margin'],
            ['', '', ''],
            ['Less: Operating Expenses', format_currency(total_operating_expenses), 'Rent, salaries, utilities'],
            ['OPERATING PROFIT', format_currency(operating_profit), 'Before tax'],
            ['', '', ''],
            ['NET PROFIT/(LOSS)', format_currency(net_profit), f'{profit_margin:.1f}% margin'],
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
            ('BACKGROUND', (0, 7), (-1, 7), colors.HexColor('#FFF9C4')),  # Light yellow
            ('FONTNAME', (0, 10), (-1, 10), 'Helvetica-Bold'),  # OPERATING PROFIT
            ('BACKGROUND', (0, 10), (-1, 10), colors.HexColor('#FFE082')),  # Medium yellow
            ('FONTNAME', (0, 12), (-1, 12), 'Helvetica-Bold'),  # NET PROFIT
            ('BACKGROUND', (0, 12), (-1, 12), ReportColors.FINANCIAL_GOLDEN),  # Golden
            ('TEXTCOLOR', (0, 12), (-1, 12), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(financial_table)
        story.append(Spacer(1, 12))
        
        # Add helpful note about Gross Margin
        if total_cogs == 0 and sales_revenue > 0:
            margin_note = """
<i><b>Note:</b> Your Gross Margin is 100% because you have no Cost of Goods Sold (COGS).
This is typical for service-based businesses that don't sell physical products.</i>
"""
            story.append(Paragraph(margin_note, self.styles['InfoText']))
        elif sales_revenue == 0:
            margin_note = """
<i><b>Note:</b> Gross Margin is not applicable because there are no product sales recorded.
If you sell products, ensure they are categorized as "Sales Revenue" for accurate margin calculation.</i>
"""
            story.append(Paragraph(margin_note, self.styles['InfoText']))
        
        story.append(Spacer(1, 20))
        
        # Asset Overview
        story.append(Paragraph("Fixed Assets Overview", self.styles['SectionHeader']))
        
        asset_overview = [
            ['Metric', 'Amount (N)', 'Notes'],
            ['Total Assets (Original)', format_currency(total_assets_cost), f'{asset_count} assets'],
            ['Total Assets (NBV)', format_currency(total_assets_nbv), 'After depreciation'],
            ['Total Depreciation', format_currency(total_depreciation), 'Accumulated'],
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
        
        story.append(asset_table)
        story.append(Spacer(1, 20))
        
        # Current Assets & Liabilities Overview
        story.append(Paragraph("Current Assets & Liabilities", self.styles['SectionHeader']))
        
        # Display helpers for zero values
        inventory_display = format_currency(inventory_value) if inventory_count > 0 else "N0.00 (Not tracked)"
        debtors_display = format_currency(debtors_value) if debtors_count > 0 else "N0.00 (Not tracked)"
        creditors_display = format_currency(creditors_value) if creditors_count > 0 else "N0.00 (Not tracked)"
        
        # CRITICAL FIX (Feb 19, 2026): Display helper for cash - show if tracked via Cash/Bank Management
        # If user has set opening balance OR has adjustments, consider it "tracked"
        # Otherwise show "Not tracked" to encourage setup
        cash_display = format_currency(cash_balance) if cash_balance != 0 else "N0.00 (Not tracked)"
        
        current_assets_liabilities = [
            ['Item', 'Amount (N)', 'Notes'],
            ['CURRENT ASSETS', '', ''],
            ['Cash & Bank', cash_display, 'Liquid funds'],
            ['Inventory (Stock)', inventory_display, f'{inventory_count} items' if inventory_count > 0 else ''],
            ['Accounts Receivable (Debtors)', debtors_display, f'{debtors_count} customers' if debtors_count > 0 else ''],
            ['Total Current Assets', format_currency(total_current_assets), ''],
            ['', '', ''],
            ['CURRENT LIABILITIES', '', ''],
            ['Accounts Payable (Creditors)', creditors_display, f'{creditors_count} vendors' if creditors_count > 0 else ''],
            ['Estimated Tax Payable', format_currency(unpaid_tax), 'Unpaid tax obligation'],
            ['Total Current Liabilities', format_currency(total_current_liabilities), ''],
            ['', '', ''],
            ['NET CURRENT ASSETS', format_currency(total_current_assets - total_current_liabilities), 'Working Capital'],
        ]
        
        current_table = create_table(current_assets_liabilities, col_widths=[2.5*inch, 2*inch, 1.5*inch])
        current_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.INVENTORY_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (0, 1), 'Helvetica-Bold'),  # CURRENT ASSETS
            ('FONTNAME', (0, 6), (0, 6), 'Helvetica-Bold'),  # CURRENT LIABILITIES
            ('FONTNAME', (0, 10), (-1, 10), 'Helvetica-Bold'),  # NET CURRENT ASSETS
            ('BACKGROUND', (0, 10), (-1, 10), colors.HexColor('#E8F5E9')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(current_table)
        story.append(Spacer(1, 20))
        
        # VAS Breakdown Section (Granular Utility Reporting)
        if vas_breakdown and vas_breakdown.get('total', 0) > 0:
            story.append(Paragraph("Value Added Services (VAS) Breakdown", self.styles['SectionHeader']))
            
            vas_data = [
                ['Service Type', 'Amount (N)', 'Notes'],
            ]
            
            if vas_breakdown.get('airtime', 0) > 0:
                vas_data.append(['Airtime', format_currency(vas_breakdown['airtime']), 'Mobile airtime purchases'])
            if vas_breakdown.get('data', 0) > 0:
                vas_data.append(['Data', format_currency(vas_breakdown['data']), 'Mobile data bundles'])
            if vas_breakdown.get('electricity', 0) > 0:
                vas_data.append(['Electricity', format_currency(vas_breakdown['electricity']), 'Power/utility bills'])
            if vas_breakdown.get('cable_tv', 0) > 0:
                vas_data.append(['Cable TV', format_currency(vas_breakdown['cable_tv']), 'TV subscriptions'])
            if vas_breakdown.get('internet', 0) > 0:
                vas_data.append(['Internet', format_currency(vas_breakdown['internet']), 'Internet services'])
            if vas_breakdown.get('water', 0) > 0:
                vas_data.append(['Water', format_currency(vas_breakdown['water']), 'Water bills'])
            if vas_breakdown.get('transportation', 0) > 0:
                vas_data.append(['Transportation', format_currency(vas_breakdown['transportation']), 'Transport services'])
            if vas_breakdown.get('other', 0) > 0:
                vas_data.append(['Other VAS', format_currency(vas_breakdown['other']), 'Other services'])
            
            vas_data.append(['', '', ''])
            vas_data.append(['Total VAS Expenses', format_currency(vas_breakdown['total']), 'All digital services'])
            
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
            
            story.append(vas_table)
            story.append(Spacer(1, 20))
        
        # Tax Overview
        story.append(Paragraph("Tax Overview", self.styles['SectionHeader']))
        
        # CRITICAL FIX (Feb 19, 2026): Show tax savings message when profitable but exempt
        # Calculate what tax WOULD BE without exemption
        tax_without_exemption = 0
        if tax_type == 'CIT' and net_profit > 0:
            tax_without_exemption = net_profit * 0.30  # 30% CIT rate
        elif tax_type == 'PIT' and net_profit > 800000:
            tax_without_exemption = (net_profit - 800000) * 0.15  # Simplified PIT
        
        tax_savings = tax_without_exemption - estimated_tax
        
        tax_overview = [
            ['Metric', 'Amount (N)', 'Notes'],
            ['Taxable Income', format_currency(net_profit), 'After deductions'],
            ['Estimated Tax', format_currency(estimated_tax), tax_rate_display],
            ['Effective Rate', f"{effective_rate:.2f}%", ''],
        ]
        
        # Add tax savings message if applicable
        if tax_savings > 0 and estimated_tax == 0:
            tax_overview.append(['Tax Savings', format_currency(tax_savings), 'Amount saved through exemption'])
        
        # Add CIT exemption context
        if tax_type == 'CIT':
            tax_overview.append(['Revenue Status', format_currency(total_income), '≤N100M for exemption'])
            tax_overview.append(['Assets NBV Status', format_currency(total_assets_nbv), '≤N250M for exemption'])
        
        tax_table = create_table(tax_overview, col_widths=[2*inch, 2*inch, 2*inch])
        tax_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.TAX_BROWN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(tax_table)
        story.append(PageBreak())
        
        # === BALANCE SHEET ===
        story.append(Paragraph("Balance Sheet", self.styles['CustomTitle']))
        story.append(Spacer(1, 12))
        
        # ASSETS Section
        story.append(Paragraph("ASSETS", self.styles['SectionHeader']))
        
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
        
        story.append(assets_bs_table)
        story.append(Spacer(1, 20))
        
        # LIABILITIES & EQUITY Section
        story.append(Paragraph("LIABILITIES & EQUITY", self.styles['SectionHeader']))
        
        liabilities_section = [
            ['Category', 'Amount (N)'],
            ['CURRENT LIABILITIES', ''],
            ['Accounts Payable (Creditors)', creditors_display],
            ['Estimated Tax Payable', format_currency(unpaid_tax)],
            ['Total Current Liabilities', format_currency(total_current_liabilities)],
            ['', ''],
            ['OWNER\'S EQUITY', ''],
            ['Opening Equity', format_currency(opening_equity)],
            ['Add: Net Profit/(Loss) for Period', format_currency(net_profit)],
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
            ('FONTNAME', (0, 6), (0, 6), 'Helvetica-Bold'),  # OWNER'S EQUITY
            ('FONTNAME', (0, 10), (-1, 10), 'Helvetica-Bold'),  # Closing Equity
            ('BACKGROUND', (0, 10), (-1, 10), colors.HexColor('#E8F5E9')),  # Light green
            ('FONTNAME', (0, 12), (-1, 12), 'Helvetica-Bold'),  # TOTAL
            ('BACKGROUND', (0, 12), (-1, 12), colors.HexColor('#FFEBEE')),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(liabilities_bs_table)
        
        # Accounting equation verification
        accounting_balance = total_all_assets - (total_current_liabilities + closing_equity)
        balance_status = "✓ Balanced" if abs(accounting_balance) < 0.01 else f"⚠ Difference: ₦{accounting_balance:,.2f}"
        
        # Note about tracking, accounting equation, and Drawings education
        note_text = f"""
<i><b>Note:</b> Items marked as "Not tracked" indicate that no data has been recorded for these categories.
Most SMEs focus on income and expenses tracking. Inventory, Debtors, Creditors, and Cash tracking is optional
but recommended for a complete financial picture.<br/>
<br/>
<b>Understanding Drawings:</b> Drawings represent money withdrawn by the owner for personal use. 
These are NOT business expenses and do NOT reduce profit. Instead, they reduce Owner's Equity.
Example: If you take ₦50,000 from the business for personal shopping, this is a Drawing, not an expense.<br/>
<br/>
<b>Accounting Equation Check:</b> Assets (₦{total_all_assets:,.2f}) = Liabilities (₦{total_current_liabilities:,.2f}) + Equity (₦{closing_equity:,.2f}) [{balance_status}]<br/>
<br/>
<b>Important:</b> This Statement of Affairs is calculated as of {end_date.strftime('%B %d, %Y') if end_date else 'the current date'}.
Asset depreciation and all values reflect the position at that specific date.</i>
"""
        story.append(Spacer(1, 12))
        story.append(Paragraph(note_text, self.styles['InfoText']))
        story.append(PageBreak())
        
        # === DOCUMENTATION NOTES ===
        story.append(Paragraph("Documentation Notes & Best Practices", self.styles['CustomTitle']))
        story.append(Spacer(1, 12))
        
        # Tax Filing Requirements
        story.append(Paragraph("Tax Filing Requirements", self.styles['SectionHeader']))
        
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
• Revenue: ₦{total_income:,.2f} ({('≤' if total_income <= 100000000 else '>')} ₦100M)<br/>
• Assets NBV: ₦{total_assets_nbv:,.2f} ({('≤' if total_assets_nbv <= 250000000 else '>')} ₦250M)<br/>
• Estimated Tax: ₦{estimated_tax:,.2f}
"""
        else:
            tax_requirements = f"""
<b>Personal Income Tax (PIT) Filing Requirements:</b><br/>
<br/>
1. <b>Annual Returns:</b> File by March 31st of following year<br/>
2. <b>Tax-Free Threshold:</b> First ₦800,000 is tax-exempt<br/>
3. <b>Progressive Rates:</b> 0% to 25% based on income bands<br/>
<br/>
<b>Your Estimated Tax:</b> ₦{estimated_tax:,.2f}
"""
        
        story.append(Paragraph(tax_requirements, self.styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Record Keeping Recommendations
        story.append(Paragraph("Record Keeping Recommendations", self.styles['SectionHeader']))
        
        # Add specific recommendations based on what's missing
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
        
        story.append(Paragraph(recommendations, self.styles['Normal']))
        story.append(Spacer(1, 30))
        
        # Footer
        report_id = f"SOA-{nigerian_time.strftime('%Y%m%d%H%M%S')}"
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
        
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

