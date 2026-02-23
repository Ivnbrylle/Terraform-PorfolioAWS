import json
import boto3
import uuid
import hashlib
from datetime import datetime, timedelta

# Initialize DynamoDB and SES resources
dynamodb = boto3.resource('dynamodb')
ses = boto3.client('ses', region_name='ap-southeast-1')
table = dynamodb.Table('PortfolioMessages')

SENDER_EMAIL = "rempisivan@gmail.com"
MAX_SUBMISSIONS_PER_IP = 10  # Max submissions per IP per hour
MAX_SUBMISSIONS_PER_EMAIL = 5  # Max submissions per email per hour

def get_source_ip(event):
    """Extract source IP from API Gateway event (HTTP API v2)"""
    # Try HTTP API v2 format first
    request_context = event.get('requestContext', {})
    http_info = request_context.get('http', {})
    ip = http_info.get('sourceIp')
    
    # Fallback: Try REST API format
    if not ip:
        identity = request_context.get('identity', {})
        ip = identity.get('sourceIp')
    
    # Fallback: Check headers for X-Forwarded-For
    if not ip:
        headers = event.get('headers', {})
        forwarded = headers.get('x-forwarded-for') or headers.get('X-Forwarded-For')
        if forwarded:
            ip = forwarded.split(',')[0].strip()
    
    return ip or 'unknown'

def lambda_handler(event, context):
    try:
        # 1. Parse the incoming data
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})

        name = body.get('name', '').strip()
        email = body.get('email', '').strip().lower()
        message = body.get('message', '').strip()
        source_ip = get_source_ip(event)

        # 2. Input validation
        if not name or not email or not message:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'status': 'error', 'message': 'Missing required fields'})
            }

        one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()

        # 3. Check IP-based rate limit (max 3 per hour)
        ip_response = table.query(
            IndexName='SourceIPIndex',
            KeyConditionExpression='SourceIP = :ip',
            FilterExpression='#ts > :time',
            ExpressionAttributeNames={'#ts': 'Timestamp'},
            ExpressionAttributeValues={
                ':ip': source_ip,
                ':time': one_hour_ago
            }
        )

        if len(ip_response.get('Items', [])) >= MAX_SUBMISSIONS_PER_IP:
            return {
                'statusCode': 429,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'status': 'error', 'message': 'Too many submissions. Please try again later.'})
            }

        # 4. Check email-based rate limit (max 2 per hour per email)
        email_count = sum(1 for item in ip_response.get('Items', []) if item.get('Email', '').lower() == email)
        if email_count >= MAX_SUBMISSIONS_PER_EMAIL:
            return {
                'statusCode': 429,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'status': 'error', 'message': 'Too many submissions from this email. Please try again later.'})
            }

        # 5. Check for duplicate content (same email+message within 5 minutes)
        content_hash = hashlib.md5(f"{email}{message.lower()}".encode()).hexdigest()
        five_mins_ago = (datetime.utcnow() - timedelta(minutes=5)).isoformat()

        dup_response = table.query(
            IndexName='ContentHashIndex',
            KeyConditionExpression='ContentHash = :hash',
            FilterExpression='#ts > :time',
            ExpressionAttributeNames={'#ts': 'Timestamp'},
            ExpressionAttributeValues={
                ':hash': content_hash,
                ':time': five_mins_ago
            }
        )

        if dup_response.get('Items'):
            return {
                'statusCode': 429,
                'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
                'body': json.dumps({'status': 'error', 'message': 'Duplicate submission detected. Please wait a few minutes.'})
            }

        # 6. Save the entry to DynamoDB
        table.put_item(Item={
            'MessageId': str(uuid.uuid4()),
            'Timestamp': datetime.utcnow().isoformat(),
            'Name': name,
            'Email': email,
            'Message': message,
            'ContentHash': content_hash,
            'SourceIP': source_ip
        })

        # 7. Send the Email Notification via SES (non-blocking - don't fail if quota exceeded)
        email_sent = True
        try:
            ses.send_email(
                Source=SENDER_EMAIL,
                Destination={'ToAddresses': [SENDER_EMAIL]},
                Message={
                    'Subject': {'Data': f'New Portfolio Contact: {name}'},
                    'Body': {
                        'Text': {
                            'Data': f"You have a new message from your portfolio:\n\n"
                                    f"Name: {name}\n"
                                    f"Email: {email}\n"
                                    f"Message: {message}"
                        }
                    }
                }
            )
        except Exception as email_error:
            print(f"Email failed (quota?): {str(email_error)}")
            email_sent = False

        # 8. Return success response (message saved even if email failed)
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type'
            },
            'body': json.dumps({'status': 'success', 'message': 'Message received!' if not email_sent else 'Message sent!'})}



    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({'status': 'error', 'message': 'Internal server error'})
        }