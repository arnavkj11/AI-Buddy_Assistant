import os
import json
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

OS_ENDPOINT = os.environ.get("OS_ENDPOINT", "")
if not OS_ENDPOINT.startswith("https://"):
    OS_ENDPOINT = f"https://{OS_ENDPOINT}"

bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
credentials = boto3.Session().get_credentials()
auth = AWSV4SignerAuth(credentials, os.environ.get("AWS_REGION", "us-east-1"), 'es')

os_client = OpenSearch(
    hosts=[OS_ENDPOINT],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

INDEX_NAME = "onboarding_chunks"
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
CHAT_MODEL = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

def get_embedding(text: str) -> list[float]:
    response = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": text})
    )
    result = json.loads(response['body'].read().decode())
    return result.get('embedding')

def retrieve_chunks(query: str, embedding: list[float], top_k: int = 10):
    if not os_client.indices.exists(index=INDEX_NAME):
        return []

    # Hybrid search: KNN + BM25
    query_body = {
        "size": top_k,
        "query": {
            "hybrid": {
                "queries": [
                    {
                        "match": {
                            "chunk_text": query
                        }
                    },
                    {
                        "knn": {
                            "embedding": {
                                "vector": embedding,
                                "k": top_k
                            }
                        }
                    }
                ]
            }
        }
    }

    try:
        res = os_client.search(index=INDEX_NAME, body=query_body)
        hits = res['hits']['hits']
        
        chunks = []
        for hit in hits:
            source = hit['_source']
            chunks.append({
                "chunk_id": source.get("chunk_id"),
                "doc_title": source.get("doc_title"),
                "page_or_section": source.get("page_or_section", "N/A"),
                "chunk_text": source.get("chunk_text")
            })
        return chunks
    except Exception as e:
        print(f"OpenSearch error: {e}")
        return []

def generate_answer(query: str, chunks: list[dict], chat_history: list[dict]):
    if not chunks:
        return "I don't know the answer to that as there isn't sufficient context in the uploaded documents. Please try asking your manager or HR team.", []

    context_str = "\n\n".join([f"[{c['doc_title']} - {c['page_or_section']}] {c['chunk_text']}" for c in chunks])
    
    system_prompt = f"""You are AI Buddy, a knowledgeable and friendly onboarding assistant for new employees.
Your role is to help new hires quickly get up to speed on company policies, processes, tools, and procedures.

## Instructions
- Answer questions based ONLY on the provided document excerpts below. Do not use outside knowledge.
- Be clear, structured, and practical. Use bullet points or numbered steps when explaining processes.
- If the question has multiple parts, address each part separately.
- Always cite the source document name at the end of your answer.
- If the provided excerpts do not contain enough information to answer fully, say exactly:
  "I don't have enough information in the available documents to fully answer this. I'd recommend checking with HR or your manager for more details."
- Never guess, assume, or make up policies, names, or procedures.
- Keep a warm, professional, and encouraging tone — the user is new and may feel overwhelmed.

## Context Documents
{context_str}"""

    # Format history for Claude
    messages = []
    # Claude Message structure expects role and content
    for msg in chat_history[-10:]: # last 10 messages
        role = "user" if msg.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": msg.get("content")})
        
    messages.append({"role": "user", "content": query})

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": messages,
        "temperature": 0.1
    }

    try:
        response = bedrock.invoke_model(
            modelId=CHAT_MODEL,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body)
        )
        result = json.loads(response['body'].read().decode())
        answer = result.get('content', [{}])[0].get('text', 'Error generating text.')
        
        # Only include sources that Claude actually cited in the answer
        seen = set()
        sources = []
        for c in chunks:
            if c["doc_title"] not in seen and c["doc_title"] in answer:
                seen.add(c["doc_title"])
                sources.append({"doc_title": c["doc_title"], "page_or_section": c["page_or_section"], "chunk_id": c["chunk_id"]})
        # Fallback: if Claude cited nothing (unlikely), return all unique docs
        if not sources:
            for c in chunks:
                if c["doc_title"] not in seen:
                    seen.add(c["doc_title"])
                    sources.append({"doc_title": c["doc_title"], "page_or_section": c["page_or_section"], "chunk_id": c["chunk_id"]})
        return answer, sources
    except Exception as e:
        import traceback
        print(f"Bedrock error [{type(e).__name__}]: {e}")
        print(traceback.format_exc())
        return f"Sorry, I encountered an error: {type(e).__name__}: {str(e)}", []
