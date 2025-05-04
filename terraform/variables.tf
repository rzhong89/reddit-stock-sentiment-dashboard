variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  default     = "us-east-1"
}

variable "raw_bucket_name" {
  description = "The name of the S3 bucket for raw data."
  type        = string
  default     = "altdata-raw-sentiment-dashboard"
}

variable "processed_bucket_name" {
  description = "The name of the S3 bucket for processed data."
  type        = string
  default     = "altdata-processed-sentiment-dashboard"
}

variable "reddit_secret_name" {
  description = "The name of the secret in AWS Secrets Manager holding the Reddit API credentials."
  type        = string
  default     = "RedditAPISecret"
}

variable "athena_results_bucket_name" {
  description = "The name of the S3 bucket for Athena query results."
  type        = string
  default     = "altdata-athena-query-results"
}

variable "ingestion_enabled" {
  description = "Set to false to disable the CloudWatch trigger and pause the ingestion pipeline."
  type        = bool
  default     = true
}

# Company list update variables (DISABLED)
# Uncomment these if you want to enable the company list update feature
/*
variable "config_bucket_name" {
  description = "The name of the S3 bucket for storing configuration files like the company list."
  type        = string
  default     = "altdata-config-sentiment-dashboard"
}

variable "fmp_api_secret_name" {
  description = "The name of the secret in AWS Secrets Manager holding the FMP API key."
  type        = string
  default     = "FMP_API_Key"
}
*/


variable "alert_email" {
  description = "Email address to receive CloudWatch alerts"
  type        = string
  default     = "admin@example.com"
}

variable "keywords" {
  description = "Comma-separated list of stock ticker keywords to search for"
  type        = string
  default     = "AAPL,MSFT,GOOGL,AMZN,TSLA,NVDA,META,BRK.B,JNJ,JPM,NFLX,V,PYPL,DIS,BAC,XOM,WMT,PFE,CSCO,CVX,ORCL,INTC,ADBE,CRM,CMCSA,KO,T,ABNB,AMD,PLTR,UBER"
}

variable "training_data_bucket_name" {
  description = "The name of the S3 bucket for SageMaker training data."
  type        = string
  default     = "altdata-sagemaker-training-data"
}

variable "sagemaker_model_bucket_name" {
  description = "The name of the S3 bucket for SageMaker model artifacts."
  type        = string
  default     = "altdata-sagemaker-models"
}