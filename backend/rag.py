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
CHAT_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"

def get_embedding(text: str) -> list[float]:
    response = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": text})
    )
    result = json.loads(response['body'].read().decode())
    return result.get('embedding')

def retrieve_chunks(query: str, embedding: list[float], top_k: int = 8):
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
    
    system_prompt = f"""You are the AI Buddy Assistant for new employee onboarding. 
Answer the user's questions based ONLY on the provided document excerpts.
If the excerpts don't contain enough information to answer the question, firmly reply "I don't know the answer based on the provided documents. You may want to check with HR or your manager." Do not hallucinate or make up answers.
Always cite your sources clearly using the document title if you produce an answer based on them.

<context>
{context_str}
</context>"""

    # Format history for Claude
    messages = []
    # Claude Message structure expects role and content
    for msg in chat_history[-10:]: # last 10 messages
        role = "user" if msg.get("role") == "user" else "assistant"
        messages.append({"role": role, "content": msg.get("content")})
        
    messages.append({"role": "user", "content": query})

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
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
        
        sources = [{"doc_title": c["doc_title"], "page_or_section": c["page_or_section"], "chunk_id": c["chunk_id"]} for c in chunks]
        return answer, sources
    except Exception as e:
        print(f"Bedrock error: {e}")
        return "Sorry, I encountered an error while communicating with the AI model.", []
