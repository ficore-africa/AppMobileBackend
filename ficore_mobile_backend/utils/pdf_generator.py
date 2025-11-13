"""
PDF Generation Utilities for FiCore Mobile
Generates professional PDF reports for user data exports
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime
import io


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
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("FiCore Financial Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Report Generated:</b> {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}<br/>
        <b>Report Type:</b> {data_type.upper()}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Expenses Section
        if 'expenses' in export_data and export_data['expenses']:
            story.append(Paragraph("Expenses Summary", self.styles['SectionHeader']))
            
            expense_data = [['Date', 'Title', 'Category', 'Amount (₦)']]
            total_expenses = 0
            
            for expense in export_data['expenses']:
                date_str = datetime.fromisoformat(expense['date'].replace('Z', '')).strftime('%Y-%m-%d')
                expense_data.append([
                    date_str,
                    expense.get('title', 'N/A'),
                    expense.get('category', 'N/A'),
                    f"₦{expense.get('amount', 0):,.2f}"
                ])
                total_expenses += expense.get('amount', 0)
            
            expense_data.append(['', '', 'Total:', f"₦{total_expenses:,.2f}"])
            
            expense_table = Table(expense_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 1.5*inch])
            expense_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f0fe')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(expense_table)
            story.append(Spacer(1, 20))
        
        # Income Section
        if 'incomes' in export_data and export_data['incomes']:
            story.append(Paragraph("Income Summary", self.styles['SectionHeader']))
            
            income_data = [['Date', 'Source', 'Amount (₦)']]
            total_income = 0
            
            for income in export_data['incomes']:
                date_str = datetime.fromisoformat(income['dateReceived'].replace('Z', '')).strftime('%Y-%m-%d')
                income_data.append([
                    date_str,
                    income.get('source', 'N/A'),
                    f"₦{income.get('amount', 0):,.2f}"
                ])
                total_income += income.get('amount', 0)
            
            income_data.append(['', 'Total:', f"₦{total_income:,.2f}"])
            
            income_table = Table(income_data, colWidths=[2*inch, 3*inch, 1.5*inch])
            income_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34a853')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.lightgreen),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f5e9')),
                ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(income_table)
            story.append(Spacer(1, 20))
        
        # Credit Transactions Section
        if 'creditTransactions' in export_data and export_data['creditTransactions']:
            story.append(Paragraph("Credit Transactions", self.styles['SectionHeader']))
            
            credit_data = [['Date', 'Type', 'Description', 'Amount (FC)']]
            
            for transaction in export_data['creditTransactions']:
                date_str = datetime.fromisoformat(transaction['createdAt'].replace('Z', '')).strftime('%Y-%m-%d')
                credit_data.append([
                    date_str,
                    transaction.get('type', 'N/A'),
                    transaction.get('description', 'N/A'),
                    f"{transaction.get('amount', 0):,.2f}"
                ])
            
            credit_table = Table(credit_data, colWidths=[1.5*inch, 1.5*inch, 2.5*inch, 1*inch])
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
        
        # Footer
        footer_text = """
        <i>This report was generated by FiCore Mobile App.<br/>
        For support, contact: ficoreafrica@gmail.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def generate_tax_report(self, user_data, tax_calculation):
        """Generate tax calculation report PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                              topMargin=72, bottomMargin=18)
        
        story = []
        
        # Title
        title = Paragraph("Tax Calculation Report", self.styles['CustomTitle'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # User Info
        user_info = f"""
        <b>Name:</b> {user_data.get('firstName', '')} {user_data.get('lastName', '')}<br/>
        <b>Email:</b> {user_data.get('email', '')}<br/>
        <b>Tax Year:</b> {tax_calculation.get('tax_year', datetime.utcnow().year)}<br/>
        <b>Report Generated:</b> {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}
        """
        story.append(Paragraph(user_info, self.styles['InfoText']))
        story.append(Spacer(1, 20))
        
        # Income Summary
        story.append(Paragraph("Income Summary", self.styles['SectionHeader']))
        income_data = [
            ['Description', 'Amount (₦)'],
            ['Total Income', f"₦{tax_calculation.get('total_income', 0):,.2f}"],
            ['Deductible Expenses', f"₦{tax_calculation.get('deductible_expenses', {}).get('total', 0):,.2f}"],
            ['Net Income', f"₦{tax_calculation.get('net_income', 0):,.2f}"],
            ['Statutory Contributions', f"₦{tax_calculation.get('statutory_contributions', 0):,.2f}"],
            ['Adjusted Income', f"₦{tax_calculation.get('adjusted_income', 0):,.2f}"],
            ['Rent Relief', f"₦{tax_calculation.get('rent_relief', 0):,.2f}"],
            ['Taxable Income', f"₦{tax_calculation.get('taxable_income', 0):,.2f}"]
        ]
        
        income_table = Table(income_data, colWidths=[4*inch, 2*inch])
        income_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a73e8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f0fe')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(income_table)
        story.append(Spacer(1, 20))
        
        # Tax Breakdown
        story.append(Paragraph("Tax Calculation Breakdown", self.styles['SectionHeader']))
        tax_breakdown_data = [['Tax Band', 'Rate', 'Taxable Amount (₦)', 'Tax (₦)']]
        
        for band in tax_calculation.get('tax_breakdown', []):
            tax_breakdown_data.append([
                f"₦{band['lower_bound']:,.0f} - ₦{band['upper_bound']:,.0f}",
                f"{band['rate']*100:.0f}%",
                f"₦{band['taxable_amount']:,.2f}",
                f"₦{band['tax_amount']:,.2f}"
            ])
        
        tax_breakdown_data.append([
            '', 'Total Tax:', '', 
            f"₦{tax_calculation.get('total_tax', 0):,.2f}"
        ])
        
        tax_table = Table(tax_breakdown_data, colWidths=[2*inch, 1*inch, 1.5*inch, 1.5*inch])
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
        story.append(Paragraph("Summary", self.styles['SectionHeader']))
        summary_text = f"""
        <b>Total Tax Liability:</b> ₦{tax_calculation.get('total_tax', 0):,.2f}<br/>
        <b>Effective Tax Rate:</b> {tax_calculation.get('effective_rate', 0):.2f}%<br/>
        <b>Net Income After Tax:</b> ₦{tax_calculation.get('net_income_after_tax', 0):,.2f}
        """
        story.append(Paragraph(summary_text, self.styles['Normal']))
        
        # Footer
        footer_text = """
        <i>This tax calculation is for informational purposes only.<br/>
        Please consult with a tax professional for official tax filing.<br/>
        Generated by FiCore Mobile App | ficoreafrica@gmail.com</i>
        """
        story.append(Spacer(1, 30))
        story.append(Paragraph(footer_text, self.styles['InfoText']))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
