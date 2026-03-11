# Profit & Loss Statement PDF Generator
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import TableStyle

from .generator_core import (
    BaseReportGenerator, format_currency, get_nigerian_time, format_tin_display,
    create_table, parse_date_safe, ReportColors, safe_float, wrap_text_for_table
)

class ProfitLossGenerator(BaseReportGenerator):
    """Specialized generator for Profit & Loss statements"""
    
    def generate_financial_report(self, user_data, export_data, data_type='all', tag_filter="all"):
        """Generate comprehensive financial report PDF"""
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
        
        # Add filter disclaimer
        if tag_filter and tag_filter != 'all':
            disclaimer_text = self._get_filter_disclaimer(tag_filter)
            disclaimer = Paragraph(disclaimer_text, self.styles['InfoText'])
            story.append(disclaimer)
            story.append(Spacer(1, 12))

        # Expenses Section
        if 'expenses' in export_data and export_data['expenses']:
            story.extend(self._build_expenses_section(export_data['expenses']))
        
        # Income Section
        if 'incomes' in export_data and export_data['incomes']:
            story.extend(self._build_income_section(export_data['incomes']))
        
        # Credit Transactions Section
        if 'creditTransactions' in export_data and export_data['creditTransactions']:
            story.extend(self._build_credit_transactions_section(export_data['creditTransactions']))
        
        # Profit & Loss Summary Section (only for 'all' data type)
        if data_type.lower() == 'all':
            story.extend(self._build_profit_loss_summary(export_data))
        
        # Footer
        story.extend(self._build_footer())
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def _build_expenses_section(self, expenses):
        """Build expenses section"""
        elements = []
        elements.append(Paragraph("Expenses Summary", self.styles['SectionHeader']))
        
        expense_data = [['Date', 'Category', 'Description', 'Amount (N)']]
        total_expenses = 0
        
        for expense in expenses:
            date_obj = parse_date_safe(expense.get('date'))
            date_str = date_obj.strftime('%Y-%m-%d')
            description = expense.get('description') or expense.get('notes') or expense.get('title', 'N/A')
            category = expense.get('category', 'N/A')
            
            # Wrap long text in Paragraph objects for automatic text wrapping
            category_para = wrap_text_for_table(category, max_width=20)
            description_para = wrap_text_for_table(description, max_width=35)
            
            expense_data.append([
                date_str,
                category_para,
                description_para,
                format_currency(expense.get('amount', 0))
            ])
            total_expenses += expense.get('amount', 0)
        
        expense_data.append(['', '', 'Total:', format_currency(total_expenses)])
        
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
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        elements.append(expense_table)
        elements.append(Spacer(1, 20))
        return elements
    
    def _build_income_section(self, incomes):
        """Build income section"""
        elements = []
        elements.append(Paragraph("Income Summary", self.styles['SectionHeader']))
        
        income_data = [['Date', 'Category', 'Description', 'Amount (N)']]
        total_income = 0
        
        for income in incomes:
            date_obj = parse_date_safe(income.get('date'))
            date_str = date_obj.strftime('%Y-%m-%d')
            description = income.get('description') or income.get('source', 'N/A')
            category = income.get('category', 'Other')
            
            category_para = wrap_text_for_table(category, max_width=20)
            description_para = wrap_text_for_table(description, max_width=35)
            
            income_data.append([
                date_str,
                category_para,
                description_para,
                format_currency(income.get('amount', 0))
            ])
            total_income += income.get('amount', 0)
        
        income_data.append(['', '', 'Total:', format_currency(total_income)])
        
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
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        elements.append(income_table)
        elements.append(Spacer(1, 20))
        return elements
    
    def _build_credit_transactions_section(self, credit_transactions):
        """Build credit transactions section"""
        elements = []
        elements.append(Paragraph("Credit Transactions", self.styles['SectionHeader']))
        
        credit_data = [['Date', 'Type', 'Description', 'Amount (FC)']]
        
        for transaction in credit_transactions:
            date_obj = parse_date_safe(transaction.get('createdAt'))
            date_str = date_obj.strftime('%Y-%m-%d')
            credit_data.append([
                date_str,
                transaction.get('type', 'N/A'),
                transaction.get('description', 'N/A'),
                f"{safe_float(transaction.get('amount', 0)):,.2f}"
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
        
        elements.append(credit_table)
        elements.append(Spacer(1, 20))
        return elements
    
    def _build_profit_loss_summary(self, export_data):
        """Build profit & loss summary section"""
        elements = []
        
        # Calculate totals
        total_income = 0
        if 'incomes' in export_data and export_data['incomes']:
            total_income = sum(income.get('amount', 0) for income in export_data['incomes'])
        
        # COGS SEPARATION: Separate COGS from Operating Expenses
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
        
        # Add summary section
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("Financial Summary", self.styles['SectionHeader']))
        
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
        
        elements.append(summary_table)
        elements.append(Spacer(1, 20))
        return elements
    
    def _build_footer(self):
        """Build report footer"""
        footer_text = """
        <i>This report was generated by FiCore Mobile App.<br/>
        For support, contact: team@ficoreafrica.com</i>
        """
        return [
            Spacer(1, 30),
            Paragraph(footer_text, self.styles['InfoText'])
        ]