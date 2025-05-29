import os
import json
import boto3
import urllib.parse
import logging
import time
import random

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3_client = boto3.client("s3")
comprehend_client = boto3.client("comprehend")
# Configure SageMaker client with longer timeouts for serverless endpoints
sagemaker_runtime = boto3.client(
    "sagemaker-runtime", 
    config=boto3.session.Config(
        read_timeout=120,  # 2 minutes for serverless cold start
        connect_timeout=60,  # 1 minute connection timeout
        retries={'max_attempts': 2}  # Retry once if timeout
    )
)

PROCESSED_BUCKET_NAME = os.environ.get("PROCESSED_BUCKET_NAME")
COMPREHEND_LANGUAGE = os.environ.get("COMPREHEND_LANGUAGE", "en")
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "informative-emotional-endpoint")
ENABLE_SAGEMAKER_CLASSIFICATION = os.environ.get("ENABLE_SAGEMAKER_CLASSIFICATION", "true").lower() == "true"

def lambda_handler(event, context):
    try:
        # Handle S3 event structure
        if 'Records' in event and event['Records']:
            bucket = event['Records'][0]['s3']['bucket']['name']
            key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
        else:
            # Handle direct invocation or test events
            print("Event structure:", json.dumps(event, default=str))
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'Invalid event structure. Expected S3 event with Records.',
                    'event': event
                })
            }
    except KeyError as e:
        print(f"KeyError parsing event: {e}")
        print("Event structure:", json.dumps(event, default=str))
        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': f'Missing required event field: {str(e)}',
                'event': event
            })
        }
    
    print(f"Processing file s3://{bucket}/{key}")

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        json_data = json.loads(response["Body"].read().decode("utf-8"))
        
        if isinstance(json_data, dict) and "data" in json_data:
            posts = json_data["data"]
        else:
            posts = json_data

        processed_items = []
        for item in posts:
            text_to_analyze = ""
            if item.get("type") == "post":
                text_to_analyze = item.get("title", "")
            elif item.get("type") == "comment":
                text_to_analyze = item.get("body", "")

            if not text_to_analyze:
                continue

            # AWS Comprehend sentiment analysis (existing functionality)
            sentiment_response = comprehend_client.detect_sentiment(
                Text=text_to_analyze,
                LanguageCode=COMPREHEND_LANGUAGE
            )

            item["sentiment"] = {
                "Sentiment": sentiment_response["Sentiment"],
                "SentimentScore": sentiment_response["SentimentScore"]
            }

            # SageMaker informative/emotional classification (new functionality)
            if ENABLE_SAGEMAKER_CLASSIFICATION:
                try:
                    content_type_result = classify_content_type(text_to_analyze)
                    item["content_type"] = content_type_result
                    logger.info(f"Content type classification: {content_type_result['Classification']} (confidence: {content_type_result['Confidence']:.3f})")
                except Exception as e:
                    logger.error(f"SageMaker classification failed: {str(e)}")
                    # Add fallback classification
                    item["content_type"] = {
                        "Classification": "UNKNOWN",
                        "Confidence": 0.0,
                        "Error": str(e)
                    }
            else:
                # SageMaker classification disabled
                item["content_type"] = {
                    "Classification": "DISABLED",
                    "Confidence": 0.0
                }

            processed_items.append(item)

        if not processed_items:
            print("No items to process.")
            return {"statusCode": 200, "body": "No items processed."}

        output_key = key  # Keep same path structure: reddit-posts/
        # Convert to newline-delimited JSON for Athena compatibility
        ndjson_content = '\n'.join(json.dumps(item) for item in processed_items)
        
        s3_client.put_object(
            Bucket=PROCESSED_BUCKET_NAME,
            Key=output_key,
            Body=ndjson_content,
            ContentType="application/json"
        )

        print(f"Successfully processed {len(processed_items)} items to s3://{PROCESSED_BUCKET_NAME}/{output_key}")
        return {"statusCode": 200, "body": f"Processed {len(processed_items)} items."}

    except Exception as e:
        logger.error(f"Error processing file: {e}")
        return {"statusCode": 500, "body": f"Error: {e}"}

def classify_content_type(text):
    """
    Classify text as informative or emotional using SageMaker endpoint.
    
    Args:
        text (str): Text to classify
    
    Returns:
        dict: Classification result with confidence score
    """
    try:
        # Prepare request payload
        payload = {
            "text": text
        }
        
        # Call SageMaker endpoint with increased timeout for serverless cold starts
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType="application/json",
            Body=json.dumps(payload),
            # No direct timeout parameter, but configure boto3 client timeout
        )
        
        # Parse response
        result = json.loads(response['Body'].read().decode('utf-8'))
        
        # Extract classification and confidence
        classification = result.get('predicted_class', 'UNKNOWN').upper()
        confidence = result.get('confidence', 0.0)
        probabilities = result.get('probabilities', {})
        
        return {
            "Classification": classification,
            "Confidence": confidence,
            "Probabilities": {
                "Informative": probabilities.get('informative', 0.0),
                "Emotional": probabilities.get('emotional', 0.0)
            }
        }
        
    except Exception as e:
        logger.error(f"SageMaker endpoint invocation failed: {str(e)}")
        raise e