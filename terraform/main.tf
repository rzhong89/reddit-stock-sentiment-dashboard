terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

resource "aws_s3_bucket" "altdata_raw" {
  bucket = var.raw_bucket_name

  tags = {
    Name        = "AltData Raw"
    Project     = "Alternative Consumer Sentiment Dashboard"
    ManagedBy   = "Terraform"
  }
}

# --- IAM Role for Reddit Ingest Lambda ---
resource "aws_iam_role" "lambda_ingest_role" {
  name = "reddit-ingest-lambda-role"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Effect    = "Allow",
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_ingest_policy_s3" {
  role       = aws_iam_role.lambda_ingest_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess" # More restrictive in production
}

data "aws_secretsmanager_secret" "reddit_api_secret" {
  name = var.reddit_secret_name
}

resource "aws_iam_policy" "lambda_ingest_secrets_policy" {
  name        = "reddit-ingest-lambda-secrets-policy"
  description = "Policy to allow the ingest Lambda to read the Reddit API secret"

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action   = "secretsmanager:GetSecretValue",
        Effect   = "Allow",
        Resource = data.aws_secretsmanager_secret.reddit_api_secret.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_ingest_attach_secrets" {
  role       = aws_iam_role.lambda_ingest_role.name
  policy_arn = aws_iam_policy.lambda_ingest_secrets_policy.arn
}

resource "aws_iam_policy" "lambda_ingest_ssm_policy" {
  name        = "reddit-ingest-lambda-ssm-policy"
  description = "Policy to allow the ingest Lambda to use SSM Parameter Store for state and deduplication"

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action   = ["ssm:GetParameter", "ssm:PutParameter"],
        Effect   = "Allow",
        Resource = [
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/reddit/last_post_timestamp",
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/reddit/processed_post_ids"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_ingest_attach_ssm" {
  role       = aws_iam_role.lambda_ingest_role.name
  policy_arn = aws_iam_policy.lambda_ingest_ssm_policy.arn
}

resource "aws_iam_policy" "lambda_ingest_bedrock_policy" {
  name        = "reddit-ingest-lambda-bedrock-policy"
  description = "Policy to allow the ingest Lambda to invoke Bedrock models"

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action   = [
          "bedrock:InvokeModel",
          "bedrock:ListFoundationModels",
          "bedrock:GetFoundationModel"
        ],
        Effect   = "Allow",
        Resource = [
          "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_ingest_attach_bedrock" {
  role       = aws_iam_role.lambda_ingest_role.name
  policy_arn = aws_iam_policy.lambda_ingest_bedrock_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_ingest_policy_logs" {
  role       = aws_iam_role.lambda_ingest_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- Lambda Function for Reddit Ingest ---
data "archive_file" "lambda_ingest_zip" {
  type        = "zip"
  source_dir  = "../lambda_reddit_ingest/package"
  output_path = "${path.module}/lambda_ingest.zip"
}

resource "aws_lambda_function" "reddit_ingest" {
  function_name = "reddit-ingest"
  role          = aws_iam_role.lambda_ingest_role.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.9"
  timeout       = 180 # Increase timeout to 3 minutes for advanced processing
  memory_size   = 256 # Increase memory to 256 MB
  filename      = data.archive_file.lambda_ingest_zip.output_path
  source_code_hash = data.archive_file.lambda_ingest_zip.output_base64sha256

  environment {
    variables = {
      RAW_BUCKET_NAME    = var.raw_bucket_name
      REDDIT_SECRET_NAME = var.reddit_secret_name
      KEYWORDS           = var.keywords
      SUBREDDITS         = "stocks,investing,wallstreetbets"
      IGNORE_KEYWORDS    = "yolo,gain,loss,portfolio,bought,sold,trade"
      # Heuristic Filter Settings
      MIN_POST_SCORE     = "10"
      MIN_POST_LENGTH    = "200"
      MIN_COMMENT_SCORE  = "5"
      MIN_COMMENT_LENGTH = "50"
      # Bedrock Configuration
      BEDROCK_MODEL_ID   = "anthropic.claude-3-haiku-20240307-v1:0"
      BEDROCK_REGION     = var.aws_region
      # Fallback to disable AI if Bedrock access fails
      ENABLE_AI_RELEVANCE_CHECK = "false"
    }
  }

  tags = {
    Project   = "Alternative Consumer Sentiment Dashboard"
    ManagedBy = "Terraform"
  }
}

# --- CloudWatch Events to Trigger Lambda (Hybrid Approach) ---

# Primary: Every 2 hours during market hours (9:30 AM - 4:00 PM ET, Mon-Fri)
# Note: ET is UTC-5 (winter) or UTC-4 (summer), using UTC-5 for consistency
# 9:30 AM ET = 2:30 PM UTC, 4:00 PM ET = 9:00 PM UTC
resource "aws_cloudwatch_event_rule" "market_hours" {
  name                = "reddit-ingest-market-hours"
  description         = "Fires every 2 hours during market hours (Mon-Fri 9:30 AM - 4:00 PM ET)"
  schedule_expression = "cron(30 14,16,18,20 ? * MON-FRI *)"
  state               = var.ingestion_enabled ? "ENABLED" : "DISABLED"
}

# Secondary: Once per day after market close (6:00 PM ET = 11:00 PM UTC)
resource "aws_cloudwatch_event_rule" "after_hours" {
  name                = "reddit-ingest-after-hours"
  description         = "Fires once daily after market hours (Mon-Fri 6:00 PM ET)"
  schedule_expression = "cron(0 23 ? * MON-FRI *)"
  state               = var.ingestion_enabled ? "ENABLED" : "DISABLED"
}

# Targets for market hours schedule
resource "aws_cloudwatch_event_target" "trigger_lambda_market_hours" {
  rule      = aws_cloudwatch_event_rule.market_hours.name
  target_id = "TriggerRedditIngestLambdaMarketHours"
  arn       = aws_lambda_function.reddit_ingest.arn
}

# Targets for after hours schedule
resource "aws_cloudwatch_event_target" "trigger_lambda_after_hours" {
  rule      = aws_cloudwatch_event_rule.after_hours.name
  target_id = "TriggerRedditIngestLambdaAfterHours"
  arn       = aws_lambda_function.reddit_ingest.arn
}

# Lambda permissions for market hours
resource "aws_lambda_permission" "allow_cloudwatch_market_hours" {
  statement_id  = "AllowExecutionFromCloudWatchMarketHours"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reddit_ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.market_hours.arn
}

# Lambda permissions for after hours
resource "aws_lambda_permission" "allow_cloudwatch_after_hours" {
  statement_id  = "AllowExecutionFromCloudWatchAfterHours"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reddit_ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.after_hours.arn
}

# --- Company List Update Resources (DISABLED) ---
# These resources are commented out because the company list update Lambda
# is not essential for core Reddit sentiment analysis functionality.
# To enable, create the missing lambda_company_list_update directory and
# FMP_API_Key secret, then uncomment these resources.


# --- IAM Role for Sentiment Analysis Lambda ---
resource "aws_iam_role" "lambda_sentiment_role" {
  name = "sentiment-analysis-lambda-role"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Effect    = "Allow",
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "lambda_sentiment_policy" {
  name        = "sentiment-analysis-lambda-policy"
  description = "Policy for the sentiment analysis Lambda function"

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action   = [
          "s3:GetObject"
        ],
        Effect   = "Allow",
        Resource = "${aws_s3_bucket.altdata_raw.arn}/*"
      },
      {
        Action   = [
          "s3:PutObject"
        ],
        Effect   = "Allow",
        Resource = "${aws_s3_bucket.altdata_processed.arn}/*"
      },
      {
        Action   = [
          "comprehend:DetectSentiment"
        ],
        Effect   = "Allow",
        Resource = "*" # Can be restricted further if needed
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_sentiment_attach_custom" {
  role       = aws_iam_role.lambda_sentiment_role.name
  policy_arn = aws_iam_policy.lambda_sentiment_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_sentiment_attach_logs" {
  role       = aws_iam_role.lambda_sentiment_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- Lambda Function for Sentiment Analysis ---
data "archive_file" "lambda_sentiment_zip" {
  type        = "zip"
  source_dir  = "../lambda_sentiment_analysis/package"
  output_path = "${path.module}/lambda_sentiment.zip"
}

resource "aws_lambda_function" "sentiment_analysis" {
  function_name = "sentiment-analysis"
  role          = aws_iam_role.lambda_sentiment_role.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.9"
  filename      = data.archive_file.lambda_sentiment_zip.output_path
  source_code_hash = data.archive_file.lambda_sentiment_zip.output_base64sha256
  timeout       = 180  # 3 minutes to handle SageMaker serverless cold starts

  environment {
    variables = {
      PROCESSED_BUCKET_NAME             = var.processed_bucket_name
      SAGEMAKER_ENDPOINT_NAME           = "informative-emotional-endpoint"
      ENABLE_SAGEMAKER_CLASSIFICATION   = "false"  # DISABLED - SageMaker endpoint too expensive
    }
  }

  tags = {
    Project   = "Alternative Consumer Sentiment Dashboard"
    ManagedBy = "Terraform"
  }
}

# --- S3 Trigger for Sentiment Analysis Lambda ---
resource "aws_s3_bucket_notification" "raw_bucket_notification" {
  bucket = aws_s3_bucket.altdata_raw.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.sentiment_analysis.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "reddit-posts/"
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke_sentiment]
}

resource "aws_lambda_permission" "allow_s3_invoke_sentiment" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sentiment_analysis.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.altdata_raw.arn
}

# --- Glue and Athena Setup ---
resource "aws_glue_catalog_database" "altdata_db" {
  name = "altdata_sentiment_db"
}

resource "aws_iam_role" "glue_crawler_role" {
  name = "glue-crawler-role"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Effect    = "Allow",
        Principal = {
          Service = "glue.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "glue_crawler_policy" {
  role       = aws_iam_role.glue_crawler_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy_attachment" "glue_crawler_s3_policy" {
  role       = aws_iam_role.glue_crawler_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess" # More restrictive in production
}

resource "aws_glue_crawler" "processed_data_crawler" {
  name          = "altdata-processed-data-crawler"
  database_name = aws_glue_catalog_database.altdata_db.name
  role          = aws_iam_role.glue_crawler_role.arn

  s3_target {
    path = "s3://${var.processed_bucket_name}/reddit-posts/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  configuration = jsonencode({
    Version = 1.0,
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
  })

  schedule = "cron(0 1 * * ? *)" # Run once a day at 1 AM UTC
}

# --- S3 Bucket for Athena Query Results ---
resource "aws_s3_bucket" "athena_results" {
  bucket = var.athena_results_bucket_name
}

# --- S3 Bucket for Frontend Website Hosting ---
resource "aws_s3_bucket" "frontend_bucket" {
  bucket = "altdata-sentiment-dashboard-website"
}

resource "aws_s3_bucket_website_configuration" "frontend_website_config" {
  bucket = aws_s3_bucket.frontend_bucket.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

resource "aws_s3_bucket_public_access_block" "frontend_bucket_pab" {
  bucket = aws_s3_bucket.frontend_bucket.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "frontend_bucket_policy" {
  bucket = aws_s3_bucket.frontend_bucket.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid       = "PublicReadGetObject",
        Effect    = "Allow",
        Principal = "*",
        Action    = "s3:GetObject",
        Resource  = "${aws_s3_bucket.frontend_bucket.arn}/*"
      }
    ]
  })
}

resource "aws_s3_object" "frontend_files" {
  for_each = fileset("../frontend", "**")

  bucket       = aws_s3_bucket.frontend_bucket.id
  key          = each.value
  source       = "../frontend/${each.value}"
  content_type = lookup({
    "html" = "text/html",
    "css"  = "text/css",
    "js"   = "application/javascript"
  }, split(".", each.value)[length(split(".", each.value)) - 1], "application/octet-stream")
  etag = filemd5("../frontend/${each.value}")
}

# --- IAM Role for API Query Lambda ---
resource "aws_iam_role" "lambda_api_query_role" {
  name = "api-query-lambda-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_policy" "lambda_api_query_policy" {
  name        = "api-query-lambda-policy"
  description = "Policy for the API query Lambda function"
  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action   = [
          "athena:StartQueryExecution", 
          "athena:GetQueryExecution", 
          "athena:GetQueryResults",
          "athena:GetWorkGroup"
        ],
        Effect   = "Allow",
        Resource = "*"
      },
      {
        Action   = [
          "glue:GetTable",
          "glue:GetDatabase",
          "glue:GetPartitions"
        ],
        Effect   = "Allow",
        Resource = [
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_database.altdata_db.name}",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.altdata_db.name}/*",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog"
        ]
      },
      {
        Action   = [
          "s3:GetObject", 
          "s3:ListBucket", 
          "s3:PutObject", 
          "s3:GetBucketLocation"
        ],
        Effect   = "Allow",
        Resource = [
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*",
          "arn:aws:s3:::${var.processed_bucket_name}",
          "arn:aws:s3:::${var.processed_bucket_name}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_api_query_attach_custom" {
  role       = aws_iam_role.lambda_api_query_role.name
  policy_arn = aws_iam_policy.lambda_api_query_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_api_query_attach_logs" {
  role       = aws_iam_role.lambda_api_query_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- Lambda Function for API Query ---
data "archive_file" "lambda_api_query_zip" {
  type        = "zip"
  source_dir  = "../lambda_api_query/package"
  output_path = "${path.module}/lambda_api_query.zip"
}

resource "aws_lambda_function" "api_query" {
  function_name = "api-query"
  role          = aws_iam_role.lambda_api_query_role.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.9"
  timeout       = 30
  memory_size   = 256
  filename      = data.archive_file.lambda_api_query_zip.output_path
  source_code_hash = data.archive_file.lambda_api_query_zip.output_base64sha256

  environment {
    variables = {
      ATHENA_DATABASE      = aws_glue_catalog_database.altdata_db.name
      ATHENA_TABLE         = "reddit_posts"
      ATHENA_OUTPUT_BUCKET = var.athena_results_bucket_name
      KEYWORDS             = var.keywords
    }
  }
}

# --- API Gateway ---
resource "aws_api_gateway_rest_api" "sentiment_api" {
  name        = "SentimentAnalysisAPI"
  description = "API for querying Reddit sentiment data"
  
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# --- API Gateway Usage Plan for Rate Limiting ---
resource "aws_api_gateway_usage_plan" "sentiment_api_usage_plan" {
  name         = "sentiment-api-usage-plan"
  description  = "Usage plan for sentiment analysis API with rate limiting"

  api_stages {
    api_id = aws_api_gateway_rest_api.sentiment_api.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }

  quota_settings {
    limit  = 10000 # 10,000 requests per day
    period = "DAY"
  }

  throttle_settings {
    rate_limit  = 100 # 100 requests per second
    burst_limit = 200 # 200 concurrent requests
  }
}

# --- API Gateway API Key ---
resource "aws_api_gateway_api_key" "sentiment_api_key" {
  name        = "sentiment-api-key"
  description = "API key for sentiment analysis API"
}

# --- API Gateway Usage Plan Key ---
resource "aws_api_gateway_usage_plan_key" "sentiment_api_usage_plan_key" {
  key_id        = aws_api_gateway_api_key.sentiment_api_key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.sentiment_api_usage_plan.id
}

resource "aws_api_gateway_resource" "query_resource" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  parent_id   = aws_api_gateway_rest_api.sentiment_api.root_resource_id
  path_part   = "query"
}

resource "aws_api_gateway_method" "query_method" {
  rest_api_id   = aws_api_gateway_rest_api.sentiment_api.id
  resource_id   = aws_api_gateway_resource.query_resource.id
  http_method   = "GET"
  authorization = "NONE"
  api_key_required = true
}

# --- CORS OPTIONS method for query endpoint ---
resource "aws_api_gateway_method" "query_options_method" {
  rest_api_id   = aws_api_gateway_rest_api.sentiment_api.id
  resource_id   = aws_api_gateway_resource.query_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "query_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  resource_id = aws_api_gateway_resource.query_resource.id
  http_method = aws_api_gateway_method.query_options_method.http_method
  type        = "MOCK"
  
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "query_options_200" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  resource_id = aws_api_gateway_resource.query_resource.id
  http_method = aws_api_gateway_method.query_options_method.http_method
  status_code = "200"
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "query_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  resource_id = aws_api_gateway_resource.query_resource.id
  http_method = aws_api_gateway_method.query_options_method.http_method
  status_code = aws_api_gateway_method_response.query_options_200.status_code
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

resource "aws_api_gateway_integration" "lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.sentiment_api.id
  resource_id             = aws_api_gateway_resource.query_resource.id
  http_method             = aws_api_gateway_method.query_method.http_method
  integration_http_method = "POST" # Lambda integrations use POST
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.api_query.invoke_arn
}

resource "aws_api_gateway_deployment" "api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id

  # This triggers a new deployment whenever the API definition changes.
  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.query_resource.id,
      aws_api_gateway_method.query_method.id,
      aws_api_gateway_integration.lambda_integration.id,
      aws_api_gateway_resource.ticker_search_resource.id,
      aws_api_gateway_method.ticker_search_method.id,
      aws_api_gateway_integration.ticker_search_integration.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.sentiment_api.id
  stage_name    = "prod"
}

resource "aws_lambda_permission" "allow_api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.sentiment_api.execution_arn}/*/*"
}

# --- Ticker Search Lambda Function ---
resource "aws_iam_role" "lambda_ticker_search_role" {
  name = "ticker-search-lambda-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_policy" "lambda_ticker_search_policy" {
  name        = "ticker-search-lambda-policy"
  description = "Policy for the ticker search Lambda function"
  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action   = "secretsmanager:GetSecretValue",
        Effect   = "Allow",
        Resource = data.aws_secretsmanager_secret.reddit_api_secret.arn
      },
      {
        Action   = "comprehend:DetectSentiment",
        Effect   = "Allow",
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_ticker_search_attach_custom" {
  role       = aws_iam_role.lambda_ticker_search_role.name
  policy_arn = aws_iam_policy.lambda_ticker_search_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_ticker_search_attach_logs" {
  role       = aws_iam_role.lambda_ticker_search_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "archive_file" "lambda_ticker_search_zip" {
  type        = "zip"
  source_dir  = "../lambda_ticker_search/package"
  output_path = "${path.module}/lambda_ticker_search.zip"
}

resource "aws_lambda_function" "ticker_search" {
  function_name = "ticker-search"
  role          = aws_iam_role.lambda_ticker_search_role.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.9"
  timeout       = 60
  memory_size   = 512
  filename      = data.archive_file.lambda_ticker_search_zip.output_path
  source_code_hash = data.archive_file.lambda_ticker_search_zip.output_base64sha256

  environment {
    variables = {
      REDDIT_SECRET_NAME = var.reddit_secret_name
    }
  }

  tags = {
    Project   = "Alternative Consumer Sentiment Dashboard"
    ManagedBy = "Terraform"
  }
}

# --- API Gateway Resources for Ticker Search ---
resource "aws_api_gateway_resource" "ticker_search_resource" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  parent_id   = aws_api_gateway_rest_api.sentiment_api.root_resource_id
  path_part   = "search"
}

resource "aws_api_gateway_method" "ticker_search_method" {
  rest_api_id   = aws_api_gateway_rest_api.sentiment_api.id
  resource_id   = aws_api_gateway_resource.ticker_search_resource.id
  http_method   = "GET"
  authorization = "NONE"
  api_key_required = true
}

# --- CORS OPTIONS method for ticker search endpoint ---
resource "aws_api_gateway_method" "ticker_search_options_method" {
  rest_api_id   = aws_api_gateway_rest_api.sentiment_api.id
  resource_id   = aws_api_gateway_resource.ticker_search_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "ticker_search_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  resource_id = aws_api_gateway_resource.ticker_search_resource.id
  http_method = aws_api_gateway_method.ticker_search_options_method.http_method
  type        = "MOCK"
  
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "ticker_search_options_200" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  resource_id = aws_api_gateway_resource.ticker_search_resource.id
  http_method = aws_api_gateway_method.ticker_search_options_method.http_method
  status_code = "200"
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "ticker_search_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.sentiment_api.id
  resource_id = aws_api_gateway_resource.ticker_search_resource.id
  http_method = aws_api_gateway_method.ticker_search_options_method.http_method
  status_code = aws_api_gateway_method_response.ticker_search_options_200.status_code
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

resource "aws_api_gateway_integration" "ticker_search_integration" {
  rest_api_id             = aws_api_gateway_rest_api.sentiment_api.id
  resource_id             = aws_api_gateway_resource.ticker_search_resource.id
  http_method             = aws_api_gateway_method.ticker_search_method.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.ticker_search.invoke_arn
}

resource "aws_lambda_permission" "allow_api_gateway_ticker_search" {
  statement_id  = "AllowAPIGatewayInvokeTickerSearch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ticker_search.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.sentiment_api.execution_arn}/*/*"
}

# --- Data Labeling Lambda Function ---
resource "aws_iam_role" "lambda_data_labeling_role" {
  name = "data-labeling-lambda-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_policy" "lambda_data_labeling_policy" {
  name        = "data-labeling-lambda-policy"
  description = "Policy for the data labeling Lambda function"
  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action   = [
          "athena:StartQueryExecution", 
          "athena:GetQueryExecution", 
          "athena:GetQueryResults",
          "athena:GetWorkGroup"
        ],
        Effect   = "Allow",
        Resource = "*"
      },
      {
        Action   = [
          "glue:GetTable",
          "glue:GetDatabase",
          "glue:GetPartitions"
        ],
        Effect   = "Allow",
        Resource = [
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_database.altdata_db.name}",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.altdata_db.name}/*",
          "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog"
        ]
      },
      {
        Action   = [
          "s3:GetObject", 
          "s3:ListBucket"
        ],
        Effect   = "Allow",
        Resource = [
          "arn:aws:s3:::${var.processed_bucket_name}",
          "arn:aws:s3:::${var.processed_bucket_name}/*"
        ]
      },
      {
        Action   = [
          "s3:PutObject", 
          "s3:GetBucketLocation"
        ],
        Effect   = "Allow",
        Resource = [
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*",
          aws_s3_bucket.sagemaker_training_data.arn,
          "${aws_s3_bucket.sagemaker_training_data.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_data_labeling_attach_custom" {
  role       = aws_iam_role.lambda_data_labeling_role.name
  policy_arn = aws_iam_policy.lambda_data_labeling_policy.arn
}

resource "aws_iam_role_policy_attachment" "lambda_data_labeling_attach_logs" {
  role       = aws_iam_role.lambda_data_labeling_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "archive_file" "lambda_data_labeling_zip" {
  type        = "zip"
  source_dir  = "../lambda_data_labeling/package"
  output_path = "${path.module}/lambda_data_labeling.zip"
}

resource "aws_lambda_function" "data_labeling" {
  function_name = "data-labeling"
  role          = aws_iam_role.lambda_data_labeling_role.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.9"
  timeout       = 900  # 15 minutes
  memory_size   = 512
  filename      = data.archive_file.lambda_data_labeling_zip.output_path
  source_code_hash = data.archive_file.lambda_data_labeling_zip.output_base64sha256

  environment {
    variables = {
      PROCESSED_BUCKET_NAME     = var.processed_bucket_name
      TRAINING_DATA_BUCKET      = var.training_data_bucket_name
      ATHENA_DATABASE           = aws_glue_catalog_database.altdata_db.name
      ATHENA_OUTPUT_BUCKET      = var.athena_results_bucket_name
      MAX_POSTS_PER_EXTRACTION  = "5000"
    }
  }

  tags = {
    Project   = "Alternative Consumer Sentiment Dashboard"
    ManagedBy = "Terraform"
  }
}


data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_s3_bucket" "altdata_processed" {
  bucket = var.processed_bucket_name

  tags = {
    Name        = "AltData Processed"
    Project     = "Alternative Consumer Sentiment Dashboard"
    ManagedBy   = "Terraform"
  }
}

# --- S3 Buckets for SageMaker ---
resource "aws_s3_bucket" "sagemaker_training_data" {
  bucket = var.training_data_bucket_name

  tags = {
    Name        = "SageMaker Training Data"
    Project     = "Alternative Consumer Sentiment Dashboard"
    ManagedBy   = "Terraform"
  }
}

resource "aws_s3_bucket" "sagemaker_models" {
  bucket = var.sagemaker_model_bucket_name

  tags = {
    Name        = "SageMaker Model Artifacts"
    Project     = "Alternative Consumer Sentiment Dashboard"
    ManagedBy   = "Terraform"
  }
}

# --- CloudWatch Dashboard ---
resource "aws_cloudwatch_dashboard" "sentiment_dashboard" {
  dashboard_name = "sentiment-analysis-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6

        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.reddit_ingest.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.reddit_ingest.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.reddit_ingest.function_name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "Reddit Ingest Lambda Metrics"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6

        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.sentiment_analysis.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.sentiment_analysis.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.sentiment_analysis.function_name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "Sentiment Analysis Lambda Metrics"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6

        properties = {
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.api_query.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.api_query.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.api_query.function_name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "API Query Lambda Metrics"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6

        properties = {
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiName", aws_api_gateway_rest_api.sentiment_api.name],
            ["AWS/ApiGateway", "Latency", "ApiName", aws_api_gateway_rest_api.sentiment_api.name],
            ["AWS/ApiGateway", "4XXError", "ApiName", aws_api_gateway_rest_api.sentiment_api.name],
            ["AWS/ApiGateway", "5XXError", "ApiName", aws_api_gateway_rest_api.sentiment_api.name]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "API Gateway Metrics"
          period  = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6

        properties = {
          metrics = [
            ["AWS/S3", "BucketSizeBytes", "BucketName", aws_s3_bucket.altdata_raw.bucket, "StorageType", "StandardStorage"],
            ["AWS/S3", "BucketSizeBytes", "BucketName", aws_s3_bucket.altdata_processed.bucket, "StorageType", "StandardStorage"]
          ]
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          title   = "S3 Storage Usage"
          period  = 86400
        }
      }
    ]
  })
}

# --- CloudWatch Alarms ---
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "sentiment-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic           = "Sum"
  threshold           = "5"
  alarm_description   = "This metric monitors lambda errors"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = aws_lambda_function.reddit_ingest.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  alarm_name          = "sentiment-lambda-duration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = "300"
  statistic           = "Average"
  threshold           = "120000"  # 2 minutes
  alarm_description   = "This metric monitors lambda duration"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    FunctionName = aws_lambda_function.reddit_ingest.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "api_gateway_errors" {
  alarm_name          = "sentiment-api-gateway-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "5XXError"
  namespace           = "AWS/ApiGateway"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "This metric monitors API Gateway 5XX errors"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ApiName = aws_api_gateway_rest_api.sentiment_api.name
  }
}

resource "aws_cloudwatch_metric_alarm" "api_gateway_latency" {
  alarm_name          = "sentiment-api-gateway-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "3"
  metric_name         = "Latency"
  namespace           = "AWS/ApiGateway"
  period              = "300"
  statistic           = "Average"
  threshold           = "10000"  # 10 seconds
  alarm_description   = "This metric monitors API Gateway latency"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ApiName = aws_api_gateway_rest_api.sentiment_api.name
  }
}

# --- SNS Topic for Alerts ---
resource "aws_sns_topic" "alerts" {
  name = "sentiment-analysis-alerts"
}

resource "aws_sns_topic_subscription" "email_alerts" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email  # Add this variable to variables.tf
}

# --- CloudWatch Log Groups (OPTIONAL) ---
# These log groups already exist and are managed automatically by Lambda.
# Uncomment if you want to manage retention via Terraform, then import existing groups.
/*
resource "aws_cloudwatch_log_group" "reddit_ingest_logs" {
  name              = "/aws/lambda/${aws_lambda_function.reddit_ingest.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "sentiment_analysis_logs" {
  name              = "/aws/lambda/${aws_lambda_function.sentiment_analysis.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "api_query_logs" {
  name              = "/aws/lambda/${aws_lambda_function.api_query.function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "ticker_search_logs" {
  name              = "/aws/lambda/${aws_lambda_function.ticker_search.function_name}"
  retention_in_days = 14
}
*/