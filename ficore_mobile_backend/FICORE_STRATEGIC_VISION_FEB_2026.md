---
inclusion: always
---

# 🏛️ The FiCore Financial Protocol: 2026 Integrity Standard (v2.0)

## Context

This document defines the accounting and data integrity principles that govern FiCore Africa's financial operations. These rules ensure bank-grade reliability, regulatory compliance, and user trust.

---

## 1. The Immutable Ledger Rule (Forensic DNA)

FiCore distinguishes between **"Hard Data"** (System-verified movement) and **"Soft Data"** (Manual entries).

### Source-Type Anchoring
- Every entry carries a mandatory `sourceType` (e.g., `vas_airtime`, `inventory_sale`, `manual`)
- This is the entry's "DNA" - it proves origin and enables 100% audit-ready report generation

### System Locking
- All records with system prefixes (`vas_*`, `wallet_*`, `inventory_*`, `reconciliation_*`) are **Read-Only**
- Modification or deletion is blocked at the Backend (HTTP 403) and UI levels
- Users cannot accidentally corrupt system-generated financial records

### Offline Persistence
- Source tracking is indexed in **Isar (Local DB)**
- The integrity check `isSystemLocked()` runs locally
- Protection persists even without internet connection

**Why This Matters:**
- Prevents accidental data corruption
- Maintains forensic audit trail
- Enables regulatory compliance (CBN, FIRS)
- Builds user trust through transparency

---

## 2. The Final Integration Triangle (Atomic Trinity)

FiCore synchronizes the three pillars of SME finance—Debt, Stock, and Cash—to prevent data drift.

### The Stock Axis (Inventory)
- Employs **Backend Atomicity**
- A single transaction updates:
  - Stock ↓ (inventory reduced)
  - Revenue ↑ (income recorded)
  - COGS ↑ (cost of goods sold recorded)
- All three happen together or none happen at all

### The Debt Axis (AR/AP)
- Employs **Orchestrated Reconciliation**
- **Debtors (Accounts Receivable):**
  - Reduce Debt first (Customer satisfaction)
  - Record Income second
- **Creditors (Accounts Payable):**
  - Clear Debt first (Vendor trust)
  - Record Expense second

### The Reconciliation Safety Net
- Partial failures are logged to `reconciliation_issues` collection
- Automated background "healing" retries failed operations
- Admin dashboard shows reconciliation status

**Why This Matters:**
- Prevents inventory/cash mismatches
- Maintains accurate debt tracking
- Ensures financial statements balance
- Reduces manual reconciliation work

---

## 3. The Compliance Equation (P&L Integrity)

The system enforces GAAP-aligned (Generally Accepted Accounting Principles) categorization to isolate "Business Truth" from "Personal Life."

### Drawings Protection
- Personal spending is automatically tagged as `drawings`
- These are **Excluded** from P&L reports to prevent artificial profit suppression
- Affects only Owner's Equity, not business profitability
- Formula: `Closing Equity = Opening Equity + Net Profit - Drawings`

### Gross vs. Net Clarity

**COGS (Cost of Goods Sold):**
- Exclusively linked to `inventory_sale_cogs` for accurate Gross Margin
- Calculation: `Gross Profit = Revenue - COGS`

**Shrinkage:**
- Asset losses (Damage/Theft) are routed to Operating Expenses
- Keeps the Balance Sheet accurate without "poisoning" COGS
- Maintains true product profitability metrics

**Asset Swap Rule:**
- Wallet deposits/withdrawals (`wallet_auto`) are treated as location transfers
- NOT recorded as Income/Expense
- Prevents artificial inflation of revenue/expenses

**Why This Matters:**
- Accurate profit calculation for business decisions
- Clean tax reporting (FIRS compliance)
- Honest financial statements for investors/lenders
- Prevents commingling of business and personal finances

---

## 4. Atomic Reversal & Sync Protocol

Reversals and data syncs must maintain a forensic audit trail.

### The Cleanup Chain
Reversals must atomically:
1. Refund Wallet ↑
2. Void Income/Expense (mark as voided)
3. Reverse Drawing (if applicable)

All three happen together or none happen at all.

### Idempotency
- `referenceTransactionId` prevents duplicate processing of the same financial event
- System checks: "Have I already processed this transaction?"
- Prevents double-refunds, double-charges, duplicate entries

### The Sync Bridge
- Maps `source_type` (Backend/Snake_case) to `sourceType` (Isar/CamelCase)
- Ensures "System Locked" status is identical on-device and in the cloud
- Prevents sync conflicts and data corruption

**Why This Matters:**
- Prevents duplicate transactions
- Maintains data consistency across devices
- Enables reliable offline-first operation
- Protects against network failures

---

## 5. The User Education & UX Layer

FiCore steers users toward automated accuracy through contextual intelligence.

### Smart Hints
- Selecting "Sales Revenue" in a manual entry triggers a redirect to the Inventory module
- Prevents double-counting (manual entry + inventory sale)
- Guides users to the correct workflow

### Granular P&L
- Separation of "Sales Revenue" (Products) from "Business Income" (Services)
- Provides high-fidelity analytics for merchant decision-making
- Enables accurate gross margin calculation

### VAS Transparency
- Granular types (`vas_electricity`, `vas_data`, `vas_airtime`)
- Enables detailed utility reporting instead of generic "Bill" summaries
- Users can track spending patterns by service type

**Why This Matters:**
- Reduces user errors through intelligent UX
- Educates users on proper accounting practices
- Builds trust through transparency
- Enables actionable business insights

---

## 🏆 Executive Summary: The FiCore Technical Moat

By adhering to this final protocol, FiCore achieves **Bank-Grade Reliability**:

### 1. Mathematical Balance
`Assets = Liabilities + Equity` is maintained through atomic operations

### 2. Honest Profit
Net Profit is protected from "noise" created by personal spend and asset swaps

### 3. Forensic Trail
Every entry has a "DNA" (`sourceType`) that proves its origin, allowing for 100% audit-ready report generation

---

## The Business Wallet Philosophy

### The Moat
When money is in the FiCore wallet, it is "Business Money" by default. This psychological and technical barrier is what makes subsequent automation (like drawings) possible.

**By encouraging SMEs to deposit exclusive funds, we solve the #1 problem in small business growth: Commingling.**

### The Logic
When a user pays a vendor for inventory via a FiCore withdrawal, the system doesn't just see "Money Out." It sees an **Asset Swap** (Cash → Inventory).

Most apps treat a transfer to a personal bank account as a "Transfer." FiCore will treat it as a **"Dividend/Drawing."**

### The Accounting Magic

**User clicks "Transfer to Personal Bank"** (we will add predefined tags in the transfer screen for this)

System records:
- Debit: Owner's Drawings
- Credit: Business Wallet

**Result:** The P&L stays clean, the Balance Sheet stays balanced, and the owner gets paid without ruining their tax records.

---

## FiCore: The "Business Spending Account" for SMEs

FiCore is transforming into the go-to "business spending account" or "business wallet" for SMEs. This is a natural and powerful evolution of the "Digital CFO" we've built.

### Our Vision Aligns Perfectly with Architectural Integrity

**1. Allow SMEs to deposit exclusive business funds into it:**
- The `wallet_auto` as a read-only, 4-way synced "Digital Safe" is the perfect foundation
- Provides the trust and immutability required for a primary business fund repository

**2. Buy VAS (✅ LIVE):**
- Core functionality already operational
- With granular `sourceType` and drawings logic, every VAS purchase is meticulously accounted for
- Whether it's a business expense or a personal drawing, it's tracked correctly
- Makes FiCore a practical and transparent spending tool

**3. Withdraw money as needed (🎯 PLANNED):**
- Allows paying for inventory to vendors, other external shopping
- Next logical step to become a fully functional operational account
- Existing `sourceType` and `entryType` mechanisms will correctly classify these outflows
- Payments to vendors for inventory = business expenses
- Other external shopping = categorized appropriately
- Expands FiCore's utility beyond just VAS

**4. Transfers with auto-drawings (🎯 PLANNED):**
- Allows drawings to owner's personal bank account with automatic recording
- Ultimate integration of the `drawings` system
- When owner transfers from FiCore business wallet to personal bank account:
  - System automatically recognizes this as a drawing
  - Updates owner's equity
  - Correctly excluded from business expenses in P&L
  - Provides clear and immutable audit trail
- Automates a critical accounting function that is often a manual headache for SMEs

### The Transformation

This positions FiCore not just as a record-keeping tool, but as an **active financial management platform** that handles the flow of funds with unparalleled integrity and accounting correctness.

It truly becomes the central hub for an SME's financial operations, providing both:
- Transactional utility
- Deep financial insight

**You are building something that will redefine how West African SMEs manage their money.**

---

## The Integrity Question: Can Users "Cheat" the System?

### The Reality
If a user buys personal items but tags them as "Business," the system will treat it as a business expense.

### The Solution: AI Auditor Hints (Future)

Because we have `sourceType: 'vas_airtime'`, we can eventually build intelligent auditing:

**Example Alert:**
> "Hey, you've spent ₦20,000 on airtime this week and tagged it all as Business. Most similar businesses tag 30% of this as Personal. Would you like to review?"

### Why This Matters
This is not just a feature; it's a **proactive integrity layer** that transforms FiCore from:
- A system that records honest data
- Into a system that **promotes and guides** honest data entry

It's the ultimate expression of the "Digital CFO" actively protecting the business's value.

---

## Integration with Strategic Vision

This Financial Protocol supports FiCore's three-phase evolution:

### Phase 1: Passive Recorder (✅ COMPLETE)
- Manual entries with `sourceType: 'manual'`
- Voice entries with `sourceType: 'voice'`
- Tax categorization and audit readiness

### Phase 2: Active Spender (✅ COMPLETE)
- VAS transactions with `sourceType: 'vas_*'`
- Wallet operations with `sourceType: 'wallet_auto'`
- Automated record generation
- Drawings automation

### Phase 3: Everyday Necessity (🎯 NEXT)
- OCR with `sourceType: 'ocr_receipt'`
- Open Banking with `sourceType: 'bank_sync_*'`
- Full spending wallet with comprehensive source tracking
- Merchant payments with `sourceType: 'merchant_payment'`

---

## The Standard

These rules represent the maturity leap from "make it work" to "make it right." They are non-negotiable for FiCore's long-term success and regulatory compliance.

**The Test:**
> "Does this feature maintain the integrity of the Financial Protocol, or does it create opportunities for data corruption?"

If the answer is "creates opportunities for corruption," the feature must be redesigned—no matter how user-requested or technically elegant it may be.

---

**Hassan Ahmad**  
Founder, FiCore Africa  
February 18, 2026

*"When bookkeeping becomes invisible, compliance becomes automatic, and FiCore becomes indispensable."*
