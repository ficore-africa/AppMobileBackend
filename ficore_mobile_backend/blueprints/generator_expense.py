# Expense Report PDF Generator
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import TableStyle

from .generator_core import (
    BaseReportGenerator, format_currency, get_nigerian_time, format_tin_display,
    create_table, parse_date_safe, ReportColors, safe_float, wrap_text_for_table
)

class ExpenseGenerator(BaseReportGenerator):
    """Specialized generator for Expense reports"""
    
    def generate_expense_report(self, user_data, export_data, tag_filter="all"):
        """Generate Expense report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Expense Report", self.styles['CustomTitle'])
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
        <b>Report Type:</b> EXPENSE
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
        else:
            story.append(Paragraph("No expense records found for the selected period.", self.styles['Normal']))
        
        # Footer
        story.extend(self._build_footer())
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def _build_expenses_section(self, expenses):
        """Build expenses section with COGS separation"""
        elements = []
        
        # Separate COGS from Operating Expenses
        cogs_expenses = []
        operating_expenses = []
        
        for expense in expenses:
            if expense.get('category') == 'Cost of Goods Sold':
                cogs_expenses.append(expense)
            else:
                operating_expenses.append(expense)
        
        # Build COGS section if exists
        if cogs_expenses:
            elements.extend(self._build_cogs_section(cogs_expenses))
        
        # Build Operating Expenses section
        if operating_expenses:
            elements.extend(self._build_operating_expenses_section(operating_expenses))
        
        # Build summary
        if cogs_expenses or operating_expenses:
            elements.extend(self._build_expense_summary(cogs_expenses, operating_expenses))
        
        return elements
    
    def _build_cogs_section(self, cogs_expenses):
        """Build Cost of Goods Sold section"""
        elements = []
        elements.append(Paragraph("Cost of Goods Sold (COGS)", self.styles['SectionHeader']))
        
        cogs_data = [['Date', 'Description', 'Amount (N)']]
        total_cogs = 0
        
        for expense in cogs_expenses:
            date_obj = parse_date_safe(expense.get('date'))
            date_str = date_obj.strftime('%Y-%m-%d')
            description = expense.get('description') or expense.get('notes') or expense.get('title', 'N/A')
            
            description_para = wrap_text_for_table(description, max_width=45)
            
            cogs_data.append([
                date_str,
                description_para,
                format_currency(expense.get('amount', 0))
            ])
            total_cogs += expense.get('amount', 0)
        
        cogs_data.append(['', 'Total COGS:', format_currency(total_cogs)])
        
        cogs_table = create_table(cogs_data, col_widths=[1.5*inch, 3.2*inch, 1.3*inch])
        cogs_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8b4513')),  # Brown for COGS
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#f5f5dc')),  # Beige
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#deb887')),  # Burlywood
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        elements.append(cogs_table)
        elements.append(Spacer(1, 20))
        return elements
    
    def _build_operating_expenses_section(self, operating_expenses):
        """Build Operating Expenses section"""
        elements = []
        elements.append(Paragraph("Operating Expenses", self.styles['SectionHeader']))
        
        expense_data = [['Date', 'Category', 'Description', 'Amount (N)']]
        total_operating = 0
        
        for expense in operating_expenses:
            date_obj = parse_date_safe(expense.get('date'))
            date_str = date_obj.strftime('%Y-%m-%d')
            description = expense.get('description') or expense.get('notes') or expense.get('title', 'N/A')
            category = expense.get('category', 'N/A')
            
            category_para = wrap_text_for_table(category, max_width=20)
            description_para = wrap_text_for_table(description, max_width=35)
            
            expense_data.append([
                date_str,
                category_para,
                description_para,
                format_currency(expense.get('amount', 0))
            ])
            total_operating += expense.get('amount', 0)
        
        expense_data.append(['', '', 'Total Operating:', format_currency(total_operating)])
        
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
    
    def _build_expense_summary(self, cogs_expenses, operating_expenses):
        """Build expense summary section"""
        elements = []
        
        total_cogs = sum(exp.get('amount', 0) for exp in cogs_expenses)
        total_operating = sum(exp.get('amount', 0) for exp in operating_expenses)
        total_expenses = total_cogs + total_operating
        
        elements.append(Paragraph("Expense Summary", self.styles['SectionHeader']))
        
        summary_data = [
            ['Category', 'Amount (N)'],
            ['Cost of Goods Sold (COGS)', format_currency(total_cogs)],
            ['Operating Expenses', format_currency(total_operating)],
            ['Total Expenses', format_currency(total_expenses)]
        ]
        
        summary_table = create_table(summary_data, col_widths=[4*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ReportColors.EXPENSE_RED),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, 2), colors.beige),
            ('BACKGROUND', (0, -1), (-1, -1), ReportColors.EXPENSE_LIGHT),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (-1, -1), 14),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
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
        elements = []
        elements.append(Spacer(1, 30))
        elements.append(Paragraph(footer_text, self.styles['InfoText']))
        return elements