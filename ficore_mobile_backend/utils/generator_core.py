# Core utilities shared across all PDF generators
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.platypus.tables import LongTable
from datetime import datetime, timezone, timedelta
import pytz
import io
from decimal import Decimal

# CRITICAL FIX (Feb 19, 2026): Naira symbol rendering
# The ₦ symbol doesn't render properly in default Helvetica font
# Use "N" with proper formatting instead for PDF compatibility
NAIRA_SYMBOL = "N"  # Will be rendered as "N" with proper spacing

def format_currency(amount):
    """
    Format currency with proper Naira symbol for PDF rendering
    
    CRITICAL FIX (Feb 19, 2026): The ₦ symbol renders as a black square in PDFs
    because Helvetica font doesn't support it. Use "N" with proper spacing instead.
    
    CRITICAL FIX (Mar 9, 2026): Handle Decimal128 values from MongoDB
    
    Args:
        amount: Numeric amount to format (may be Decimal128)
    
    Returns:
        Formatted string like "N1,234,567.89"
    """
    if amount is None:
        return f"{NAIRA_SYMBOL}0.00"
    
    # Handle Decimal128 from MongoDB
    if hasattr(amount, 'to_decimal'):
        amount = float(amount.to_decimal())
    elif isinstance(amount, Decimal):
        amount = float(amount)
    
    try:
        amount = float(amount)
        return f"{NAIRA_SYMBOL}{amount:,.2f}"
    except (ValueError, TypeError):
        return f"{NAIRA_SYMBOL}0.00"

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

def safe_float(value):
    """Safely convert value to float, handling Decimal128"""
    if value is None:
        return 0.0
    if hasattr(value, 'to_decimal'):
        return float(value.to_decimal())
    elif isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def wrap_text_for_table(text, max_width=30, style_name='Normal'):
    """
    Wrap text content for table cells to prevent overflow
    
    Args:
        text: Text content to wrap
        max_width: Maximum characters per line (default: 30)
        style_name: ReportLab style name to use
    
    Returns:
        Paragraph object with wrapped text
    """
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph
    
    if not text:
        text = 'N/A'
    
    # Convert to string and limit length
    text_str = str(text)
    
    # If text is very long, truncate with ellipsis
    if len(text_str) > max_width * 3:  # Allow up to 3 lines
        text_str = text_str[:max_width * 3 - 3] + '...'
    
    # Get styles
    styles = getSampleStyleSheet()
    style = styles[style_name]
    
    # Create paragraph with word wrapping
    return Paragraph(text_str, style)


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

class BaseReportGenerator:
    """Base class for all report generators"""
    
    def __init__(self):
        self.setup_custom_styles()
    
    def setup_custom_styles(self):
        """Setup custom styles for reports"""
        self.styles = getSampleStyleSheet()
        
        # Custom title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Title'],
            fontSize=18,
            textColor=ReportColors.FINANCIAL_GOLDEN,
            alignment=TA_CENTER,
            spaceAfter=12
        ))
        
        # Section header style
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#1a73e8'),
            spaceBefore=12,
            spaceAfter=6
        ))
        
        # Info text style
        self.styles.add(ParagraphStyle(
            name='InfoText',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#5f6368'),
            leftIndent=0,
            rightIndent=0
        ))
    
    def _get_filter_disclaimer(self, tag_filter):
        """Get filter disclaimer text"""
        if tag_filter == 'business':
            return """
<i><b>Filter Applied:</b> This report shows only BUSINESS transactions (tagged as 'business').
Personal transactions (tagged as 'personal') are excluded from this report.</i>
"""
        elif tag_filter == 'personal':
            return """
<i><b>Filter Applied:</b> This report shows only PERSONAL transactions (tagged as 'personal').
Business transactions (tagged as 'business') are excluded from this report.</i>
"""
        elif tag_filter and tag_filter != 'all':
            return f"""
<i><b>Filter Applied:</b> This report shows only transactions tagged as '{tag_filter}'.
Transactions with other tags are excluded from this report.</i>
"""
        return ""
    
    def _create_tax_override_watermark(self, selected_tax_type, profile_tax_type):
        """
        Create tax override watermark when selected tax type differs from user's profile
        
        LEGAL PROTECTION (Feb 23, 2026):
        - Protects FiCore from liability (not providing 'wrong' advice)
        - Protects users from accidental wrong filing
        - Enables safe 'what if I incorporated?' scenarios
        - Professional appearance (info box, not scary warning)
        
        Args:
            selected_tax_type: Tax type selected for this report ('PIT' or 'CIT')
            profile_tax_type: User's registered tax type from profile ('PIT' or 'CIT')
        
        Returns:
            Table with watermark content (light blue info box)
        """
        # Get full tax type names
        selected_name = "Corporate Income Tax (CIT)" if selected_tax_type == 'CIT' else "Personal Income Tax (PIT)"
        profile_name = "Corporate Income Tax (CIT)" if profile_tax_type == 'CIT' else "Personal Income Tax (PIT)"
        
        # Create watermark content
        watermark_text = f"""
<para alignment="left" fontSize="10" textColor="#1565C0">
<b>ℹ️ TAX TYPE OVERRIDE NOTICE</b>
</para>
<para alignment="left" fontSize="9" textColor="#333333" spaceBefore="6">
This report was generated using <b>{selected_name}</b> rates at your request.<br/>
Your registered tax profile remains <b>{profile_name}</b>.
</para>
<para alignment="left" fontSize="9" textColor="#555555" spaceBefore="6">
<i>This is a simulation for planning purposes. Consult a tax professional before making filing decisions.</i>
</para>
"""
        
        # Create table with light blue background
        watermark_table = Table(
            [[Paragraph(watermark_text, self.styles['Normal'])]],
            colWidths=[6.5*inch]
        )
        
        watermark_table.setStyle(TableStyle([
            # Light blue background (info, not error)
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#E3F2FD')),
            # Medium blue border
            ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#1976D2')),
            # Padding
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            # Alignment
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        
        return watermark_table