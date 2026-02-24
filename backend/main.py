import os
import time
import boto3
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from auth import get_current_user
import database as db
from models import ChatMessageReq, ChatMessageResp, ChatSessionCreateResp, Source
import rag

app = FastAPI(title="AI Buddy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/v1/docs/status")
def doc_status(user=Depends(get_current_user)):
    return db.get_documents_status()

@app.get("/v1/docs/url")
def get_doc_url(doc_title: str, user=Depends(get_current_user)):
    raw_bucket = os.environ.get("RAW_BUCKET", "")
    if not raw_bucket:
        raise HTTPException(status_code=500, detail="Storage not configured")
    doc = db.get_document_by_title(doc_title)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    s3 = boto3.client("s3")
    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': raw_bucket, 'Key': doc['s3_key']},
        ExpiresIn=300
    )
    return {"url": url}

@app.post("/v1/chats", response_model=ChatSessionCreateResp)
def create_chat(user=Depends(get_current_user)):
    user_id = user.get("sub")
    session = db.create_chat_session(user_id=user_id)
    return session

@app.get("/v1/chats")
def list_chats(user=Depends(get_current_user)):
    user_id = user.get("sub")
    sessions = db.get_chat_sessions(user_id=user_id)
    return sessions

@app.delete("/v1/chats/{session_id}", status_code=204)
def delete_chat(session_id: str, user=Depends(get_current_user)):
    user_id = user.get("sub")
    sessions = db.get_chat_sessions(user_id)
    if not any(s.get("session_id") == session_id for s in sessions):
        raise HTTPException(status_code=403, detail="Unauthorized access to chat session")
    db.delete_chat_session(user_id, session_id)

@app.get("/v1/chats/{session_id}/messages")
def get_messages(session_id: str, user=Depends(get_current_user)):
    user_id = user.get("sub")
    
    # Optional: Verify session belongs to user
    sessions = db.get_chat_sessions(user_id)
    if not any(s.get("session_id") == session_id for s in sessions):
        raise HTTPException(status_code=403, detail="Unauthorized access to chat session")

    messages = db.get_chat_messages(session_id)
    # Sort messages by timestamp
    messages.sort(key=lambda x: str(x.get('ts')))
    return messages

@app.post("/v1/chats/{session_id}/messages", response_model=ChatMessageResp)
def send_message(session_id: str, req: ChatMessageReq, user=Depends(get_current_user)):
    user_id = user.get("sub")
    
    # 1. Verify session
    sessions = db.get_chat_sessions(user_id)
    session = next((s for s in sessions if s.get("session_id") == session_id), None)
    if not session:
        raise HTTPException(status_code=403, detail="Unauthorized access to chat session")

    # 2. Get history
    history = db.get_chat_messages(session_id)
    history.sort(key=lambda x: str(x.get('ts')))
    
    # 3. Save user message
    db.add_chat_message(session_id, role="user", content=req.message)
    start_time = time.time()

    # 4. RAG Pipeline
    try:
        embedding = rag.get_embedding(req.message)
        chunks = rag.retrieve_chunks(req.message, embedding=embedding)
        answer, sources = rag.generate_answer(req.message, chunks=chunks, chat_history=history)
        
        # Determine if we got an answer or "I don't know"
        if "I don't know" in answer:
            sources = [] # Remove sources if the model couldn't find answer
            
    except Exception as e:
        print(f"RAG Error: {e}")
        answer = "I'm sorry, an error occurred while generating a response."
        sources = []

    latency = int((time.time() - start_time) * 1000)

    # 5. Save assistant message
    db.add_chat_message(
        session_id, 
        role="assistant", 
        content=answer, 
        sources=sources,
        model=rag.CHAT_MODEL,
        latency_ms=latency
    )

    db.update_session_last_active(user_id, session_id)

    # If this is the first interaction, we might want to update the chat session title
    if len(history) == 0:
        # A simple mechanism: Title is first 30 chars of prompt
        title = (req.message[:27] + '...') if len(req.message) > 30 else req.message
        db.sessions_table.update_item(
            Key={'user_id': user_id, 'session_id': session_id},
            UpdateExpression="SET title = :title",
            ExpressionAttributeValues={':title': title}
        )

    response_sources = [Source(**s) for s in sources]
    return ChatMessageResp(answer=answer, sources=response_sources, session_id=session_id)

handler = Mangum(app)
