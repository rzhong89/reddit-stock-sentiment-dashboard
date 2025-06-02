import os
import json
import boto3
import time
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

athena_client = boto3.client('athena')
s3_client = boto3.client('s3')

ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "altdata_sentiment_db")
ATHENA_TABLE = os.environ.get("ATHENA_TABLE", "reddit_posts")
ATHENA_OUTPUT_BUCKET = os.environ.get("ATHENA_OUTPUT_BUCKET")
KEYWORDS = os.environ.get("KEYWORDS")

VALID_CONTENT_TYPES = {'all', 'posts', 'comments'}
MAX_TICKER_LENGTH = 10
TICKER_PATTERN = re.compile(r'^[A-Z]{1,10}$')
ALLOWED_ORIGINS = [
    'http://localhost:3000', 
    'https://altdata-sentiment-dashboard-website.s3-website-us-east-1.amazonaws.com',
    'http://altdata-sentiment-dashboard-website.s3-website-us-east-1.amazonaws.com'
] 

def validate_ticker(ticker):
    if not ticker or ticker == 'ALL':
        return True
    
    if len(ticker) > MAX_TICKER_LENGTH:
        return False
        
    return bool(TICKER_PATTERN.match(ticker.upper()))

def validate_content_type(content_type):
    return content_type in VALID_CONTENT_TYPES

def sanitize_input(input_str):
    if not input_str:
        return ""
    
    sanitized = re.sub(r'[\'";\\-]', '', input_str)
    return sanitized.strip()

def get_cors_headers(origin):
    allowed_origin = '*'
    
    if origin in ALLOWED_ORIGINS:
        allowed_origin = origin
    
    return {
        'Access-Control-Allow-Origin': allowed_origin,
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Api-Key',
        'Content-Type': 'application/json'
    }

def lambda_handler(event, context):
    logger.info(f"Received event: {event}")

    origin = event.get('headers', {}).get('origin', '')
    cors_headers = get_cors_headers(origin)

    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': ''
        }
    
    # Handle tickers request via query parameter
    query_params = event.get('queryStringParameters') or {}
    if query_params.get('action') == 'tickers':
        return handle_tickers_endpoint(cors_headers)

    try:
        ticker = query_params.get('ticker', 'ALL')
        content_type = query_params.get('type', 'all')
        
        if not validate_ticker(ticker):
            logger.warning(f"Invalid ticker format: {ticker}")
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Invalid ticker format. Use 1-10 uppercase letters.'})
            }
        
        if not validate_content_type(content_type):
            logger.warning(f"Invalid content type: {content_type}")
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': 'Invalid content type. Use: all, posts, or comments.'})
            }
        
        ticker = sanitize_input(ticker.upper()) if ticker != 'ALL' else 'ALL'
        content_type = sanitize_input(content_type.lower())
        
        logger.info(f"Querying data for ticker: {ticker}, type: {content_type}")

        where_conditions = ["1=1"]
        
        if ticker != 'ALL':
            where_conditions.append(f"(UPPER(title) LIKE UPPER('%{ticker}%') OR UPPER(selftext) LIKE UPPER('%{ticker}%'))")

        if content_type == 'posts':
            where_conditions.append("type = 'post'")
        elif content_type == 'comments':
            where_conditions.append("type = 'comment'")
        
        where_clause = " AND ".join(where_conditions)

        trend_query = f"""
            SELECT date(from_unixtime(created_utc)) AS post_date, sentiment.sentiment AS sentiment_type, COUNT(*) as post_count
            FROM {ATHENA_TABLE} WHERE {where_clause}
            GROUP BY 1, 2 ORDER BY 1 DESC
        """

        posts_query = f"""
            SELECT
                CASE
                    WHEN type = 'post' THEN title
                    WHEN type = 'comment' THEN body
                END AS display_text,
                subreddit, sentiment.sentiment AS sentiment_type, url, type
            FROM {ATHENA_TABLE} WHERE {where_clause}
            ORDER BY created_utc DESC LIMIT 20
        """

        logger.info("Executing trend data query...")
        trend_results = execute_athena_query(trend_query)
        
        logger.info("Executing posts data query...")
        posts_results = execute_athena_query(posts_query)

        final_response = {
            "trend_data": trend_results,
            "posts_data": posts_results,
            "metadata": {
                "ticker": ticker,
                "content_type": content_type,
                "timestamp": int(time.time())
            }
        }

        logger.info(f"Successfully processed query for ticker: {ticker}, type: {content_type}")
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps(final_response)
        }

    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        return {
            'statusCode': 400,
            'headers': cors_headers,
            'body': json.dumps({'error': f"Validation error: {str(ve)}"})
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Internal server error. Please try again later.'})
        }

def execute_athena_query(query):
    if not query.strip():
        raise ValueError("Query cannot be empty")
        
    logger.info(f"Executing Athena query: {query[:100]}...")
    
    try:
        response = athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': ATHENA_DATABASE},
            ResultConfiguration={'OutputLocation': f's3://{ATHENA_OUTPUT_BUCKET}/query-results/'}
        )
        query_execution_id = response['QueryExecutionId']
        logger.info(f"Started query execution with ID: {query_execution_id}")

        max_wait_time = 60
        wait_time = 0
        while wait_time < max_wait_time:
            stats = athena_client.get_query_execution(QueryExecutionId=query_execution_id)
            status = stats['QueryExecution']['Status']['State']
            
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                break
                
            time.sleep(1)
            wait_time += 1

        if wait_time >= max_wait_time:
            raise Exception(f"Athena query timed out after {max_wait_time} seconds")

        if status != 'SUCCEEDED':
            error_reason = stats['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
            logger.error(f"Athena query failed: {error_reason}")
            raise Exception(f"Athena query failed: {error_reason}")

        result_key = f"query-results/{query_execution_id}.csv"
        logger.info(f"Fetching results from S3: {result_key}")
        
        result_response = s3_client.get_object(Bucket=ATHENA_OUTPUT_BUCKET, Key=result_key)
        result_data = result_response['Body'].read().decode('utf-8').splitlines()

        if not result_data:
            logger.warning("Query returned no data")
            return []
            
        headers = [h.strip('"') for h in result_data[0].split(',')]
        parsed_results = []
        
        for i, row in enumerate(result_data[1:], 1):
            if not row.strip():
                continue
                
            try:
                values = [v.strip('"') for v in row.split(',')]
                if len(values) == len(headers):
                    parsed_results.append(dict(zip(headers, values)))
                else:
                    logger.warning(f"Row {i} has {len(values)} values but {len(headers)} headers expected")
            except Exception as row_error:
                logger.warning(f"Error parsing row {i}: {row_error}")
                continue
        
        logger.info(f"Successfully parsed {len(parsed_results)} rows from Athena results")
        return parsed_results
        
    except Exception as e:
        logger.error(f"Error executing Athena query: {e}")
        raise

def handle_tickers_endpoint(cors_headers):
    try:
        # Get tickers from environment variable (set in AWS Lambda console)
        if not KEYWORDS:
            # Return fallback tickers with a warning
            tickers_list = ['AAPL', 'TSLA', 'AMZN', 'GOOGL', 'MSFT']
            response = {
                "tickers": tickers_list,
                "metadata": {
                    "source": "fallback_default",
                    "timestamp": int(time.time()),
                    "count": len(tickers_list),
                    "warning": "KEYWORDS environment variable not set, using fallback"
                }
            }
        else:
            tickers_list = [ticker.strip() for ticker in KEYWORDS.split(',') if ticker.strip()]
            response = {
                "tickers": tickers_list,
                "metadata": {
                    "source": "lambda_environment",
                    "timestamp": int(time.time()),
                    "count": len(tickers_list)
                }
            }
        
        logger.info(f"Returning {len(tickers_list)} tickers: {tickers_list}")
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps(response)
        }
        
    except Exception as e:
        logger.error(f"Error in tickers endpoint: {e}")
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Failed to retrieve tickers'})
        }