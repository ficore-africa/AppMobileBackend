"""
Wallet Reports - Bills and Full Wallet Endpoints
Add these to reports.py after the VAS endpoints
"""

# Bills Transactions Report - PDF
@reports_bp.route('/wallet-bills-pdf', methods=['POST'])
@token_required
def export_wallet_bills_pdf(current_user):
    """Export Bills transactions as PDF"""
    try:
        request_data = request.get_json() or {}
        report_type = 'wallet_bills_pdf'
        
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
        
        start_date, end_date = parse_date_range(request_data)
        
        query = {
            'userId': ObjectId(str(current_user['_id'])),
            'type': {'$in': ['BILLS', 'BILL', 'ELECTRICITY', 'CABLE_TV', 'WATER', 'INTERNET']}
        }
        
        if start_date or end_date:
            query['createdAt'] = {}
            if start_date:
                query['createdAt']['$gte'] = start_date
            if end_date:
                query['createdAt']['$lte'] = end_date
        
        transactions = list(mongo.db.vas_transactions.find(query).sort('createdAt', -1))
