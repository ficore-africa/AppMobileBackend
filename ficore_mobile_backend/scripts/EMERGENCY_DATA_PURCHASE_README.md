# 🚨 FiCore Emergency Data Purchase

Buy data when you're out of data and can't access the FiCore app!

## Quick Start

### Default Purchase (₦500 MTN data)
```bash
python buy_data.py
```

### Custom Amount
```bash
python buy_data.py 200      # ₦200 MTN data
python buy_data.py 500      # ₦500 MTN data (1GB)
python buy_data.py 1000     # ₦1000 MTN data
```

### Different Network
```bash
python buy_data.py 500 mtn      # ₦500 MTN data
python buy_data.py 500 airtel   # ₦500 Airtel data
python buy_data.py 500 glo      # ₦500 Glo data
python buy_data.py 500 9mobile  # ₦500 9mobile data
```

### Different Phone Number
```bash
python buy_data.py 500 mtn 08012345678
```

## Common Use Cases

### Your Regular Purchase (1GB for ₦500)
```bash
python buy_data.py 500
```

### Quick ₦200 Top-up
```bash
python buy_data.py 200
```

### Buy for Someone Else
```bash
python buy_data.py 500 mtn 08098765432
```

## Available Networks

- **mtn** - MTN Nigeria
- **airtel** - Airtel Nigeria
- **glo** - Glo Nigeria
- **9mobile** - 9mobile Nigeria

## Common Data Amounts

| Amount | Typical Data | Networks |
|--------|--------------|----------|
| ₦100 | 100-200MB | All |
| ₦200 | 230-350MB | All |
| ₦500 | 1GB | All |
| ₦1000 | 2-3GB | All |
| ₦1500 | 4-6GB | All |
| ₦2000 | 6-10GB | All |

## What Happens

1. **Login** - Authenticates with your FiCore account
2. **Check Balance** - Verifies you have enough funds
3. **Find Plan** - Searches for matching data plan
4. **Purchase** - Initiates the purchase
5. **Confirm** - Shows transaction details
6. **Deliver** - Data arrives within 30-60 seconds

## Requirements

- Python 3.6+
- Internet connection (WiFi or borrowed hotspot)
- Sufficient balance in FiCore wallet

## Troubleshooting

### "Insufficient balance"
```bash
# Check your balance first
python debug_wallet_and_networks.py
```

### "No plan found"
The script will show available amounts:
```
Available plans:
   ₦200 - 230MB Daily Plan
   ₦500 - 1GB Weekly Plan
   ₦1000 - 2GB Monthly Plan
```

### "Network not found"
Make sure you're using lowercase:
- ✅ `python buy_data.py 500 mtn`
- ❌ `python buy_data.py 500 MTN`

## Examples

### Morning Routine (1GB MTN)
```bash
python buy_data.py 500
```

### Emergency Top-up (₦200)
```bash
python buy_data.py 200
```

### Buy for Family (Airtel)
```bash
python buy_data.py 500 airtel 08012345678
```

### Weekend Data (2GB)
```bash
python buy_data.py 1000
```

## Files

- `buy_data.py` - Main script (dynamic, command-line args)
- `buy_data_as_real_user.py` - Original script (hardcoded values)
- `check_warpiiv_wallet.py` - MongoDB wallet checker
- `debug_wallet_and_networks.py` - API debugger

## Tips

1. **Save as alias** (Linux/Mac):
   ```bash
   alias buydata='python /path/to/buy_data.py'
   # Then just: buydata 500
   ```

2. **Windows shortcut**:
   Create `buydata.bat`:
   ```batch
   @echo off
   python C:\path\to\buy_data.py %*
   ```

3. **Check balance first**:
   ```bash
   python debug_wallet_and_networks.py
   ```

## Safety

- ✅ Uses official FiCore API
- ✅ Same flow as mobile app
- ✅ Secure authentication
- ✅ Transaction verification
- ✅ Balance checks before purchase

## Support

If you encounter issues:
1. Check your wallet balance
2. Verify network name is correct
3. Ensure amount matches available plans
4. Check internet connection

---

**Last Updated:** February 21, 2026  
**Status:** ✅ Production Ready  
**Tested:** Successfully purchased ₦200 MTN data
