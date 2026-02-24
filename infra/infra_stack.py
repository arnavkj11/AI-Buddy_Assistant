from aws_cdk import (
    Stack,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_s3_deployment as s3_deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_opensearchservice as opensearch,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_lambda as _lambda,
    aws_apigateway as apigateway,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
    aws_s3_notifications as s3n,
    RemovalPolicy,
    CfnOutput,
    Duration,
)
from constructs import Construct

class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ==========================================
        # 1. Cognito User Pool
        # ==========================================
        self.user_pool = cognito.UserPool(
            self, "AiBuddyUserPool",
            user_pool_name="AiBuddyUsers",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True, username=False),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                given_name=cognito.StandardAttribute(required=True, mutable=True),
                family_name=cognito.StandardAttribute(required=True, mutable=True)
            ),
            custom_attributes={
                "date_of_joining": cognito.StringAttribute(mutable=True)
            },
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False
            ),
            removal_policy=RemovalPolicy.DESTROY  # Prototype only
        )

        self.user_pool_client = cognito.UserPoolClient(
            self, "AiBuddyAppClient",
            user_pool=self.user_pool,
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True, user_password=True)
        )

        # ==========================================
        # 2. DynamoDB Tables
        # ==========================================
        self.documents_table = dynamodb.Table(
            self, "DocumentsTable",
            partition_key=dynamodb.Attribute(name="doc_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        self.chat_sessions_table = dynamodb.Table(
            self, "ChatSessionsTable",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="session_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )
        self.chat_sessions_table.add_global_secondary_index(
            index_name="LastActiveIndex",
            partition_key=dynamodb.Attribute(name="user_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="last_active_at", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.ALL
        )

        self.chat_messages_table = dynamodb.Table(
            self, "ChatMessagesTable",
            partition_key=dynamodb.Attribute(name="session_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="ts", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        # ==========================================
        # 3. S3 Buckets
        # ==========================================
        self.raw_bucket = s3.Bucket(
            self, "DocsRawBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            cors=[s3.CorsRule(
                allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.PUT, s3.HttpMethods.POST],
                allowed_origins=["*"],
                allowed_headers=["*"]
            )]
        )

        self.processed_bucket = s3.Bucket(
            self, "DocsProcessedBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        # ==========================================
        # 4. OpenSearch Domain
        # ==========================================
        self.opensearch_domain = opensearch.Domain(
            self, "AiBuddyOSDomain",
            version=opensearch.EngineVersion.OPENSEARCH_2_11,
            capacity=opensearch.CapacityConfig(
                data_node_instance_type="t3.small.search",
                data_nodes=1
            ),
            ebs=opensearch.EbsOptions(
                volume_size=10,
                volume_type=ec2.EbsDeviceVolumeType.GP3
            ),
            enforce_https=True,
            node_to_node_encryption=True,
            encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
            removal_policy=RemovalPolicy.DESTROY
        )

        # ==========================================
        # 5. IAM Roles for Lambdas
        # ==========================================
        api_lambda_role = iam.Role(self, "ApiLambdaRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        api_lambda_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))
        
        worker_lambda_role = iam.Role(self, "WorkerLambdaRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        worker_lambda_role.add_managed_policy(iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"))

        # Bedrock Access
        bedrock_policy = iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=["*"] # Can restrict to specific Claude/Titan models
        )
        api_lambda_role.add_to_policy(bedrock_policy)
        worker_lambda_role.add_to_policy(bedrock_policy)

        # OpenSearch Access
        self.opensearch_domain.grant_read_write(api_lambda_role)
        self.opensearch_domain.grant_read_write(worker_lambda_role)

        # DDB Access
        self.documents_table.grant_read_write_data(api_lambda_role)
        self.documents_table.grant_read_write_data(worker_lambda_role)
        self.chat_sessions_table.grant_read_write_data(api_lambda_role)
        self.chat_messages_table.grant_read_write_data(api_lambda_role)

        # S3 Access
        self.raw_bucket.grant_read_write(api_lambda_role)
        self.raw_bucket.grant_read(worker_lambda_role)
        self.processed_bucket.grant_read_write(worker_lambda_role)

        # ==========================================
        # 5.5 Lambda Layer for Dependencies
        # ==========================================
        self.dependencies_layer = _lambda.LayerVersion(
            self, "DependenciesLayer",
            code=_lambda.Code.from_asset("../backend/lambda_layer"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_11],
            description="Python dependencies for backend Lambda functions"
        )

        # ==========================================
        # 6. Backend API (FastAPI)
        # ==========================================
        self.api_lambda = _lambda.Function(
            self, "ApiHandler",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset("../backend", exclude=["lambda_layer", "*.pyc", "__pycache__"]),
            handler="main.handler",
            role=api_lambda_role,
            layers=[self.dependencies_layer],
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "USER_POOL_ID": self.user_pool.user_pool_id,
                "APP_CLIENT_ID": self.user_pool_client.user_pool_client_id,
                "OS_ENDPOINT": self.opensearch_domain.domain_endpoint,
                "CHAT_SESSIONS_TABLE": self.chat_sessions_table.table_name,
                "CHAT_MESSAGES_TABLE": self.chat_messages_table.table_name,
                "DOCUMENTS_TABLE": self.documents_table.table_name,
                "RAW_BUCKET": self.raw_bucket.bucket_name,
            }
        )

        # API Gateway
        self.api_gw = apigateway.LambdaRestApi(
            self, "AiBuddyApi",
            handler=self.api_lambda,
            proxy=True,
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"]
            )
        )

        # Add CORS headers to API Gateway error responses (4xx/5xx).
        # Without this, Lambda errors return responses without CORS headers,
        # and browsers mis-report them as CORS failures instead of real errors.
        cors_headers = {
            "Access-Control-Allow-Origin": "'*'",
            "Access-Control-Allow-Headers": "'Content-Type,Authorization'",
        }
        self.api_gw.add_gateway_response(
            "Default4xxCors",
            type=apigateway.ResponseType.DEFAULT_4_XX,
            response_headers=cors_headers,
        )
        self.api_gw.add_gateway_response(
            "Default5xxCors",
            type=apigateway.ResponseType.DEFAULT_5_XX,
            response_headers=cors_headers,
        )

        # ==========================================
        # 7. Ingestion Pipeline (Step Functions)
        # ==========================================
        self.worker_lambda = _lambda.Function(
            self, "IngestionWorker",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset("../backend", exclude=["lambda_layer", "*.pyc", "__pycache__"]),
            handler="worker.handler",
            role=worker_lambda_role,
            layers=[self.dependencies_layer],
            timeout=Duration.minutes(5),
            memory_size=1024,
            environment={
                "OS_ENDPOINT": self.opensearch_domain.domain_endpoint,
                "DOCUMENTS_TABLE": self.documents_table.table_name,
                "PROCESSED_BUCKET": self.processed_bucket.bucket_name
            }
        )

        # Define Step Function Tasks
        extract_task = tasks.LambdaInvoke(
            self, "ExtractText",
            lambda_function=self.worker_lambda,
            payload=sfn.TaskInput.from_object({
                "step": "extract",
                "input": sfn.JsonPath.string_at("$")
            }),
            result_path="$.extractResult",
            output_path="$"
        )
        
        chunk_embed_index_task = tasks.LambdaInvoke(
            self, "ChunkEmbedIndex",
            lambda_function=self.worker_lambda,
            payload=sfn.TaskInput.from_object({
                "step": "chunk_embed_index",
                "input": sfn.JsonPath.string_at("$")
            }),
            result_path="$.indexResult"
        )

        definition = extract_task.next(chunk_embed_index_task)

        self.state_machine = sfn.StateMachine(
            self, "IngestionPipeline",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.minutes(15)
        )

        # S3 Trigger Lambda
        self.trigger_lambda = _lambda.Function(
            self, "S3IngestionTrigger",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_inline('''
import json, os, boto3
sfn = boto3.client('stepfunctions')
def handler(event, context):
    for rec in event['Records']:
        bucket = rec['s3']['bucket']['name']
        key = rec['s3']['object']['key']
        sfn.start_execution(
            stateMachineArn=os.environ['SFN_ARN'],
            input=json.dumps({"bucket": bucket, "key": key})
        )
    return {"status": "started"}
            '''),
            handler="index.handler",
            environment={
                "SFN_ARN": self.state_machine.state_machine_arn
            }
        )
        self.state_machine.grant_start_execution(self.trigger_lambda)
        self.raw_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.trigger_lambda)
        )

        # ==========================================
        # 8. Frontend Hosting (CloudFront + S3)
        # ==========================================
        self.frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True
        )

        self.frontend_distribution = cloudfront.Distribution(
            self, "FrontendDist",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.frontend_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS
            ),
            error_responses=[cloudfront.ErrorResponse(
                http_status=404,
                response_http_status=200,
                response_page_path="/index.html"
            )]
        )

        # Outputs
        CfnOutput(self, "ApiUrl", value=self.api_gw.url)
        CfnOutput(self, "CloudFrontUrl", value=self.frontend_distribution.domain_name)
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "AppClientId", value=self.user_pool_client.user_pool_client_id)
        CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)
