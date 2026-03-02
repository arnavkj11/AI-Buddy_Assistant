import os
import json
import uuid
import time
import boto3
from urllib.parse import unquote_plus
from pypdf import PdfReader
from io import BytesIO
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

# Env vars
OS_ENDPOINT = os.environ.get("OS_ENDPOINT", "")
if OS_ENDPOINT and not OS_ENDPOINT.startswith("https://"):
    OS_ENDPOINT = f"https://{OS_ENDPOINT}"
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "DocumentsTable")
PROCESSED_BUCKET = os.environ.get("PROCESSED_BUCKET", "DocsProcessedBucket")

# Clients
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
docs_table = dynamodb.Table(DOCUMENTS_TABLE)
bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))

credentials = boto3.Session().get_credentials()
auth = AWSV4SignerAuth(credentials, os.environ.get("AWS_REGION", "us-east-1"), 'es')

if OS_ENDPOINT:
    os_client = OpenSearch(
        hosts=[OS_ENDPOINT],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection
    )
else:
    os_client = None

INDEX_NAME = "onboarding_chunks"
EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"

def get_embedding(text: str) -> list[float]:
    response = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": text})
    )
    result = json.loads(response['body'].read().decode())
    return result.get('embedding')

def process_extract(input_data):
    bucket = input_data.get('bucket')
    key = unquote_plus(input_data.get('key'))  # Decode URL-encoded key
    doc_id = str(uuid.uuid4())
    now = str(int(time.time() * 1000))
    
    # 1. Update status
    docs_table.put_item(
        Item={
            'doc_id': doc_id,
            'filename': key,
            's3_key': key,
            'status': 'PROCESSING',
            'created_at': now,
            'updated_at': now
        }
    )
    
    # 2. Extract Text
    text_content = ""
    try:
        print(f"Attempting to fetch from S3: bucket={bucket}, key={key}")
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        if key.lower().endswith('.pdf'):
            reader = PdfReader(BytesIO(obj['Body'].read()))
            for page in reader.pages:
                text_content += page.extract_text() + "\n"
        else:
            # Assume text/plain
            text_content = obj['Body'].read().decode('utf-8')
    except Exception as e:
        docs_table.update_item(
            Key={'doc_id': doc_id},
            UpdateExpression="SET #st = :st, error_message = :err, updated_at = :now",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":st": "FAILED", ":err": str(e), ":now": now}
        )
        raise e
        
    # 3. Save extracted text to processed bucket
    text_key = f"extracted/{doc_id}.txt"
    s3_client.put_object(
        Bucket=PROCESSED_BUCKET,
        Key=text_key,
        Body=text_content.encode('utf-8')
    )
    
    return {
        "doc_id": doc_id,
        "text_key": text_key,
        "doc_title": key.split('/')[-1]
    }

def process_chunk_embed_index(input_data):
    # input_data will contain the original state, including extractResult
    extract_payload = input_data.get('extractResult', {}).get('Payload', {})
    doc_id = extract_payload.get('doc_id')
    text_key = extract_payload.get('text_key')
    doc_title = extract_payload.get('doc_title', 'Unknown Document')
    
    if not doc_id or not text_key:
        raise ValueError("Missing doc_id or text_key from extract step")
        
    now = str(int(time.time() * 1000))
        
    try:
        # 1. Read text
        obj = s3_client.get_object(Bucket=PROCESSED_BUCKET, Key=text_key)
        text_content = obj['Body'].read().decode('utf-8')
        
        # 2. Chunking (Simple character + overlap strategy)
        CHUNK_SIZE = 800
        OVERLAP = 150
        chunks = []
        i = 0
        while i < len(text_content):
            chunks.append(text_content[i:i+CHUNK_SIZE])
            i += CHUNK_SIZE - OVERLAP
            
        # 3. Create Index if not exists
        if not os_client.indices.exists(index=INDEX_NAME):
            mapping = {
                "mappings": {
                    "properties": {
                        "chunk_id": {"type": "keyword"},
                        "doc_id": {"type": "keyword"},
                        "doc_title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                        "page_or_section": {"type": "keyword"},
                        "chunk_text": {"type": "text"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": 1024, # Dimension for amazon.titan-embed-text-v2:0 (defaults varies, standard is 1024)
                            "method": {
                                "name": "hnsw",
                                "engine": "nmslib",
                                "space_type": "l2"
                            }
                        },
                        "updated_at": {"type": "date"}
                    }
                },
                "settings": {
                    "index": {
                        "knn": True
                    }
                }
            }
            os_client.indices.create(index=INDEX_NAME, body=mapping)
            
        # 4. Embed & Index
        indexed_count = 0
        for idx, chunk_str in enumerate(chunks):
            if not chunk_str.strip():
                continue
            embedding = get_embedding(chunk_str)
            chunk_id = f"{doc_id}_{idx}"
            
            doc = {
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "doc_title": doc_title,
                "page_or_section": f"Chunk {idx+1}",
                "chunk_text": chunk_str,
                "embedding": embedding,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            
            os_client.index(index=INDEX_NAME, id=chunk_id, body=doc)
            indexed_count += 1
            
        # 5. Update status
        docs_table.update_item(
            Key={'doc_id': doc_id},
            UpdateExpression="SET #st = :st, updated_at = :now",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":st": "READY", ":now": now}
        )
        
        return {"status": "SUCCESS", "doc_id": doc_id, "chunks_indexed": indexed_count}
        
    except Exception as e:
        docs_table.update_item(
            Key={'doc_id': doc_id},
            UpdateExpression="SET #st = :st, error_message = :err, updated_at = :now",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":st": "FAILED", ":err": str(e), ":now": now}
        )
        raise e

def handler(event, context):
    print("Ingestion worker started", json.dumps(event))
    step = event.get('step')
    input_data = event.get('input', "{}")
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except Exception as e:
            print(f"Failed to parse input_data: {e}")
            pass

    print(f"Processing step: {step}, input_data: {json.dumps(input_data)}")

    if step == "extract":
        return process_extract(input_data)
    elif step == "chunk_embed_index":
        return process_chunk_embed_index(input_data)
    else:
        return {"error": "Unknown step"}
