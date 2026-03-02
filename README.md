# AI Buddy Assistant

An end-to-end RAG-powered chatbot prototype for employee onboarding, built on AWS serverless infrastructure. New hires can register, log in, and ask questions about company policies and procedures. Answers are grounded in uploaded company documents, with sources linked directly to the original files.

## Architecture Overview

```
User → CloudFront → React Frontend
         │
         ▼
  API Gateway → Lambda (FastAPI)
         │              │
         │         ┌────┴─────┐
         │         ▼          ▼
         │     OpenSearch   DynamoDB
         │     (RAG index)  (sessions/messages)
         │         │
         │         ▼
         │    Bedrock (Titan Embeddings + Claude)
         │
PDF Upload → S3 (Raw Bucket)
               │
               ▼
         Step Functions
         (Extract → Chunk → Embed → Index)
```

### Data Flows

**Document Ingestion** (event-driven):
PDF uploaded to S3 → Step Functions state machine → extract text → chunk → embed via Bedrock Titan → index in OpenSearch → status tracked in DynamoDB

**RAG Chat** (request-driven):
User message → API Gateway → Lambda → embed query → hybrid search (KNN + BM25) in OpenSearch → retrieved chunks + history → Claude generates grounded answer → response with sources saved to DynamoDB

## Directory Structure

```
/
├── frontend/     # React + Vite + TypeScript (AWS Amplify Auth)
├── backend/      # FastAPI + Mangum (deployed on AWS Lambda)
│   ├── main.py       # API routes
│   ├── rag.py        # Embedding, retrieval, answer generation
│   ├── worker.py     # Document ingestion pipeline
│   ├── database.py   # DynamoDB operations
│   ├── auth.py       # Cognito JWT validation
│   └── models.py     # Pydantic request/response models
└── infra/        # AWS CDK Python (all cloud resources)
```

## Features

- **Secure Registration** — Users register with First Name, Last Name, Date of Joining, Email, and Password. Email verification enforced via Cognito.
- **RAG Chat Interface** — ChatGPT-style UI with persistent sessions, message history, and the ability to delete conversations.
- **Grounded Answers** — Claude cites only the documents it actually used. Hallucination-resistant: returns a clear "I don't know" when documents don't contain the answer.
- **Clickable Sources** — Each cited source is a clickable link that opens the original document (pre-signed S3 URL, valid 5 minutes).
- **Automated Ingestion** — Uploading a PDF to the S3 raw bucket automatically triggers a Step Functions pipeline: extract → chunk → embed → index. No manual steps required.
- **Hybrid Search** — OpenSearch combines vector similarity (KNN) and keyword matching (BM25) for higher-quality retrieval.

## AWS Services Used

| Service | Purpose |
|---|---|
| Amazon Cognito | User authentication & email verification |
| Amazon API Gateway | REST API endpoint |
| AWS Lambda | FastAPI backend + ingestion worker |
| Amazon DynamoDB | Chat sessions, messages, document metadata |
| Amazon OpenSearch | Vector store (KNN + BM25 hybrid search) |
| Amazon S3 | Raw document storage + frontend hosting |
| AWS Step Functions | Document ingestion orchestration |
| Amazon Bedrock | Titan Text Embeddings v2 + Claude (chat) |
| Amazon CloudFront | Frontend CDN |

## Prerequisites

- AWS account with credentials configured locally (`aws configure`)
- Python 3.10+
- Node.js v18+ and npm
- AWS CDK CLI: `npm install -g aws-cdk`

## Deployment

### 1. Deploy Infrastructure

```bash
cd infra
python -m venv .venv

# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
npx aws-cdk bootstrap   # first time only
npx aws-cdk deploy
```

Note the stack outputs — you'll need them for the frontend config:
- `ApiUrl`
- `UserPoolId`
- `AppClientId`
- `RawBucketName`

### 2. Configure and Run the Frontend

```bash
cd frontend
npm install
```

Create a `.env` file in `/frontend`:

```env
VITE_USER_POOL_ID=us-east-1_xxxxx
VITE_APP_CLIENT_ID=xxxxxxxxxx
VITE_API_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com/prod
VITE_REGION=us-east-1
```

```bash
npm run dev
# Open http://localhost:5173
```

## Usage

1. **Register** — Click "Create an account", fill in your details, and verify your email.
2. **Upload documents** — In the AWS Console, find the S3 bucket with "RawBucket" in the name and upload PDF files (e.g., employee handbook, policy docs). The ingestion pipeline runs automatically; the status badge in the top-right corner shows *N Docs Ready*.
3. **Chat** — Click **New Chat**, ask a question. The assistant answers using only the uploaded documents and displays the source(s) below the response. Click a source to open the original document.

## Backend API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/docs/status` | Count of ready/processing/failed documents |
| `GET` | `/v1/docs/url?doc_title=...` | Generate pre-signed S3 URL for a document |
| `POST` | `/v1/chats` | Create a new chat session |
| `GET` | `/v1/chats` | List all sessions for the current user |
| `DELETE` | `/v1/chats/{session_id}` | Delete a session and its messages |
| `GET` | `/v1/chats/{session_id}/messages` | Retrieve message history |
| `POST` | `/v1/chats/{session_id}/messages` | Send a message and get a RAG response |

## Development Notes

- **Backend changes** require a CDK redeploy (`npx aws-cdk deploy`) to update the Lambda function code.
- **Frontend changes** hot-reload in development; run `npm run build` for a production build.
- **Models used**: Titan Text Embeddings v2 (1024-dim vectors), Claude for chat generation.
- **Chunk size**: 800 characters with 150-character overlap.
- **Retrieval**: top-10 hybrid search; sources filtered post-generation to only those cited in the answer.
