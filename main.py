import os
import re
import json
import time
import logging
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('waitlist-bot')

# Initialize Flask app
app = Flask(__name__)

# In-memory queue for pending emails
EMAIL_QUEUE = []

# HTML email template - Customize this!
EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Welcome to Our Waitlist</title>
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333333;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #ffffff;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .header {
            text-align: center;
            padding: 20px 0;
        }
        .logo {
            max-width: 150px;
            height: auto;
        }
        h1 {
            color: #4a90e2;
            font-size: 24px;
            margin-bottom: 20px;
        }
        p {
            margin-bottom: 16px;
        }
        ul {
            padding-left: 20px;
            margin-bottom: 20px;
        }
        li {
            margin-bottom: 10px;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eeeeee;
            font-size: 12px;
            color: #888888;
            text-align: center;
        }
        .social {
            margin-top: 15px;
        }
        .social a {
            display: inline-block;
            margin: 0 8px;
            color: #4a90e2;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <!-- Replace with your logo URL -->
            <!-- <img src="https://yourcompany.com/logo.png" alt="Company Logo" class="logo"> -->
            <h1>Welcome to Our Waitlist!</h1>
        </div>
        
        <p>Hi {name},</p>
        
        <p>Thank you for joining our waitlist! We're excited to have you on board and can't wait to share our product with you.</p>
        
        <p>Here's what you can expect while on our waitlist:</p>
        
        <ul>
            <li><strong>Regular Updates:</strong> We'll keep you informed about our progress and launch timeline.</li>
            <li><strong>Early Access:</strong> As a waitlist member, you'll be among the first to access our platform.</li>
            <li><strong>Exclusive Offers:</strong> Special promotions available only to our early supporters.</li>
        </ul>
        
        <p>We're working hard to create something amazing, and your interest means a lot to us.</p>
        
        <p>If you have any questions or feedback, feel free to reply to this email directly.</p>
        
        <p>Best regards,<br>The Team</p>
        
        <div class="footer">
            <p>© 2025 Your Company. All rights reserved.</p>
            <p>123 Startup Street, San Francisco, CA 94107</p>
            
            <div class="social">
                <a href="https://twitter.com/yourcompany">Twitter</a> |
                <a href="https://facebook.com/yourcompany">Facebook</a> |
                <a href="https://instagram.com/yourcompany">Instagram</a>
            </div>
        </div>
    </div>
</body>
</html>
"""

# Extract configuration from environment variables
SLACK_VERIFICATION_TOKEN = os.environ.get('SLACK_VERIFICATION_TOKEN', '')
EMAIL_USER = os.environ.get('EMAIL_USER', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_SERVER = os.environ.get('EMAIL_SERVER', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_FROM_NAME = os.environ.get('EMAIL_FROM_NAME', 'Your Company')
WAITLIST_KEYWORD = os.environ.get('WAITLIST_KEYWORD', 'new waitlist signup')
QUEUE_FILE = os.environ.get('QUEUE_FILE', 'email_queue.json')
PORT = int(os.environ.get('PORT', 8080))

def extract_user_info(message_text):
    """Extract email and name from Slack message text"""
    # You can adjust these regex patterns to match your Slack message format
    email_pattern = r'[\w.-]+@[\w.-]+\.\w+'
    name_pattern = r'Name: ([^\n]+)'
    
    email_match = re.search(email_pattern, message_text)
    name_match = re.search(name_pattern, message_text)
    
    if email_match and name_match:
        return {
            'email': email_match.group(0),
            'name': name_match.group(1)
        }
    return None

def send_email(to_email, name):
    """Send welcome email to the user"""
    try:
        # Create email
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Welcome to Our Waitlist!'
        msg['From'] = f"{EMAIL_FROM_NAME} <{EMAIL_USER}>"
        msg['To'] = to_email
        
        # Fill template
        html_content = EMAIL_TEMPLATE.format(name=name)
        msg.attach(MIMEText(html_content, 'html'))
        
        # Send email
        with smtplib.SMTP(EMAIL_SERVER, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
            
        logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Error sending email to {to_email}: {e}")
        return False

def save_queue():
    """Save the email queue to a file"""
    try:
        queue_data = []
        for item in EMAIL_QUEUE:
            # Convert datetime to string for JSON serialization
            queue_item = item.copy()
            queue_item['scheduled_time'] = queue_item['scheduled_time'].isoformat()
            queue_data.append(queue_item)
            
        with open(QUEUE_FILE, 'w') as f:
            json.dump(queue_data, f)
        logger.debug(f"Queue saved with {len(queue_data)} items")
    except Exception as e:
        logger.error(f"Error saving queue: {e}")

def load_queue():
    """Load the email queue from a file"""
    global EMAIL_QUEUE
    try:
        if os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, 'r') as f:
                queue_data = json.load(f)
                
            # Convert string timestamps back to datetime objects
            EMAIL_QUEUE = []
            for item in queue_data:
                item['scheduled_time'] = datetime.fromisoformat(item['scheduled_time'])
                EMAIL_QUEUE.append(item)
                
            logger.info(f"Loaded {len(EMAIL_QUEUE)} items from queue file")
    except Exception as e:
        logger.error(f"Error loading queue: {e}")
        EMAIL_QUEUE = []

def email_processor_thread():
    """Background thread that processes the email queue"""
    logger.info("Email processor thread started")
    while True:
        try:
            current_time = datetime.now()
            
            # Check for emails that need to be sent
            emails_to_remove = []
            
            for i, item in enumerate(EMAIL_QUEUE):
                if current_time >= item['scheduled_time']:
                    # Time to send this email
                    logger.info(f"Sending scheduled email to {item['email']}")
                    success = send_email(item['email'], item['name'])
                    if success:
                        emails_to_remove.append(i)
                    else:
                        # If failed, retry after 5 minutes
                        item['scheduled_time'] = current_time + timedelta(minutes=5)
                        logger.info(f"Email sending failed, rescheduled for {item['scheduled_time']}")
            
            # Remove sent emails (in reverse order to not mess up indices)
            if emails_to_remove:
                for i in sorted(emails_to_remove, reverse=True):
                    del EMAIL_QUEUE[i]
                # Save the updated queue
                save_queue()
                
            # Sleep for 30 seconds before checking again
            time.sleep(30)
        except Exception as e:
            logger.error(f"Error in email processor: {e}")
            # Sleep for a bit to avoid tight loop in case of repeated errors
            time.sleep(10)

@app.route('/slack/events', methods=['POST'])
def slack_events():
    """Handle incoming Slack events webhook"""
    try:
        data = request.json
        logger.debug(f"Received Slack event: {data.get('type', 'unknown')}")
        
        # Handle URL verification challenge
        if data.get('type') == 'url_verification':
            logger.info("Responding to Slack URL verification challenge")
            return jsonify({'challenge': data.get('challenge')})
        
        # Verify the request is from Slack
        token = data.get('token')
        if not token or token != SLACK_VERIFICATION_TOKEN:
            logger.warning(f"Invalid Slack verification token: {token}")
            return jsonify({'error': 'Invalid token'}), 401
        
        # Check if this is a message event
        if data.get('type') == 'event_callback':
            event = data.get('event', {})
            
            # Only process new messages, not edits or deletes
            if event.get('type') == 'message' and not event.get('subtype'):
                message_text = event.get('text', '')
                
                # Check if this is a waitlist signup message
                if WAITLIST_KEYWORD.lower() in message_text.lower():
                    logger.info(f"Received waitlist signup message")
                    
                    # Extract user info
                    user_info = extract_user_info(message_text)
                    
                    if user_info:
                        # Schedule email for 10 minutes later
                        scheduled_time = datetime.now() + timedelta(minutes=10)
                        
                        EMAIL_QUEUE.append({
                            'email': user_info['email'],
                            'name': user_info['name'],
                            'scheduled_time': scheduled_time,
                            'message': message_text
                        })
                        
                        logger.info(f"Scheduled email for {user_info['email']} at {scheduled_time}")
                        
                        # Save queue to file as backup
                        save_queue()
                    else:
                        logger.warning(f"Could not extract email/name from message: {message_text}")
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Error processing Slack event: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/', methods=['GET'])
def home():
    """Simple health check endpoint"""
    queue_length = len(EMAIL_QUEUE)
    next_email = None
    if queue_length > 0:
        # Find the next email to be sent
        next_time = min(item['scheduled_time'] for item in EMAIL_QUEUE)
        next_email = next_time.strftime('%Y-%m-%d %H:%M:%S')
    
    return f"""
    <html>
    <head>
        <title>Waitlist Email Bot</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
            h1 {{ color: #4a90e2; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .stats {{ background-color: #f5f5f5; padding: 20px; border-radius: 5px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Waitlist Email Bot</h1>
            <p>Status: Running</p>
            
            <div class="stats">
                <h2>Current Stats:</h2>
                <p>Emails in queue: {queue_length}</p>
                {f"<p>Next email scheduled for: {next_email}</p>" if next_email else ""}
            </div>
        </div>
    </body>
    </html>
    """

@app.route('/ping', methods=['GET'])
def ping():
    """Simple endpoint for uptime monitoring services"""
    return "pong"

def start_app():
    """Start the Flask app with the email processor thread"""
    # Load any saved emails from previous run
    load_queue()
    
    # Start the email processor thread
    processor_thread = threading.Thread(target=email_processor_thread, daemon=True)
    processor_thread.start()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    start_app()

