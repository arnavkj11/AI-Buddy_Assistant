# AI Buddy Assistant Prototype

An end-to-end prototype of an AI Buddy Assistant intended for employee onboarding. This system allows users to register, log in, and interact with a RAG-powered chatbot. Documents used for grounding are manually uploaded to an S3 bucket, triggering an ingestion pipeline that extracts, chunks, embeds, and indexes the content in OpenSearch.

## Directory Structure
- `/infra`: AWS CDK Python project defining the infrastructure (API Gateway, Lambda, Cognito, IAM, S3, DynamoDB, OpenSearch, Step Functions, CloudFront).
- `/backend`: FastAPI Python backend powered by Mangum for serverless deployment on AWS Lambda.
- `/frontend`: React + Vite + TypeScript web interface using AWS Amplify Auth.

## Features
- **Strict Registration**: Normal users must register providing First Name, Last Name, Date of Joining, Email, and Password. Email verification is enforced.
- **RAG Chat Experience**: ChatGPT-like interface with persistent message history and session management.
- **Grounded Answers**: Amazon Bedrock Titan embeddings query Amazon OpenSearch using vector similarity. Claude 3 generates grounded responses citing specific document sections. Prevents hallucinations for out-of-bounds questions.
- **Automated Ingestion**: Dropping a PDF into the raw S3 bucket triggers an AWS Step Functions state machine which chunks text, retrieves embeddings, and upserts into OpenSearch without manual interaction.

## Prerequisites
- AWS Account configured locally
- Python 3.10+
- Node.js v18+ & npm
- AWS CDK CLI installed (`npm i -g aws-cdk`)

## Deployment Instructions

### 1. Deploy Infrastructure (AWS CDK)
1. Open a terminal and navigate to the `/infra` directory.
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Mac/Linux:
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Bootstrap and Deploy the stack to your AWS environment:
   ```bash
   npx aws-cdk bootstrap
   npx aws-cdk deploy
   ```
5. Note the outputs produced by CDK (e.g., `AiBuddyApiEndpoint`, `UserPoolId`, `AppClientId`, `RawBucketName`, etc.).

### 2. Configure & Run Frontend
1. Navigate to the `/frontend` directory.
2. Install Node dependencies:
   ```bash
   npm install
   ```
3. Create a `.env` file in `/frontend` mapping to the CDK outputs:
   ```env
   VITE_USER_POOL_ID=us-east-1_xxxxx
   VITE_APP_CLIENT_ID=xxxxxxxxxx
   VITE_API_URL=https://xxxxxxxx.execute-api.us-east-1.amazonaws.com/prod
   VITE_REGION=us-east-1
   ```
4. Start the local dev server:
   ```bash
   npm run dev
   ```
5. Open `http://localhost:5173` to test the application!

## Testing the Prototype

1. **User Registration:**
   Navigate to the app, click "Create an account", fill out the details including the Date of Joining. Verify the email code sent via Cognito.
2. **Document Upload:**
   Log into the AWS Console, locate your S3 Bucket containing "RawBucket" in the name, and upload a `pdf` document (e.g., Employee Handbook).
3. **Chat:**
   Go to the frontend, click **New Chat**, and ask a question relevant to the uploaded document. The assistant will answer and display a `Sources` block beneath the response.