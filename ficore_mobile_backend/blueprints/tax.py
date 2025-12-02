from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from bson import ObjectId
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.pdf_generator import PDFGenerator
from tax_education_content import (
    TAX_EDUCATION_CONTENT, 
    CALCULATOR_LINKS,
    get_total_modules,
    get_content_categories,
    get_module_metadata,
    get_all_modules_metadata,
    get_module_content,
    get_module_reward
)


def init_tax_blueprint(mongo, token_required, serialize_doc):
    """Initialize the tax blueprint with database and auth decorator"""
    from utils.analytics_tracker import create_tracker
    tax_bp = Blueprint('tax', __name__, url_prefix='/tax')
    tracker = create_tracker(mongo.db)

    # Nigerian Personal Income Tax Bands (NTA 2026)
    TAX_BANDS = [
        {'min': 0, 'max': 800000, 'rate': 0.00},           # First ₦800,000 - Tax-free
        {'min': 800001, 'max': 3000000, 'rate': 0.15},     # ₦800,001 to ₦2,200,000 - 15%
        {'min': 3000001, 'max': 12000000, 'rate': 0.18},   # ₦2,200,001 to ₦9,000,000 - 18%
        {'min': 12000001, 'max': 25000000, 'rate': 0.21},  # ₦9,000,001 to ₦13,000,000 - 21%
        {'min': 25000001, 'max': 50000000, 'rate': 0.23},  # ₦13,000,001 to ₦25,000,000 - 23%
        {'min': 50000001, 'max': float('inf'), 'rate': 0.25}  # Above ₦50,000,000 - 25%
    ]

    # Maximum rent relief
    MAX_RENT_RELIEF = 500000  # ₦500,000

    def calculate_progressive_tax(taxable_income):
        """Calculate tax using progressive tax bands"""
        if taxable_income <= 0:
            return 0, []
        
        total_tax = 0
        breakdown = []

        for band in TAX_BANDS:
            band_min = band['min']
            band_max = band['max']
            band_rate = band['rate']

            # Skip if income doesn't reach this band
            if taxable_income <= band_min:
                break

            # Calculate the amount taxable in this band
            if taxable_income <= band_max:
                # Income falls within this band
                taxable_in_band = taxable_income - band_min
            else:
                # Income exceeds this band - tax the full band width
                taxable_in_band = band_max - band_min

            # Only process if there's income in this band
            if taxable_in_band <= 0:
                continue

            # Calculate tax for this band
            tax_in_band = taxable_in_band * band_rate
            total_tax += tax_in_band

            # Add to breakdown
            breakdown.append({
                'lower_bound': float(band_min),
                'upper_bound': float(band_max) if band_max != float('inf') else 999999999999.0,
                'rate': band_rate,
                'taxable_amount': taxable_in_band,
                'tax_amount': tax_in_band
            })

        return total_tax, breakdown

    @tax_bp.route('/calculate', methods=['POST'])
    @token_required
    def calculate_tax(current_user):
        """
        Calculate Personal Income Tax (PIT) for Employee and Entrepreneur
        Supports dual functionality based on entity_type parameter
        """
        try:
            data = request.get_json()

            # Validation
            errors = {}
            entity_type = data.get('entity_type')
            if not entity_type or entity_type not in ['employee', 'entrepreneur']:
                errors['entity_type'] = ['Entity type must be either "employee" or "entrepreneur"']

            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400

            tax_year = data.get('tax_year', datetime.utcnow().year)
            other_income = float(data.get('other_income', 0))
            # Optional: input_basis indicates whether frontend originally supplied monthly or annual values
            input_basis = data.get('input_basis', 'annual')

            if entity_type == 'employee':
                # Employee Tax Calculation
                # Validate employee-specific inputs
                annual_gross_salary = data.get('annual_gross_salary')
                if not annual_gross_salary or float(annual_gross_salary) <= 0:
                    errors['annual_gross_salary'] = ['Valid annual gross salary is required']

                if errors:
                    return jsonify({
                        'success': False,
                        'message': 'Validation failed',
                        'errors': errors
                    }), 400

                # Extract employee data
                annual_gross_salary = float(annual_gross_salary)
                car_cost = float(data.get('car_cost', 0))
                annual_housing_rental_value = float(data.get('annual_housing_rental_value', 0))
                annual_rent_paid_by_employee = float(data.get('annual_rent_paid_by_employee', 0))
                employee_pension_contributions = float(data.get('employee_pension_contributions', 0))
                nhis_contributions = float(data.get('nhis_contributions', 0))
                nhf_contributions = float(data.get('nhf_contributions', 0))

                # Calculate benefits
                car_benefit = car_cost * 0.05  # 5% of car cost
                housing_benefit = min(annual_housing_rental_value, annual_gross_salary * 0.20)  # Capped at 20% of salary

                # Calculate gross employment income
                gross_employment_income = annual_gross_salary + car_benefit + housing_benefit

                # Calculate total gross income
                total_gross_income = gross_employment_income + other_income

                # Calculate total statutory contributions
                total_statutory_contributions = employee_pension_contributions + nhis_contributions + nhf_contributions

                # Calculate rent relief
                rent_relief = min(annual_rent_paid_by_employee * 0.20, MAX_RENT_RELIEF)

                # Calculate chargeable income
                chargeable_income = max(0, total_gross_income - total_statutory_contributions - rent_relief)

                # Calculate tax using progressive bands
                total_tax, tax_breakdown = calculate_progressive_tax(chargeable_income)

                # Calculate effective tax rate
                effective_rate = (total_tax / total_gross_income * 100) if total_gross_income > 0 else 0

                # Calculate total annual deductions that directly reduce take-home pay
                total_annual_deductions_for_take_home_pay = total_statutory_contributions + rent_relief

                # Prepare calculation result
                calculation_result = {
                    'userId': current_user['_id'],
                    'entity_type': 'employee',
                    'tax_year': tax_year,
                    'calculation_date': datetime.utcnow(),
                    
                    # Employee-specific data
                    'annual_gross_salary': annual_gross_salary,
                    'car_cost': car_cost,
                    'car_benefit': car_benefit,
                    'annual_housing_rental_value': annual_housing_rental_value,
                    'housing_benefit': housing_benefit,
                    'gross_employment_income': gross_employment_income,
                    'other_income': other_income,
                    'total_gross_income': total_gross_income,
                    
                    # Deductions
                    'employee_pension_contributions': employee_pension_contributions,
                    'nhis_contributions': nhis_contributions,
                    'nhf_contributions': nhf_contributions,
                    'total_statutory_contributions': total_statutory_contributions,
                    'annual_rent_paid_by_employee': annual_rent_paid_by_employee,
                    'rent_relief': rent_relief,
                    # Sum of deductions that reduce take-home pay (annual)
                    'total_annual_deductions_for_take_home_pay': total_annual_deductions_for_take_home_pay,
                    
                    # Tax calculation
                    'chargeable_income': chargeable_income,
                    'tax_breakdown': tax_breakdown,
                    'total_tax': total_tax,
                    'effective_rate': effective_rate,
                    'net_income_after_tax': total_gross_income - total_tax,
                    
                    'createdAt': datetime.utcnow()
                }

            elif entity_type == 'entrepreneur':
                # Entrepreneur Tax Calculation
                # Validate entrepreneur-specific inputs
                total_annual_business_income = data.get('total_annual_business_income')
                if not total_annual_business_income or float(total_annual_business_income) <= 0:
                    errors['total_annual_business_income'] = ['Valid total annual business income is required']

                if errors:
                    return jsonify({
                        'success': False,
                        'message': 'Validation failed',
                        'errors': errors
                    }), 400

                # Extract entrepreneur data
                total_annual_business_income = float(total_annual_business_income)
                expenses = data.get('deductible_expenses', {})
                statutory_contributions = float(data.get('statutory_contributions', 0))
                annual_rent_paid_by_entrepreneur = float(data.get('annual_rent_paid_by_entrepreneur', 0))

                # Calculate total deductible expenses
                total_expenses = sum([
                    float(expenses.get('office_admin', 0)),
                    float(expenses.get('staff_wages', 0)),
                    float(expenses.get('business_travel', 0)),
                    float(expenses.get('rent_utilities', 0)),
                    float(expenses.get('marketing_sales', 0)),
                    float(expenses.get('cogs', 0))
                ])

                # Calculate net business income
                net_business_income = total_annual_business_income - total_expenses

                # Calculate total gross income
                total_gross_income = net_business_income + other_income

                # Calculate rent relief
                rent_relief = min(annual_rent_paid_by_entrepreneur * 0.20, MAX_RENT_RELIEF)

                # Calculate chargeable income
                chargeable_income = max(0, total_gross_income - statutory_contributions - rent_relief)

                # Calculate tax using progressive bands
                total_tax, tax_breakdown = calculate_progressive_tax(chargeable_income)

                # Calculate effective tax rate
                effective_rate = (total_tax / total_gross_income * 100) if total_gross_income > 0 else 0

                # Prepare calculation result
                # Calculate total annual deductions that directly reduce take-home pay
                total_annual_deductions_for_take_home_pay = statutory_contributions + rent_relief

                calculation_result = {
                    'userId': current_user['_id'],
                    'entity_type': 'entrepreneur',
                    'tax_year': tax_year,
                    'calculation_date': datetime.utcnow(),
                    
                    # Entrepreneur-specific data
                    'total_annual_business_income': total_annual_business_income,
                    'deductible_expenses': {
                        'office_admin': float(expenses.get('office_admin', 0)),
                        'staff_wages': float(expenses.get('staff_wages', 0)),
                        'business_travel': float(expenses.get('business_travel', 0)),
                        'rent_utilities': float(expenses.get('rent_utilities', 0)),
                        'marketing_sales': float(expenses.get('marketing_sales', 0)),
                        'cogs': float(expenses.get('cogs', 0)),
                        'total': total_expenses
                    },
                    'net_business_income': net_business_income,
                    'other_income': other_income,
                    'total_gross_income': total_gross_income,
                    
                    # Deductions
                    'statutory_contributions': statutory_contributions,
                    'annual_rent_paid_by_entrepreneur': annual_rent_paid_by_entrepreneur,
                    'rent_relief': rent_relief,
                    # Sum of deductions that reduce take-home pay (annual)
                    'total_annual_deductions_for_take_home_pay': total_annual_deductions_for_take_home_pay,
                    
                    # Tax calculation
                    'chargeable_income': chargeable_income,
                    'tax_breakdown': tax_breakdown,
                    'total_tax': total_tax,
                    'effective_rate': effective_rate,
                    'net_income_after_tax': total_gross_income - total_tax,
                    
                    'createdAt': datetime.utcnow()
                }

            # Save calculation to history
            result = mongo.db.tax_calculations.insert_one(calculation_result)
            calculation_id = str(result.inserted_id)
            
            # Track tax calculation event
            try:
                tracker.track_tax_calculation(
                    user_id=current_user['_id'],
                    tax_year=tax_year
                )
            except Exception as e:
                print(f"Analytics tracking failed: {e}")

            # Prepare response
            response_data = serialize_doc(calculation_result.copy())
            response_data['id'] = calculation_id
            response_data['calculation_date'] = response_data['calculation_date'].isoformat() + 'Z'
            response_data['createdAt'] = response_data['createdAt'].isoformat() + 'Z'

            return jsonify({
                'success': True,
                'data': response_data,
                'message': f'{entity_type.capitalize()} tax calculated successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to calculate tax',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/history', methods=['GET'])
    @token_required
    def get_tax_history(current_user):
        """Get user's tax calculation history with pagination"""
        try:
            page = int(request.args.get('page', 1))
            limit = int(request.args.get('limit', 20))
            tax_year = request.args.get('tax_year')

            # Build query
            query = {'userId': current_user['_id']}
            if tax_year:
                query['tax_year'] = int(tax_year)

            # Get calculations with pagination
            skip = (page - 1) * limit
            calculations = list(
                mongo.db.tax_calculations
                .find(query)
                .sort('calculation_date', -1)
                .skip(skip)
                .limit(limit)
            )
            total = mongo.db.tax_calculations.count_documents(query)

            # Serialize calculations
            calculation_list = []
            for calc in calculations:
                calc_data = serialize_doc(calc.copy())
                calc_data['calculation_date'] = calc_data.get('calculation_date', datetime.utcnow()).isoformat() + 'Z'
                calc_data['createdAt'] = calc_data.get('createdAt', datetime.utcnow()).isoformat() + 'Z'
                calculation_list.append(calc_data)

            return jsonify({
                'success': True,
                'data': {
                    'calculations': calculation_list,
                    'pagination': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'pages': (total + limit - 1) // limit
                    }
                },
                'message': 'Tax history retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve tax history',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/education', methods=['GET'])
    @token_required
    def get_tax_education(current_user):
        """Get tax education modules - uses single source of truth from tax_education_content.py"""
        try:
            language = request.args.get('language', 'en')

            # Get all modules from single source of truth
            modules = get_all_modules_metadata(language)

            # Get user's progress
            progress = list(mongo.db.tax_education_progress.find({
                'userId': current_user['_id']
            }))

            # Add completion status to modules
            completed_modules = {p['module_id']: p for p in progress}
            for module in modules:
                module_progress = completed_modules.get(module['id'])
                module['completed'] = module_progress.get('completed', False) if module_progress else False
                module['completed_at'] = module_progress.get('completed_at').isoformat() + 'Z' if module_progress and module_progress.get('completed_at') else None

            return jsonify({
                'success': True,
                'data': {
                    'modules': modules,
                    'total_modules': len(modules),
                    'completed_modules': len([m for m in modules if m['completed']]),
                    'total_credits_available': sum(m['coins_reward'] for m in modules),
                    'credits_earned': sum(m['coins_reward'] for m in modules if m['completed'])
                },
                'message': 'Tax education modules retrieved successfully'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve tax education',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/education/progress', methods=['GET'])
    @token_required
    def get_education_progress(current_user):
        """Get user's tax education progress - dynamically calculated"""
        try:
            # Get total modules dynamically from single source of truth
            total_modules = get_total_modules()
            
            # Get user's completed modules
            completed_progress = list(mongo.db.tax_education_progress.find({
                'userId': current_user['_id'],
                'completed': True
            }))
            
            completed_modules = len(completed_progress)
            
            # Calculate total credits earned (1 credit per completed module)
            total_credits_earned = completed_modules  # Each module gives 1 credit
            
            # Calculate progress percentage
            progress_percentage = (completed_modules / total_modules * 100) if total_modules > 0 else 0
            
            return jsonify({
                'success': True,
                'data': {
                    'total_modules': total_modules,
                    'completed_modules': completed_modules,
                    'total_credits_earned': total_credits_earned,
                    'progress_percentage': round(progress_percentage, 2)
                },
                'message': 'Education progress retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve education progress',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/education/progress', methods=['POST'])
    @token_required
    def update_education_progress(current_user):
        """Update user's progress on tax education modules"""
        try:
            data = request.get_json()

            # Validation
            errors = {}
            if not data.get('module_id'):
                errors['module_id'] = ['Module ID is required']
            if 'completed' not in data:
                errors['completed'] = ['Completion status is required']

            if errors:
                return jsonify({
                    'success': False,
                    'message': 'Validation failed',
                    'errors': errors
                }), 400

            module_id = data['module_id']
            completed = data['completed']

            # Check if progress record exists
            existing_progress = mongo.db.tax_education_progress.find_one({
                'userId': current_user['_id'],
                'module_id': module_id
            })

            if existing_progress:
                # Update existing progress
                mongo.db.tax_education_progress.update_one(
                    {'_id': existing_progress['_id']},
                    {
                        '$set': {
                            'completed': completed,
                            'completed_at': datetime.utcnow() if completed else None,
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                progress_id = str(existing_progress['_id'])
            else:
                # Create new progress record
                progress_data = {
                    'userId': current_user['_id'],
                    'module_id': module_id,
                    'completed': completed,
                    'completed_at': datetime.utcnow() if completed else None,
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
                result = mongo.db.tax_education_progress.insert_one(progress_data)
                progress_id = str(result.inserted_id)

            # Award FiCore Credits if module completed
            credits_awarded = 0
            if completed and not (existing_progress and existing_progress.get('completed')):
                # Get reward from single source of truth
                credits_awarded = get_module_reward(module_id)
                
                if credits_awarded > 0:
                    # Update user's FiCore Credit balance
                    mongo.db.users.update_one(
                        {'_id': current_user['_id']},
                        {'$inc': {'ficoreCreditBalance': credits_awarded}}
                    )
                    
                    # Create CreditTransaction record for traceability
                    from bson import ObjectId
                    transaction_data = {
                        '_id': ObjectId(),
                        'userId': current_user['_id'],
                        'amount': float(credits_awarded),
                        'type': 'credit',
                        'description': f'Tax Education Reward - {module_id.replace("_", " ").title()}',
                        'status': 'completed',
                        'action': 'tax_education_reward',
                        'createdAt': datetime.utcnow(),
                        'updatedAt': datetime.utcnow(),
                        'metadata': {
                            'source': 'tax_education',
                            'moduleId': module_id
                        }
                    }
                    mongo.db.creditTransactions.insert_one(transaction_data)

            return jsonify({
                'success': True,
                'data': {
                    'progress_id': progress_id,
                    'module_id': module_id,
                    'completed': completed,
                    'credits_awarded': credits_awarded
                },
                'message': f'Progress updated successfully{" - " + str(credits_awarded) + " FiCore Credit" + ("s" if credits_awarded != 1 else "") + " awarded!" if credits_awarded > 0 else ""}'
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to update education progress',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/education/<module_id>/complete', methods=['POST'])
    @token_required
    def complete_education_module(current_user, module_id):
        """Mark a tax education module as complete and award FiCore Credits"""
        try:
            # Check if progress record exists
            existing_progress = mongo.db.tax_education_progress.find_one({
                'userId': current_user['_id'],
                'module_id': module_id
            })

            if existing_progress:
                # Update existing progress
                mongo.db.tax_education_progress.update_one(
                    {'_id': existing_progress['_id']},
                    {
                        '$set': {
                            'completed': True,
                            'completed_at': datetime.utcnow(),
                            'updatedAt': datetime.utcnow()
                        }
                    }
                )
                progress_id = str(existing_progress['_id'])
            else:
                # Create new progress record
                progress_data = {
                    'userId': current_user['_id'],
                    'module_id': module_id,
                    'completed': True,
                    'completed_at': datetime.utcnow(),
                    'createdAt': datetime.utcnow(),
                    'updatedAt': datetime.utcnow()
                }
                result = mongo.db.tax_education_progress.insert_one(progress_data)
                progress_id = str(result.inserted_id)

            # Check if module was already completed (to prevent duplicate rewards)
            already_completed = existing_progress and existing_progress.get('completed')
            credits_awarded = 0 if already_completed else 1  # 1 FC per module, but only if not already completed
            
            # Note: Credit awarding is now handled by the FC cost system via /credits/award endpoint
            # This endpoint only marks the module as complete

            return jsonify({
                'success': True,
                'data': {
                    'progress_id': progress_id,
                    'module_id': module_id,
                    'completed': True,
                    'credits_will_be_awarded': credits_awarded
                },
                'message': 'Module completed successfully!' + (' Credits will be awarded by the FC system.' if credits_awarded > 0 else ' Module was already completed.')
            })

        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to complete education module',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/education/content/<module_id>', methods=['GET'])
    @token_required
    def get_education_content(current_user, module_id):
        """Get detailed content for a specific education module - uses single source of truth"""
        try:
            # Get module content from single source of truth
            content_data = get_module_content(module_id)
            
            if not content_data:
                return jsonify({
                    'success': False,
                    'message': 'Module not found',
                    'errors': {'module_id': ['Invalid module ID']}
                }), 404
            
            # Get calculator links
            calculator_links = []
            for calc_type in content_data.get('calculator_links', []):
                if calc_type in CALCULATOR_LINKS:
                    calculator_links.append({
                        'type': calc_type,
                        'name': f"{calc_type.title()} Tax Calculator",
                        'route': CALCULATOR_LINKS[calc_type]
                    })
            
            # Check if user has completed this module
            user_progress = mongo.db.tax_education_progress.find_one({
                'userId': current_user['_id'],
                'module_id': module_id
            })
            
            is_completed = user_progress.get('completed', False) if user_progress else False
            completed_at = user_progress.get('completed_at') if user_progress else None
            
            response_data = {
                'module_id': content_data['module_id'],
                'content': content_data['content'],
                'category': content_data['category'],
                'calculator_links': calculator_links,
                'is_completed': is_completed,
                'completed_at': completed_at.isoformat() + 'Z' if completed_at else None
            }
            
            return jsonify({
                'success': True,
                'data': response_data,
                'message': 'Module content retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve module content',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/education/categories', methods=['GET'])
    @token_required
    def get_education_categories(current_user):
        """Get education modules organized by categories - uses single source of truth"""
        try:
            language = request.args.get('language', 'en')
            
            # Get all modules from single source of truth
            modules = get_all_modules_metadata(language)
            
            # Get categories dynamically
            categories_map = get_content_categories()
            
            # Organize by categories
            categorized_modules = {}
            for category, module_ids in categories_map.items():
                categorized_modules[category] = {
                    'name': category.title(),
                    'modules': [m for m in modules if m['id'] in module_ids]
                }
            
            return jsonify({
                'success': True,
                'data': {
                    'categories': categorized_modules,
                    'calculator_links': CALCULATOR_LINKS
                },
                'message': 'Education categories retrieved successfully'
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to retrieve education categories',
                'errors': {'general': [str(e)]}
            }), 500

    @tax_bp.route('/export-pdf', methods=['POST'])
    @token_required
    def export_tax_pdf(current_user):
        """Export tax calculation as PDF with credit deduction"""
        try:
            request_data = request.get_json()
            calculation_id = request_data.get('calculation_id')
            
            if not calculation_id:
                return jsonify({
                    'success': False,
                    'message': 'Calculation ID is required',
                    'errors': {'calculation_id': ['Calculation ID is required']}
                }), 400
            
            # Credit cost for tax report export
            credit_cost = 2
            current_balance = current_user.get('ficoreCreditBalance', 0.0)
            
            # Check if user has enough credits
            if current_balance < credit_cost:
                return jsonify({
                    'success': False,
                    'message': 'Insufficient credits',
                    'errors': {
                        'credits': [f'You need {credit_cost} FC to export this tax report. Current balance: {current_balance} FC']
                    },
                    'data': {
                        'required': credit_cost,
                        'current': current_balance,
                        'shortfall': credit_cost - current_balance
                    }
                }), 402  # Payment Required
            
            # Get tax calculation
            try:
                tax_calculation = mongo.db.tax_calculations.find_one({'_id': ObjectId(calculation_id)})
            except:
                return jsonify({
                    'success': False,
                    'message': 'Invalid calculation ID',
                    'errors': {'calculation_id': ['Invalid calculation ID format']}
                }), 400
            
            if not tax_calculation:
                return jsonify({
                    'success': False,
                    'message': 'Tax calculation not found',
                    'errors': {'calculation_id': ['Tax calculation not found']}
                }), 404
            
            # Verify ownership
            if tax_calculation['userId'] != current_user['_id']:
                return jsonify({
                    'success': False,
                    'message': 'Unauthorized access',
                    'errors': {'general': ['You do not have permission to access this calculation']}
                }), 403
            
            # Prepare user data
            user_data = {
                'firstName': current_user.get('firstName', ''),
                'lastName': current_user.get('lastName', ''),
                'email': current_user.get('email', '')
            }
            
            # Generate PDF
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.generate_tax_report(user_data, tax_calculation)
            
            # Deduct credits from user balance
            new_balance = current_balance - credit_cost
            mongo.db.users.update_one(
                {'_id': current_user['_id']},
                {'$set': {'ficoreCreditBalance': new_balance}}
            )
            
            # Record credit transaction
            credit_transaction = {
                'userId': current_user['_id'],
                'type': 'deduction',
                'amount': -credit_cost,
                'description': f'Tax Report Export - {tax_calculation.get("tax_year", datetime.utcnow().year)}',
                'balanceBefore': current_balance,
                'balanceAfter': new_balance,
                'status': 'completed',
                'createdAt': datetime.utcnow()
            }
            mongo.db.credit_transactions.insert_one(credit_transaction)
            
            # Return PDF file
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=True,
                download_name=f'ficore_tax_report_{tax_calculation.get("tax_year", datetime.utcnow().year)}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.pdf'
            )
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': 'Failed to generate tax PDF export',
                'errors': {'general': [str(e)]}
            }), 500

    return tax_bp
