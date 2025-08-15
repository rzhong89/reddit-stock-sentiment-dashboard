# --- SageMaker Resources for Informative/Emotional Classification ---

# IAM Role for SageMaker Execution
resource "aws_iam_role" "sagemaker_execution_role" {
  name = "sagemaker-informative-emotional-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "sagemaker.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project   = "Alternative Consumer Sentiment Dashboard"
    ManagedBy = "Terraform"
  }
}

# SageMaker Execution Role Policy
resource "aws_iam_role_policy" "sagemaker_execution_policy" {
  name = "sagemaker-informative-emotional-execution-policy"
  role = aws_iam_role.sagemaker_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.sagemaker_training_data.arn}",
          "${aws_s3_bucket.sagemaker_training_data.arn}/*",
          "${aws_s3_bucket.sagemaker_models.arn}",
          "${aws_s3_bucket.sagemaker_models.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:CreateLogGroup",
          "logs:DescribeLogStreams",
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })
}

# Attach the SageMaker service policy
resource "aws_iam_role_policy_attachment" "sagemaker_execution_policy_attachment" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

# Note: SageMaker Model, Endpoint Configuration, and Endpoint are commented out
# because they require a trained model artifact to exist first.
# Uncomment and run terraform apply after training your model.

# SageMaker Model (DISABLED - too expensive)
# resource "aws_sagemaker_model" "informative_emotional_model" {
#   name               = "informative-emotional-classifier-model"
#   execution_role_arn = aws_iam_role.sagemaker_execution_role.arn
# 
#   primary_container {
#     # Using PyTorch Deep Learning Container for BERT models
#     image = "763104351884.dkr.ecr.${data.aws_region.current.name}.amazonaws.com/pytorch-inference:1.12.0-cpu-py38-ubuntu20.04-sagemaker"
#     
#     # Model artifacts from your training job
#     model_data_url = "s3://altdata-sagemaker-models/pytorch-training-2025-08-08-02-02-19-803/output/model.tar.gz"
#     
#     environment = {
#       SAGEMAKER_PROGRAM = "inference.py"
#       SAGEMAKER_SUBMIT_DIRECTORY = "/opt/ml/code"
#     }
#   }
# 
#   tags = {
#     Project   = "Alternative Consumer Sentiment Dashboard"
#     ManagedBy = "Terraform"
#   }
# }

# SageMaker Endpoint Configuration (DISABLED - too expensive)
# resource "aws_sagemaker_endpoint_configuration" "informative_emotional_endpoint_config" {
#   name = "informative-emotional-endpoint-config"
# 
#   production_variants {
#     variant_name           = "primary"
#     model_name            = aws_sagemaker_model.informative_emotional_model.name
#     initial_variant_weight = 1
# 
#     serverless_config {
#       max_concurrency   = 5      # Max concurrent requests
#       memory_size_in_mb = 2048   # 2GB memory for BERT model
#     }
#   }
# 
#   # Data capture configuration disabled for serverless endpoints
#   # data_capture_config {
#   #   enable_capture              = true
#   #   initial_sampling_percentage = 20
#   #   destination_s3_uri          = "s3://${aws_s3_bucket.sagemaker_models.bucket}/data-capture/"
#   #   
#   #   capture_options {
#   #     capture_mode = "Input"
#   #   }
#   #   
#   #   capture_options {
#   #     capture_mode = "Output"  
#   #   }
#   #
#   #   capture_content_type_header {
#   #     json_content_types = ["application/json"]
#   #   }
#   # }
# 
#   tags = {
#     Project   = "Alternative Consumer Sentiment Dashboard"
#     ManagedBy = "Terraform"
#   }
# }

# SageMaker Endpoint (DISABLED - too expensive)
# resource "aws_sagemaker_endpoint" "informative_emotional_endpoint" {
#   name                 = "informative-emotional-endpoint"
#   endpoint_config_name = aws_sagemaker_endpoint_configuration.informative_emotional_endpoint_config.name
# 
#   tags = {
#     Project   = "Alternative Consumer Sentiment Dashboard"
#     ManagedBy = "Terraform"
#   }
# }

# CloudWatch Log Group for SageMaker
resource "aws_cloudwatch_log_group" "sagemaker_training_logs" {
  name              = "/aws/sagemaker/TrainingJobs"
  retention_in_days = 14

  tags = {
    Project   = "Alternative Consumer Sentiment Dashboard"
    ManagedBy = "Terraform"
  }
}

resource "aws_cloudwatch_log_group" "sagemaker_endpoint_logs" {
  name              = "/aws/sagemaker/Endpoints/informative-emotional-endpoint"
  retention_in_days = 14

  tags = {
    Project   = "Alternative Consumer Sentiment Dashboard"
    ManagedBy = "Terraform"
  }
}

# Lambda IAM policy for SageMaker endpoint access (DISABLED)
# resource "aws_iam_policy" "lambda_sagemaker_policy" {
#   name        = "lambda-sagemaker-endpoint-access-policy"
#   description = "Policy for Lambda to invoke SageMaker endpoint"
# 
#   policy = jsonencode({
#     Version = "2012-10-17"
#     Statement = [
#       {
#         Effect = "Allow"
#         Action = [
#           "sagemaker:InvokeEndpoint"
#         ]
#         Resource = [
#           aws_sagemaker_endpoint.informative_emotional_endpoint.arn
#         ]
#       }
#     ]
#   })
# }

# Attach SageMaker policy to sentiment analysis Lambda role (DISABLED)
# resource "aws_iam_role_policy_attachment" "lambda_sentiment_attach_sagemaker" {
#   role       = aws_iam_role.lambda_sentiment_role.name
#   policy_arn = aws_iam_policy.lambda_sagemaker_policy.arn
# }

# Auto-scaling for SageMaker endpoint (DISABLED - not compatible with serverless)
# resource "aws_appautoscaling_target" "sagemaker_endpoint_target" {
#   max_capacity       = 3
#   min_capacity       = 1
#   resource_id        = "endpoint/${aws_sagemaker_endpoint.informative_emotional_endpoint.name}/variant/primary"
#   scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
#   service_namespace  = "sagemaker"
# }

# resource "aws_appautoscaling_policy" "sagemaker_endpoint_scaling_policy" {
#   name               = "sagemaker-endpoint-scaling-policy"
#   policy_type        = "TargetTrackingScaling"
#   resource_id        = aws_appautoscaling_target.sagemaker_endpoint_target.resource_id
#   scalable_dimension = aws_appautoscaling_target.sagemaker_endpoint_target.scalable_dimension
#   service_namespace  = aws_appautoscaling_target.sagemaker_endpoint_target.service_namespace
# 
#   target_tracking_scaling_policy_configuration {
#     target_value = 70.0
#     
#     predefined_metric_specification {
#       predefined_metric_type = "SageMakerVariantInvocationsPerInstance"
#     }
# 
#     scale_out_cooldown = 300
#     scale_in_cooldown  = 300
#   }
# }

# CloudWatch Alarms for SageMaker Endpoint (DISABLED - endpoint disabled)
# resource "aws_cloudwatch_metric_alarm" "sagemaker_endpoint_invocation_errors" {
#   alarm_name          = "sagemaker-endpoint-invocation-errors"
#   comparison_operator = "GreaterThanThreshold"
#   evaluation_periods  = "2"
#   metric_name         = "ModelLatency"
#   namespace           = "AWS/SageMaker"
#   period              = "300"
#   statistic           = "Average"
#   threshold           = "10000"  # 10 seconds
#   alarm_description   = "This metric monitors SageMaker endpoint latency"
#   alarm_actions       = [aws_sns_topic.alerts.arn]
# 
#   dimensions = {
#     EndpointName = aws_sagemaker_endpoint.informative_emotional_endpoint.name
#     VariantName  = "primary"
#   }
# 
#   tags = {
#     Project   = "Alternative Consumer Sentiment Dashboard"
#     ManagedBy = "Terraform"
#   }
# }

# resource "aws_cloudwatch_metric_alarm" "sagemaker_endpoint_4xx_errors" {
#   alarm_name          = "sagemaker-endpoint-4xx-errors"
#   comparison_operator = "GreaterThanThreshold"
#   evaluation_periods  = "2"
#   metric_name         = "Invocation4XXErrors"
#   namespace           = "AWS/SageMaker"
#   period              = "300"
#   statistic           = "Sum"
#   threshold           = "5"
#   alarm_description   = "This metric monitors SageMaker endpoint 4XX errors"
#   alarm_actions       = [aws_sns_topic.alerts.arn]
# 
#   dimensions = {
#     EndpointName = aws_sagemaker_endpoint.informative_emotional_endpoint.name
#     VariantName  = "primary"
#   }
# 
#   tags = {
#     Project   = "Alternative Consumer Sentiment Dashboard"
#     ManagedBy = "Terraform"
#   }
# }