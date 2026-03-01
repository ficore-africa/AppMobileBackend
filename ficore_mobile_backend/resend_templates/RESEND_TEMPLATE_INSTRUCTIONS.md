# FiCore Announcement Template for Resend

## How to Import This Template to Resend

### Step 1: Copy the HTML Template
Copy the entire content from `ficore_announcement_resend_ready.html` (see below)

### Step 2: Create Template in Resend
1. Go to https://resend.com/templates
2. Click "Create template"
3. Give it a name: "FiCore Announcement"
4. Paste the HTML code
5. Click "Publish"

### Step 3: Use Variables in Your Code
When sending emails via the template, use these variables:

```python
# In your Python code
resend.Emails.send({
    "from": "FiCore Africa <team@ficoreafrica.com>",
    "to": ["user@example.com"],
    "subject": "Your announcement subject",
    "template_id": "your-template-id-here",
    "template_data": {
        "title": "The NEW FiCore is here!",
        "body": "<p>Your announcement body with HTML formatting</p>",
        "imageUrl": "https://example.com/image.jpg",  # Optional
        "ctaText": "Get the FiCore App",  # Optional
        "ctaLink": "https://play.google.com/...",  # Optional
        "unsubscribe_url": "{{unsubscribe_url}}"  # Resend handles this automatically
    }
})
```

## Template Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `title` | Yes | Announcement headline | "The NEW FiCore is here!" |
| `body` | Yes | Main message (HTML formatted) | `<p>We've rebuilt FiCore...</p>` |
| `imageUrl` | No | Hero image URL | "https://cdn.ficore.com/hero.jpg" |
| `ctaText` | No | Call-to-action button text | "Download Now" |
| `ctaLink` | No | Call-to-action button URL | "https://play.google.com/..." |
| `unsubscribe_url` | Auto | Resend provides this automatically | N/A |

## Formatting Your Body Content

Since Resend templates use HTML, you need to format your body content with HTML tags:

### Paragraphs
```html
<p style="margin: 0 0 15px 0;">This is a paragraph.</p>
<p style="margin: 0 0 15px 0;">This is another paragraph.</p>
```

### Line Breaks
```html
<p style="margin: 0 0 15px 0;">
    Line 1<br>
    Line 2<br>
    Line 3
</p>
```

### Bold Text
```html
<p style="margin: 0 0 15px 0;"><strong>This is bold</strong></p>
```

### Lists
```html
<ul style="margin: 0 0 15px 0; padding-left: 20px;">
    <li>Item 1</li>
    <li>Item 2</li>
    <li>Item 3</li>
</ul>
```

### Emojis
```html
<p style="margin: 0 0 15px 0;">⚡ Super Light: Just 12MB</p>
<p style="margin: 0 0 15px 0;">🎙️ Voice Entry: Speak your transactions</p>
```

## Example: Your Early Access Announcement

```python
body_html = """
<p style="margin: 0 0 15px 0;">Hi FiCoreFam!</p>

<p style="margin: 0 0 15px 0;">We know the previous app was a bit heavy, and your feedback meant the world to us. We've been working hard in the lab to rebuild FiCore from the ground up just for you.</p>

<p style="margin: 0 0 15px 0;">As one of our valued existing users, we are excited to invite you to our Early Access list. You get to experience the new and improved FiCore before the official public launch!</p>

<p style="margin: 0 0 15px 0;"><strong>What's new?</strong></p>

<p style="margin: 0 0 15px 0;">
⚡ <strong>Super Light:</strong> No more 90MB downloads. The new app is just 12MB and lightning-fast.<br>
🎙️ <strong>Speak Your Income:</strong> Record transactions hands-free. Whether it's English, Hausa, or Pidgin, FiCore understands your business.<br>
💸 <strong>Wallet & Bills:</strong> Buy airtime and data directly. FiCore handles the bookkeeping for you automatically.
</p>

<p style="margin: 0 0 15px 0;"><strong>⚠️ How to Upgrade (Action Required)</strong></p>

<p style="margin: 0 0 15px 0;">To ensure a smooth transition, please follow these exact steps:</p>

<ol style="margin: 0 0 15px 0; padding-left: 20px;">
    <li style="margin-bottom: 10px;"><strong>Uninstall</strong> the old FiCore app from your phone completely.</li>
    <li style="margin-bottom: 10px;"><strong>Switch Google Play Account:</strong> Open your Google Play Store app, tap your profile icon at the top right, and make sure you are switched to the same email address where you received this message.</li>
    <li style="margin-bottom: 10px;"><strong>Accept the Invite:</strong> Click the link below to join the internal testing group.</li>
    <li style="margin-bottom: 10px;"><strong>Download:</strong> Once you click "Accept Invite," you will be redirected to download the new 12MB app.</li>
</ol>

<p style="margin: 0 0 15px 0;"><em>Please note: This early access is intended for existing FiCore Africa users only. If you haven't signed up yet, kindly wait for our official public launch coming very soon!</em></p>

<p style="margin: 0 0 15px 0;">Here is our Whatsapp group:<br>
<a href="https://chat.whatsapp.com/CxD8u1BkEfqHONfZHCAaKe" style="color: #25D366; text-decoration: none; font-weight: 600;">https://chat.whatsapp.com/CxD8u1BkEfqHONfZHCAaKe</a></p>

<p style="margin: 0 0 15px 0;">Thank you for helping us build the future of business bookkeeping.</p>
"""

# Send via Resend
resend.Emails.send({
    "from": "FiCore Africa <team@ficoreafrica.com>",
    "to": ["user@example.com"],
    "subject": "🎙️ You asked, we listened: The NEW FiCore is here! (Early Access)",
    "template_id": "your-template-id",
    "template_data": {
        "title": "The NEW FiCore is here! (Early Access)",
        "body": body_html,
        "ctaText": "Get the FiCore App",
        "ctaLink": "https://play.google.com/store/apps/details?id=com.ficoreafrica.app"
    }
})
```

## Benefits of Using Resend Templates

1. **Reusability:** Create once, use for all announcements
2. **Consistency:** Same branding across all emails
3. **Easy Updates:** Change template once, affects all future emails
4. **Version Control:** Resend tracks template versions
5. **Preview:** Test templates before sending
6. **Analytics:** Track opens, clicks, bounces

## Alternative: Keep Using Python Template

If you prefer to keep using the Python template (current approach), you can:

1. Keep the current `announcement_service.py` implementation
2. The paragraph formatting fix we just applied will work
3. No need to migrate to Resend templates

The choice is yours! Both approaches work well.
