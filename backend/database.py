import os
import boto3
from boto3.dynamodb.conditions import Key
import time
import uuid

# Environment variables bound in CDK
CHAT_SESSIONS_TABLE = os.environ.get("CHAT_SESSIONS_TABLE", "ChatSessionsTable")
CHAT_MESSAGES_TABLE = os.environ.get("CHAT_MESSAGES_TABLE", "ChatMessagesTable")
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "DocumentsTable")

dynamodb = boto3.resource('dynamodb')

sessions_table = dynamodb.Table(CHAT_SESSIONS_TABLE)
messages_table = dynamodb.Table(CHAT_MESSAGES_TABLE)
docs_table = dynamodb.Table(DOCUMENTS_TABLE)

def create_chat_session(user_id: str, title: str = "New Chat"):
    session_id = str(uuid.uuid4())
    now = str(int(time.time() * 1000))
    sessions_table.put_item(
        Item={
            'user_id': user_id,
            'session_id': session_id,
            'title': title,
            'created_at': now,
            'last_active_at': now
        }
    )
    return {"session_id": session_id, "created_at": now}

def get_chat_sessions(user_id: str):
    response = sessions_table.query(
        IndexName="LastActiveIndex",
        KeyConditionExpression=Key('user_id').eq(user_id),
        ScanIndexForward=False # Newest first
    )
    return response.get('Items', [])

def get_chat_messages(session_id: str):
    response = messages_table.query(
        KeyConditionExpression=Key('session_id').eq(session_id)
    )
    return response.get('Items', [])

def add_chat_message(session_id: str, role: str, content: str, sources=None, model=None, latency_ms=None):
    now = str(int(time.time() * 1000))
    item = {
        'session_id': session_id,
        'ts': now,
        'role': role,
        'content': content
    }
    if sources:
        item['sources'] = sources
    if model:
        item['model'] = model
    if latency_ms:
        item['latency_ms'] = latency_ms

    messages_table.put_item(Item=item)
    return item

def update_session_last_active(user_id: str, session_id: str):
    now = str(int(time.time() * 1000))
    sessions_table.update_item(
        Key={'user_id': user_id, 'session_id': session_id},
        UpdateExpression="SET last_active_at = :now",
        ExpressionAttributeValues={':now': now}
    )

def get_documents_status():
    # Scan table to count READY vs PROCESSING vs FAILED
    # Note: Scan is not ideal for large tables, but okay for a prototype
    response = docs_table.scan(ProjectionExpression="#st", ExpressionAttributeNames={"#st": "status"})
    statuses = [item.get("status") for item in response.get("Items", [])]
    
    return {
        "total": len(statuses),
        "ready": statuses.count("READY"),
        "processing": statuses.count("PROCESSING"),
        "failed": statuses.count("FAILED")
    }
