# Uploads Directory

This directory stores user-uploaded files for the FiCore Mobile Backend.

## Structure

```
uploads/
├── receipts/          # Payment receipts for credit requests
└── README.md          # This file
```

## Security Notes

- All uploaded files are validated for type and size
- Allowed file types: PNG, JPG, JPEG, PDF, GIF
- Maximum file size: 5MB
- Files are named with user ID and unique identifier
- Files are served through authenticated endpoints

## File Naming Convention

Format: `{userId}_{uniqueId}.{extension}`

Example: `507f1f77bcf86cd799439011_a3b2c1d4.jpg`

## Cleanup

Consider implementing a cleanup job to remove:
- Orphaned files (no associated credit request)
- Files from rejected/expired requests after 90 days
- Files older than 1 year

## Backup

Ensure this directory is included in your backup strategy, as it contains important proof of payment documents.
