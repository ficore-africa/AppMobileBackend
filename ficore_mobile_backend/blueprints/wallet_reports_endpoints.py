"""
Wallet Reports Endpoints - To be integrated into reports.py
Add these endpoints before the 'return reports_bp' statement
"""

# ============================================================================
# WALLET REPORTS - NEW SECTION (Feb 2026)
# ============================================================================

# Add to REPORT_CREDIT_COSTS dictionary:
WALLET_REPORT_COSTS = {
    'wallet_funding_csv': 2,
    'wallet_funding_pdf': 3,
    'wallet_vas_csv': 2,
    'wallet_vas_pdf': 3,
    'wallet_bills_csv': 2,
    'wallet_bills_pdf': 3,
    'wallet_full_csv': 3,
    'wallet_full_pdf': 4,
}

# Wallet Funding Report - PDF
@reports_bp.route('/wallet-funding-pdf', methods=['POST'])
@token_required
def export_wallet_funding_pdf(current_user):
    """Export Wallet Funding transactions as PDF"""
    try:
        request_data = request.get_json() or {}
        report_type = 'wallet_funding_pdf'
        
        # Check user access
        has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
        
        if not has_access:
            return jsonify({
                'success': False,
                'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                'data': {
                    'required': credit_cost,
                    'current': current_balance,
                    'shortfall': credit_cost - current_balance
                }
            }), 402
        
        # Parse date range
        start_date, end_date = parse_date_range(request_data)
        
        # Fetch wallet funding transactions
        query = {
            'userId': ObjectId(str(current_user['_id'])),
            'type': 'WALLET_FUNDING'
        }
        
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
        
        # Prepare user data
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        user_data = {
            'firstName': user.get('firstName', ''),
            'lastName': user.get('lastName', ''),
            'email': user.get('email', ''),
            'businessName': user.get('businessName', '')
        }
        
        # Prepare export data
        export_data = {
            'transactions': []
        }
        
        for txn in transactions:
            export_data['transactions'].append({
                'date': txn.get('createdAt', datetime.utcnow()),
                'reference': txn.get('reference', txn.get('transactionReference', 'N/A')),
                'amount': txn.get('amount', 0),
                'fee': txn.get('depositFee', 0),
                'status': txn.get('status', 'UNKNOWN'),
                'description': f"Wallet Funding - ₦{txn.get('amount', 0):,.2f}"
            })
        
        # Generate PDF
        pdf_generator = PDFGenerator()
        pdf_buffer = pdf_generator.generate_wallet_funding_report(user_data, export_data, start_date, end_date)
        
        # Deduct credits if not premium
        if not is_premium and credit_cost > 0:
            new_balance = deduct_credits(current_user, credit_cost, report_type)
        
        # Log export event
        log_export_event(current_user, report_type, 'pdf', success=True)
        
        # Return PDF file
        pdf_buffer.seek(0)
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'ficore_wallet_funding_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
        )
        
    except Exception as e:
        log_export_event(current_user, 'wallet_funding_pdf', 'pdf', success=False, error=str(e))
        return jsonify({
            'success': False,
            'message': f'Failed to generate Wallet Funding PDF: {str(e)}'
        }), 500

# Wallet Funding Report - CSV
@reports_bp.route('/wallet-funding-csv', methods=['POST'])
@token_required
def export_wallet_funding_csv(current_user):
    """Export Wallet Funding transactions as CSV"""
    try:
        request_data = request.get_json() or {}
        report_type = 'wallet_funding_csv'
        
        # Check user access
        has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
        
        if not has_access:
            return jsonify({
                'success': False,
                'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                'data': {
                    'required': credit_cost,
                    'current': current_balance,
                    'shortfall': credit_cost - current_balance
                }
            }), 402
        
        # Parse date range
        start_date, end_date = parse_date_range(request_data)
        
        # Fetch wallet funding transactions
        query = {
            'userId': ObjectId(str(current_user['_id'])),
            'type': 'WALLET_FUNDING'
        }
        
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['FiCore Africa - Wallet Funding Report'])
        writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
        if start_date and end_date:
            writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
        writer.writerow([])
        
        # Data
        writer.writerow(['Date', 'Reference', 'Amount (₦)', 'Fee (₦)', 'Status'])
        total_amount = 0
        total_fees = 0
        
        for txn in transactions:
            date_obj = txn.get('createdAt', datetime.utcnow())
            date_str = date_obj.strftime('%Y-%m-%d %H:%M')
            amount = txn.get('amount', 0)
            fee = txn.get('depositFee', 0)
            
            writer.writerow([
                date_str,
                txn.get('reference', txn.get('transactionReference', 'N/A')),
                f'{amount:,.2f}',
                f'{fee:,.2f}',
                txn.get('status', 'UNKNOWN')
            ])
            total_amount += amount
            total_fees += fee
        
        writer.writerow(['', 'Totals:', f'{total_amount:,.2f}', f'{total_fees:,.2f}', ''])
        writer.writerow([])
        
        # Summary
        writer.writerow(['SUMMARY'])
        writer.writerow(['Total Funded', f'{total_amount:,.2f}'])
        writer.writerow(['Total Fees', f'{total_fees:,.2f}'])
        writer.writerow(['Number of Transactions', len(transactions)])
        
        # Deduct credits if not premium
        if not is_premium and credit_cost > 0:
            new_balance = deduct_credits(current_user, credit_cost, report_type)
        
        # Log export event
        log_export_event(current_user, report_type, 'csv', success=True)
        
        # Return CSV file
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'ficore_wallet_funding_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        )
        
    except Exception as e:
        log_export_event(current_user, 'wallet_funding_csv', 'csv', success=False, error=str(e))
        return jsonify({
            'success': False,
            'message': f'Failed to generate Wallet Funding CSV: {str(e)}'
        }), 500

# VAS Transactions Report - PDF
@reports_bp.route('/wallet-vas-pdf', methods=['POST'])
@token_required
def export_wallet_vas_pdf(current_user):
    """Export VAS transactions (Airtime & Data) as PDF"""
    try:
        request_data = request.get_json() or {}
        report_type = 'wallet_vas_pdf'
        
        # Check user access
        has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
        
        if not has_access:
            return jsonify({
                'success': False,
                'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                'data': {
                    'required': credit_cost,
                    'current': current_balance,
                    'shortfall': credit_cost - current_balance
                }
            }), 402
        
        # Parse date range
        start_date, end_date = parse_date_range(request_data)
        
        # Fetch VAS transactions (Airtime & Data)
        query = {
            'userId': ObjectId(str(current_user['_id'])),
            'type': {'$in': ['AIRTIME', 'DATA']}
        }
        
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
        
        # Prepare user data
        user = mongo.db.users.find_one({'_id': current_user['_id']})
        user_data = {
            'firstName': user.get('firstName', ''),
            'lastName': user.get('lastName', ''),
            'email': user.get('email', ''),
            'businessName': user.get('businessName', '')
        }
        
        # Prepare export data
        export_data = {
            'transactions': []
        }
        
        for txn in transactions:
            txn_type = txn.get('type', 'VAS')
            network = txn.get('network', 'N/A')
            phone = txn.get('phoneNumber', 'N/A')
            plan = txn.get('dataPlanName', txn.get('dataPlan', ''))
            
            description = f"{txn_type} - {network} {phone}"
            if plan:
                description += f" - {plan}"
            
            export_data['transactions'].append({
                'date': txn.get('createdAt', datetime.utcnow()),
                'type': txn_type,
                'network': network,
                'phoneNumber': phone,
                'plan': plan,
                'amount': txn.get('amount', 0),
                'fee': txn.get('fee', txn.get('depositFee', 0)),
                'status': txn.get('status', 'UNKNOWN'),
                'reference': txn.get('reference', txn.get('transactionReference', 'N/A')),
                'description': description
            })
        
        # Generate PDF
        pdf_generator = PDFGenerator()
        pdf_buffer = pdf_generator.generate_wallet_vas_report(user_data, export_data, start_date, end_date)
        
        # Deduct credits if not premium
        if not is_premium and credit_cost > 0:
            new_balance = deduct_credits(current_user, credit_cost, report_type)
        
        # Log export event
        log_export_event(current_user, report_type, 'pdf', success=True)
        
        # Return PDF file
        pdf_buffer.seek(0)
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'ficore_wallet_vas_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
        )
        
    except Exception as e:
        log_export_event(current_user, 'wallet_vas_pdf', 'pdf', success=False, error=str(e))
        return jsonify({
            'success': False,
            'message': f'Failed to generate VAS Transactions PDF: {str(e)}'
        }), 500

# VAS Transactions Report - CSV
@reports_bp.route('/wallet-vas-csv', methods=['POST'])
@token_required
def export_wallet_vas_csv(current_user):
    """Export VAS transactions (Airtime & Data) as CSV"""
    try:
        request_data = request.get_json() or {}
        report_type = 'wallet_vas_csv'
        
        # Check user access
        has_access, is_premium, current_balance, credit_cost = check_user_access(current_user, report_type)
        
        if not has_access:
            return jsonify({
                'success': False,
                'message': f'Insufficient credits. You need {credit_cost} FC to export this report.',
                'data': {
                    'required': credit_cost,
                    'current': current_balance,
                    'shortfall': credit_cost - current_balance
                }
            }), 402
        
        # Parse date range
        start_date, end_date = parse_date_range(request_data)
        
        # Fetch VAS transactions (Airtime & Data)
        query = {
            'userId': ObjectId(str(current_user['_id'])),
            'type': {'$in': ['AIRTIME', 'DATA']}
        }
        
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
        
        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['FiCore Africa - VAS Transactions Report (Airtime & Data)'])
        writer.writerow(['Generated:', datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')])
        if start_date and end_date:
            writer.writerow(['Period:', f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"])
        writer.writerow([])
        
        # Data
        writer.writerow(['Date', 'Type', 'Network', 'Phone Number', 'Plan/Description', 'Amount (₦)', 'Fee (₦)', 'Status', 'Reference'])
        total_amount = 0
        total_fees = 0
        
        for txn in transactions:
            date_obj = txn.get('createdAt', datetime.utcnow())
            date_str = date_obj.strftime('%Y-%m-%d %H:%M')
            amount = txn.get('amount', 0)
            fee = txn.get('fee', txn.get('depositFee', 0))
            
            writer.writerow([
                date_str,
                txn.get('type', 'VAS'),
                txn.get('network', 'N/A'),
                txn.get('phoneNumber', 'N/A'),
                txn.get('dataPlanName', txn.get('dataPlan', 'N/A')),
                f'{amount:,.2f}',
                f'{fee:,.2f}',
                txn.get('status', 'UNKNOWN'),
                txn.get('reference', txn.get('transactionReference', 'N/A'))
            ])
            total_amount += amount
            total_fees += fee
        
        writer.writerow(['', '', '', '', 'Totals:', f'{total_amount:,.2f}', f'{total_fees:,.2f}', '', ''])
        writer.writerow([])
        
        # Summary
        writer.writerow(['SUMMARY'])
        writer.writerow(['Total Spent', f'{total_amount:,.2f}'])
        writer.writerow(['Total Fees', f'{total_fees:,.2f}'])
        writer.writerow(['Number of Transactions', len(transactions)])
        
        # Deduct credits if not premium
        if not is_premium and credit_cost > 0:
            new_balance = deduct_credits(current_user, credit_cost, report_type)
        
        # Log export event
        log_export_event(current_user, report_type, 'csv', success=True)
        
        # Return CSV file
        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'ficore_wallet_vas_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
        )
        
    except Exception as e:
        log_export_event(current_user, 'wallet_vas_csv', 'csv', success=False, error=str(e))
        return jsonify({
            'success': False,
            'message': f'Failed to generate VAS Transactions CSV: {str(e)}'
        }), 500

# NOTE: Due to message length limits, I'm providing the structure for the remaining endpoints.
# The Bills and Full Wallet endpoints follow the same pattern as above.
# 
# Remaining endpoints to implement:
# 1. /wallet-bills-pdf - Bills transactions PDF
# 2. /wallet-bills-csv - Bills transactions CSV  
# 3. /wallet-full-pdf - All wallet transactions PDF
# 4. /wallet-full-csv - All wallet transactions CSV
#
# Each follows the same structure:
# - Check user access
# - Parse date range
# - Query vas_transactions with appropriate filters
# - Generate PDF/CSV
# - Deduct credits
# - Return file
