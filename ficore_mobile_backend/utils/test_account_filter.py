"""
Test Account Filter Utility
Created: Feb 21, 2026

Purpose: Exclude test accounts from treasury metrics and analytics

Test Account Identification Criteria:
1. Email contains "test" (case-insensitive)
2. Email domain is @ficoreafrica.com
3. Password is "Abumeemah123!" (manually created test accounts)

Total Test Accounts: 14
- Only 1 has VAS/deposit activity: premiumtester@ficoreafrica.com (₦31,000 in transactions)
- Other 13 have only FC signup bonuses (no VAS/deposit activity)
"""

from bson import ObjectId

# ===== TEST ACCOUNT LISTS =====

# Explicit test account emails (identified via password verification: "Abumeemah123!")
# Total: 32 accounts (33 found, but warpiiv@gmail.com excluded - see note below)
# Verified: Feb 21, 2026
#
# NOTE: warpiiv@gmail.com uses test password but is REAL USER (founder using own app)
#       - 1,450 FCs, ₦3,000 real spending (15 SUCCESS transactions)
#       - ₦5,021 deposits, ₦241 current wallet balance
#       - Excluded from test list to keep metrics accurate (real money, real usage)
#       - (₦11,059 figure includes 30 FAILED test transactions - not real spending)
TEST_ACCOUNT_EMAILS = [
    '0kalshingi@gmail.com',
    'bashbasi@gmail.com',
    'batajesu@gmail.com',
    'bossmustee@gmail.com',
    'ficoretester@gmail.com',
    'furerausain@gmail.com',
    'holartim@gmail.com',
    'kalidyamah@gmail.com',
    'kamalharuna@gmail.com',
    'kotenemo889@gmail.com',
    'kunifasara@gmail.com',
    'makesaisai@gmail.com',
    'mokomali@gmail.com',
    'mustaphakaka@gmail.com',
    'nagin@gmail.com',
    'newtest@gmail.com',
    'nhooksapp@gmail.com',
    'nillima@gmail.com',
    'nimakemk@gmail.com',
    'normanimi@gmail.com',
    'numaladi01@gmail.com',
    'olupona@gmail.com',
    'onetwo@gmail.com',
    'rashid@gmail.com',
    'robbalaan@gmail.com',
    'salemanalu@gmail.com',
    'sparadad@gmail.com',
    'sunag@gmail.com',
    'tailisjera@gmail.com',
    'test@gmail.com',
    'test@test.com',
    'testuser1@gmail.com',
    # warpiiv@gmail.com - EXCLUDED (real user, founder using own app with real money)
    # Additional test accounts from @ficoreafrica.com domain
    'premiumtester@ficoreafrica.com',
    'newuser@test.com',
    'test1759502800077@ficore.com',
    'test1759590317560@ficore.com',
    'test@ficore.com',
    'test_isd1vuh5@example.com',
    'test_rym0otvp@example.com',
    'testimonyventures23@gmail.com',
    'testuser@example.com',
]

# Test account user IDs (for direct exclusion)
TEST_ACCOUNT_USER_IDS = [
    # Password-verified accounts (Abumeemah123!)
    ObjectId('690e6b3436344ee7516e32e2'),  # 0kalshingi@gmail.com
    ObjectId('6947ce4588b030b27eb9a7be'),  # bashbasi@gmail.com
    ObjectId('69628468da4d4eb555860e0d'),  # batajesu@gmail.com
    ObjectId('6946cb6b27f1c93a908399f9'),  # bossmustee@gmail.com
    ObjectId('698b7f54eb8236a774a6e36a'),  # ficoretester@gmail.com
    ObjectId('69459eb41f89dc4fd82142de'),  # furerausain@gmail.com
    ObjectId('69624e0dda4d4eb555860619'),  # holartim@gmail.com
    ObjectId('69616e742a6948d6a1fc4fe5'),  # kalidyamah@gmail.com
    ObjectId('6945304b5a3f75f2eb5bfda8'),  # kamalharuna@gmail.com
    ObjectId('694580c664445cf18ba203c9'),  # kotenemo889@gmail.com
    ObjectId('698b32a242fe8bb4297e293e'),  # kunifasara@gmail.com
    ObjectId('69626f46da4d4eb555860c7a'),  # makesaisai@gmail.com
    ObjectId('6964ca3ada4d4eb5558615d8'),  # mokomali@gmail.com
    ObjectId('694823bbe0c1f2ef8facd59a'),  # mustaphakaka@gmail.com
    ObjectId('694d8d89e0c1f2ef8fad012b'),  # nagin@gmail.com
    ObjectId('698b10a2f4d2d58b6228f94e'),  # newtest@gmail.com
    ObjectId('694463715a3f75f2eb5bfcf4'),  # nhooksapp@gmail.com
    ObjectId('6988c92faf262b1385109dd9'),  # nillima@gmail.com
    ObjectId('694c248be0c1f2ef8facf856'),  # nimakemk@gmail.com
    ObjectId('69458e7e64445cf18ba20526'),  # normanimi@gmail.com
    ObjectId('69456829c1e48df38fe009b3'),  # numaladi01@gmail.com
    ObjectId('6964df01da4d4eb555861820'),  # olupona@gmail.com
    ObjectId('68ecb8eb7a690974d7942078'),  # onetwo@gmail.com
    ObjectId('694d976ee0c1f2ef8fad0238'),  # rashid@gmail.com
    ObjectId('69626336da4d4eb555860a0c'),  # robbalaan@gmail.com
    ObjectId('6964c822da4d4eb5558614ed'),  # salemanalu@gmail.com
    ObjectId('696357c4da4d4eb55586141a'),  # sparadad@gmail.com
    ObjectId('694d8701e0c1f2ef8fad0006'),  # sunag@gmail.com
    ObjectId('69611ac22a6948d6a1fc4e1f'),  # tailisjera@gmail.com
    ObjectId('68eabba4f9ffbc1fe57302e2'),  # test@gmail.com
    ObjectId('68e6b390ff54aa11da63548c'),  # test@test.com
    ObjectId('6962a732da4d4eb555861166'),  # testuser1@gmail.com
    # warpiiv@gmail.com - EXCLUDED FROM TEST LIST (real user, founder using own app with real money)
    # ObjectId('68e11e3bd594fe6a85546181'),  # ❌ DO NOT INCLUDE - Real user with ₦3,000 real spending
    # Additional test accounts from domain/pattern matching
    ObjectId('68dfde612af1af8d274c5d23'),  # premiumtester@ficoreafrica.com
    ObjectId('68dfe1d12af1af8d274c5d26'),  # newuser@test.com
    ObjectId('68e13786067ecd5f1c9ae22e'),  # test1759502800077@ficore.com
    ObjectId('68e137af067ecd5f1c9ae22f'),  # test1759590317560@ficore.com
    ObjectId('68e13a423d66c92a9d059c6a'),  # test@ficore.com
    ObjectId('68e13ae83d66c92a9d059c6b'),  # test_isd1vuh5@example.com
    ObjectId('68e13b0f3d66c92a9d059c6e'),  # test_rym0otvp@example.com
    ObjectId('6935671539904b0b35f71595'),  # testimonyventures23@gmail.com
    ObjectId('698b7ac436cf94f3c6a6e62c'),  # testuser@example.com
]

# Test account domains (for pattern matching)
TEST_ACCOUNT_DOMAINS = [
    '@ficoreafrica.com',  # Internal test accounts
]

# Test account password (for identification)
TEST_ACCOUNT_PASSWORD = 'Abumeemah123!'


# ===== UTILITY FUNCTIONS =====

def is_test_account(email):
    """
    Check if email belongs to a test account
    
    Args:
        email (str): User email address
        
    Returns:
        bool: True if test account, False otherwise
    """
    if not email:
        return False
    
    email_lower = email.lower()
    
    # Check exact matches
    if email_lower in [e.lower() for e in TEST_ACCOUNT_EMAILS]:
        return True
    
    # Check domain matches
    for domain in TEST_ACCOUNT_DOMAINS:
        if email_lower.endswith(domain.lower()):
            return True
    
    # Check if email contains "test"
    if 'test' in email_lower:
        return True
    
    return False


def get_test_account_user_ids(mongo=None):
    """
    Get list of test account user IDs
    
    Args:
        mongo: MongoDB connection (optional, uses hardcoded list if not provided)
        
    Returns:
        list: List of ObjectId instances for test accounts
    """
    # Return hardcoded list (faster, no DB query needed)
    return TEST_ACCOUNT_USER_IDS


def add_test_account_exclusion(query, mongo=None):
    """
    Add test account exclusion to MongoDB query
    
    Args:
        query (dict): MongoDB query dictionary
        mongo: MongoDB connection (optional)
        
    Returns:
        dict: Updated query with test account exclusion
    """
    test_user_ids = get_test_account_user_ids(mongo)
    
    if 'userId' in query:
        # If userId already in query, add $nin
        if isinstance(query['userId'], dict):
            # userId is already a dict (e.g., {'$in': [...]})
            query['userId']['$nin'] = test_user_ids
        else:
            # userId is a simple value (e.g., ObjectId('...'))
            # Convert to dict with $eq and $nin
            original_user_id = query['userId']
            query['userId'] = {
                '$eq': original_user_id,
                '$nin': test_user_ids
            }
    else:
        # Add userId exclusion
        query['userId'] = {'$nin': test_user_ids}
    
    return query


def filter_test_accounts_from_list(users):
    """
    Filter test accounts from a list of user documents
    
    Args:
        users (list): List of user documents (must have 'email' field)
        
    Returns:
        list: Filtered list without test accounts
    """
    return [u for u in users if not is_test_account(u.get('email', ''))]


def count_real_users(mongo):
    """
    Count real users (excluding test accounts)
    
    Args:
        mongo: MongoDB connection
        
    Returns:
        int: Count of real users
    """
    test_user_ids = get_test_account_user_ids(mongo)
    return mongo.db.users.count_documents({'_id': {'$nin': test_user_ids}})


def get_test_account_stats(mongo):
    """
    Get statistics about test accounts (for debugging/verification)
    
    Args:
        mongo: MongoDB connection
        
    Returns:
        dict: Test account statistics
    """
    test_user_ids = get_test_account_user_ids(mongo)
    
    # Count VAS transactions
    vas_txns = mongo.db.vas_transactions.count_documents({
        'userId': {'$in': test_user_ids},
        'status': 'SUCCESS'
    })
    
    # Calculate total spending
    vas_txns_list = list(mongo.db.vas_transactions.find({
        'userId': {'$in': test_user_ids},
        'status': 'SUCCESS'
    }))
    total_spending = sum(t.get('amount', 0) for t in vas_txns_list)
    
    # Count FC credits
    test_users = list(mongo.db.users.find({'_id': {'$in': test_user_ids}}))
    total_fc = sum(u.get('ficoreCreditBalance', 0) for u in test_users)
    
    return {
        'testAccountCount': len(test_user_ids),
        'vasTransactions': vas_txns,
        'totalSpending': round(total_spending, 2),
        'totalFcCredits': round(total_fc, 2),
        'testAccountEmails': TEST_ACCOUNT_EMAILS
    }


# ===== USAGE EXAMPLES =====

"""
Example 1: Exclude test accounts from VAS query
-------------------------------------------------
from utils.test_account_filter import add_test_account_exclusion

vas_query = {
    'status': 'SUCCESS',
    'type': {'$in': ['AIRTIME', 'DATA', 'BILLS']}
}
vas_query = add_test_account_exclusion(vas_query, mongo)
vas_transactions = list(mongo.db.vas_transactions.find(vas_query))


Example 2: Filter test accounts from user list
-----------------------------------------------
from utils.test_account_filter import filter_test_accounts_from_list

all_users = list(mongo.db.users.find({}))
real_users = filter_test_accounts_from_list(all_users)


Example 3: Check if email is test account
------------------------------------------
from utils.test_account_filter import is_test_account

if is_test_account(user_email):
    print("This is a test account - excluding from metrics")


Example 4: Get test account statistics
---------------------------------------
from utils.test_account_filter import get_test_account_stats

stats = get_test_account_stats(mongo)
print(f"Test accounts: {stats['testAccountCount']}")
print(f"Test spending: ₦{stats['totalSpending']:,.2f}")
"""
