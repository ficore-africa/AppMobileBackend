
"""Payment utilities used across the backend for normalizing and
validating payment-related fields.

This module provides small, deterministic helpers used by the
`income` and `expenses` blueprints:

- normalize_payment_method(value) -> str | None
- validate_payment_method(value) -> bool
- normalize_sales_type(value) -> str | None
- validate_sales_type(value) -> bool

The functions are intentionally lightweight and dependency-free so
they can be used during request validation without side effects.
"""

from typing import Optional

# Canonical mappings for payment methods and sales types. Keep these
# mappings stable so database values remain predictable.
_PAYMENT_METHOD_MAP = {
	'cash': 'cash',
	'card': 'card',
	'debit_card': 'card',
	'credit_card': 'card',
	'transfer': 'transfer',
	'bank_transfer': 'transfer',
	'pos': 'card',
	'mobile_money': 'mobile_money',
	'momo': 'mobile_money',
}

_SALES_TYPE_MAP = {
	'cash': 'cash',
	'credit': 'credit',
	'card': 'card',
	'online': 'online',
}


def _normalize_lookup(value: Optional[str], mapping: dict) -> Optional[str]:
	"""Internal helper: normalize a value using mapping, or return None.

	Accepts None and returns None. Performs case-insensitive matching and
	trims whitespace.
	"""
	if value is None:
		return None
	if not isinstance(value, str):
		try:
			value = str(value)
		except Exception:
			return None
	key = value.strip().lower()
	return mapping.get(key)


def normalize_payment_method(value: Optional[str]) -> Optional[str]:
	"""Return a canonical payment method string or None.

	Example: 'Credit_Card' -> 'card', 'MOMO' -> 'mobile_money'
	"""
	return _normalize_lookup(value, _PAYMENT_METHOD_MAP) or None


def validate_payment_method(value: Optional[str]) -> bool:
	"""Return True if the provided payment method is recognized."""
	return _normalize_lookup(value, _PAYMENT_METHOD_MAP) is not None


def normalize_sales_type(value: Optional[str]) -> Optional[str]:
	"""Return a canonical sales type string or None.

	Example: 'CASH' -> 'cash'
	"""
	return _normalize_lookup(value, _SALES_TYPE_MAP) or None


def validate_sales_type(value: Optional[str]) -> bool:
	"""Return True if the provided sales type is recognized."""
	return _normalize_lookup(value, _SALES_TYPE_MAP) is not None
