output "altdata_raw_bucket_name" {
  description = "The name of the S3 bucket for raw data."
  value       = aws_s3_bucket.altdata_raw.bucket
}

output "altdata_processed_bucket_name" {
  description = "The name of the S3 bucket for processed data."
  value       = aws_s3_bucket.altdata_processed.bucket
}

output "website_url" {
  description = "The URL of the deployed static website dashboard."
  value       = aws_s3_bucket_website_configuration.frontend_website_config.website_endpoint
}

output "api_endpoint_url" {
  description = "The base URL of the deployed API Gateway."
  value       = aws_api_gateway_stage.prod.invoke_url
}

output "api_key_id" {
  description = "The ID of the API key for accessing the sentiment analysis API."
  value       = aws_api_gateway_api_key.sentiment_api_key.id
}

output "api_key_value" {
  description = "The value of the API key for accessing the sentiment analysis API."
  value       = aws_api_gateway_api_key.sentiment_api_key.value
  sensitive   = true
}