import os
import json
import boto3
import csv
import io
from datetime import datetime
import urllib.parse

s3_client = boto3.client("s3")
athena_client = boto3.client("athena")

PROCESSED_BUCKET_NAME = os.environ.get("PROCESSED_BUCKET_NAME")
TRAINING_DATA_BUCKET = os.environ.get("TRAINING_DATA_BUCKET")
ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "altdata_sentiment_db")
ATHENA_OUTPUT_BUCKET = os.environ.get("ATHENA_OUTPUT_BUCKET")
MAX_POSTS_PER_EXTRACTION = int(os.environ.get("MAX_POSTS_PER_EXTRACTION", "1000"))

def lambda_handler(event, context):
    """
    Extract processed Reddit posts for training data labeling.
    This function can be triggered manually or on a schedule to collect posts for labeling.
    """
    try:
        # Get extraction parameters from event or use defaults
        limit = event.get("limit", MAX_POSTS_PER_EXTRACTION)
        min_score = event.get("min_score", 10)  # Minimum post score for quality
        min_length = event.get("min_length", 100)  # Minimum text length
        
        print(f"Starting data extraction: limit={limit}, min_score={min_score}, min_length={min_length}")
        
        # Query processed data using Athena
        query = f"""
        SELECT 
            id,
            title,
            body,
            subreddit,
            score,
            type,
            created_utc,
            sentiment.sentiment as sentiment_label,
            sentiment.sentimentscore.positive as sentiment_positive,
            sentiment.sentimentscore.negative as sentiment_negative,
            sentiment.sentimentscore.neutral as sentiment_neutral,
            sentiment.sentimentscore.mixed as sentiment_mixed
        FROM "{ATHENA_DATABASE}".reddit_posts
        WHERE score >= {min_score}
            AND (
                (type = 'post' AND LENGTH(title) >= {min_length})
                OR (type = 'comment' AND LENGTH(body) >= {min_length})
            )
            AND sentiment.sentiment IS NOT NULL
        ORDER BY score DESC, created_utc DESC
        LIMIT {limit}
        """
        
        # Execute Athena query
        query_execution_id = execute_athena_query(query)
        results = get_athena_results(query_execution_id)
        
        if not results:
            return {
                "statusCode": 200,
                "body": "No data found matching criteria"
            }
        
        # Convert to training data format
        training_data = prepare_training_data(results)
        
        # Generate unique filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"training_data/unlabeled_posts_{timestamp}.csv"
        
        # Upload to S3
        upload_training_data(training_data, filename)
        
        print(f"Successfully extracted {len(training_data)} posts to s3://{TRAINING_DATA_BUCKET}/{filename}")
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"Extracted {len(training_data)} posts for labeling",
                "s3_location": f"s3://{TRAINING_DATA_BUCKET}/{filename}",
                "filename": filename
            })
        }
        
    except Exception as e:
        print(f"Error in data extraction: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }

def execute_athena_query(query):
    """Execute Athena query and return execution ID"""
    response = athena_client.start_query_execution(
        QueryString=query,
        ResultConfiguration={
            'OutputLocation': f's3://{ATHENA_OUTPUT_BUCKET}/data_extraction/'
        },
        WorkGroup='primary'
    )
    return response['QueryExecutionId']

def get_athena_results(query_execution_id):
    """Wait for query completion and get results"""
    import time
    
    # Wait for query completion
    max_wait_time = 300  # 5 minutes
    wait_time = 0
    
    while wait_time < max_wait_time:
        response = athena_client.get_query_execution(QueryExecutionId=query_execution_id)
        status = response['QueryExecution']['Status']['State']
        
        if status in ['SUCCEEDED']:
            break
        elif status in ['FAILED', 'CANCELLED']:
            raise Exception(f"Athena query {status}: {response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')}")
        
        time.sleep(5)
        wait_time += 5
    
    if wait_time >= max_wait_time:
        raise Exception("Athena query timed out")
    
    # Get query results
    results = []
    response = athena_client.get_query_results(QueryExecutionId=query_execution_id)
    
    # Skip header row
    rows = response['ResultSet']['Rows'][1:]
    
    for row in rows:
        data = [col.get('VarCharValue', '') for col in row['Data']]
        results.append(data)
    
    return results

def prepare_training_data(athena_results):
    """Convert Athena results to training data format"""
    training_data = []
    
    for row in athena_results:
        try:
            post_id, title, body, subreddit, score, post_type, created_utc = row[:7]
            sentiment_data = row[7:11]  # sentiment label and scores
            
            # Determine the text to analyze
            if post_type == 'post':
                text = title or ""
            else:  # comment
                text = body or ""
            
            # Skip if no text
            if not text or len(text.strip()) < 50:
                continue
            
            # Clean and prepare text
            text = clean_text(text)
            
            # Create training data entry
            training_entry = {
                'id': post_id,
                'text': text,
                'subreddit': subreddit,
                'type': post_type,
                'score': score,
                'created_utc': created_utc,
                'existing_sentiment': sentiment_data[0] if sentiment_data[0] else 'UNKNOWN',
                'informative_emotional_label': '',  # To be filled during labeling
                'labeler': '',  # To be filled during labeling
                'labeling_notes': ''  # To be filled during labeling
            }
            
            training_data.append(training_entry)
            
        except Exception as e:
            print(f"Error processing row: {e}")
            continue
    
    return training_data

def clean_text(text):
    """Clean text for training data"""
    # Remove excessive whitespace
    text = ' '.join(text.split())
    
    # Remove or replace problematic characters
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    
    # Limit length for manageable labeling
    if len(text) > 1000:
        text = text[:1000] + "..."
    
    return text

def upload_training_data(training_data, filename):
    """Upload training data as CSV to S3"""
    if not training_data:
        raise Exception("No training data to upload")
    
    # Convert to CSV
    csv_buffer = io.StringIO()
    fieldnames = training_data[0].keys()
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
    
    writer.writeheader()
    for entry in training_data:
        writer.writerow(entry)
    
    # Upload to S3
    s3_client.put_object(
        Bucket=TRAINING_DATA_BUCKET,
        Key=filename,
        Body=csv_buffer.getvalue(),
        ContentType='text/csv'
    )