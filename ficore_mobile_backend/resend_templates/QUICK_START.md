# Quick Start: Import FiCore Template to Resend

## Step 1: Copy the Template
Open `ficore_announcement_resend_ready.html` and copy ALL the code.

## Step 2: Create Template in Resend
1. Go to https://resend.com/templates
2. Click "+ Create template" button
3. Name it: **FiCore Announcement**
4. Paste the HTML code
5. Click "Publish"

## Step 3: Get Your Template ID
After publishing, Resend will give you a template ID like: `84213002-06c3-4529-b4a7-0f6d59756a91`

Copy this ID - you'll need it in your code.

## Step 4: Update Your Python Code

Replace the current `send_announcement` method in `announcement_service.py`:

```python
def send_announcement(self, subject, title, body, cta_text=None, cta_link=None, 
                     image_url=None, test_mode=False, test_email=None, 
                     announcement_type='general', admin_id=None):
    """
    Send announcement using Resend template
    """
    try:
        # Format body content to HTML
        body_html = self._format_body_to_html(body)
        
        # Prepare template data
        template_data = {
            "title": title,
            "body": body_html
        }
        
        # Add optional fields if provided
        if cta_text and cta_link:
            template_data["ctaText"] = cta_text
            template_data["ctaLink"] = cta_link
        
        if image_url:
            template_data["imageUrl"] = image_url
        
        if test_mode:
            # Test mode: Send to single email
            if not test_email:
                return {
                    'success': False,
                    'message': 'Test email required for test mode',
                    'error': 'Missing test_email'
                }
            
            params = {
                "from": self.from_email,
                "to": [test_email],
                "subject": f"[TEST] {subject}",
                "template_id": "YOUR_TEMPLATE_ID_HERE",  # Replace with your template ID
                "template_data": template_data
            }
            
            response = resend.Emails.send(params)
            
            self._log_announcement(
                subject=subject,
                announcement_type=announcement_type,
                status='test',
                recipient_count=1,
                admin_id=admin_id
            )
            
            return {
                'success': True,
                'message': f'Test announcement sent to {test_email}',
                'broadcast_id': response.get('id'),
                'error': None
            }
        
        else:
            # Live mode: Send to all users
            if self.mongo_db is None:
                return {
                    'success': False,
                    'message': 'Database connection required',
                    'error': 'No MongoDB connection'
                }
            
            # Get all users
            users = list(self.mongo_db.users.find(
                {'resendContactId': {'$exists': True}},
                {'email': 1, '_id': 0}
            ))
            
            if not users:
                return {
                    'success': False,
                    'message': 'No users found',
                    'error': 'Empty audience'
                }
            
            recipient_emails = [user['email'] for user in users]
            
            # Send in batches
            batch_size = 50
            total_sent = 0
            
            for i in range(0, len(recipient_emails), batch_size):
                batch = recipient_emails[i:i + batch_size]
                
                params = {
                    "from": self.from_email,
                    "to": batch,
                    "subject": subject,
                    "template_id": "YOUR_TEMPLATE_ID_HERE",  # Replace with your template ID
                    "template_data": template_data
                }
                
                response = resend.Emails.send(params)
                total_sent += len(batch)
                
                print(f'✅ Sent to {len(batch)} users')
            
            self._log_announcement(
                subject=subject,
                announcement_type=announcement_type,
                status='sent',
                recipient_count=total_sent,
                admin_id=admin_id
            )
            
            return {
                'success': True,
                'message': f'Announcement sent to {total_sent} users',
                'recipient_count': total_sent,
                'error': None
            }
    
    except Exception as e:
        print(f'❌ Announcement failed: {e}')
        return {
            'success': False,
            'message': 'Failed to send announcement',
            'error': str(e)
        }

def _format_body_to_html(self, body):
    """
    Convert plain text body to HTML with paragraphs
    """
    # Normalize line endings
    body_html = body.replace('\r\n', '\n')
    
    # Split into paragraphs
    paragraphs = body_html.split('\n\n')
    
    # Format each paragraph
    formatted_paragraphs = []
    for para in paragraphs:
        if para.strip():
            # Replace single line breaks with <br>
            para_with_breaks = para.replace('\n', '<br>')
            # Wrap in paragraph tag
            formatted_paragraphs.append(f'<p style="margin: 0 0 15px 0;">{para_with_breaks}</p>')
    
    return '\n'.join(formatted_paragraphs)
```

## Step 5: Test It!
1. Go to your admin panel
2. Create a test announcement
3. Enable "Test Mode"
4. Enter your email
5. Click "Send Test"
6. Check your inbox!

## Benefits of Using Resend Templates

✅ **Consistent Branding:** Same look across all emails
✅ **Easy Updates:** Change template once, affects all future emails
✅ **Better Deliverability:** Resend optimizes template rendering
✅ **Mobile Responsive:** Works perfectly on all devices
✅ **Version Control:** Track template changes over time

## Need Help?

Check `RESEND_TEMPLATE_INSTRUCTIONS.md` for detailed documentation.
