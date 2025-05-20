import os
import json
import boto3
import time
import hashlib
from datetime import datetime
from functools import wraps

logger = __import__('logging').getLogger(__name__)

s3_client = boto3.client("s3")
ssm_client = boto3.client("ssm")
secrets_client = boto3.client("secretsmanager")
bedrock_runtime = None
last_bedrock_call_time = 0
BEDROCK_CALL_INTERVAL = 1.0  # Minimum seconds between Bedrock calls

SSM_PARAMETER_NAME = "/reddit/last_post_timestamp"
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "sentiment-analyzer")
SUBREDDITS = os.environ.get("SUBREDDITS", "stocks,investing,wallstreetbets").split(',')
IGNORE_KEYWORDS = os.environ.get("IGNORE_KEYWORDS", "").split(',')
RAW_BUCKET_NAME = os.environ.get("RAW_BUCKET_NAME")
POST_LIMIT = int(os.environ.get("POST_LIMIT", 100))
MIN_POST_SCORE = int(os.environ.get("MIN_POST_SCORE", 10))
MIN_POST_LENGTH = int(os.environ.get("MIN_POST_LENGTH", 200))
MIN_COMMENT_SCORE = int(os.environ.get("MIN_COMMENT_SCORE", 5))
MIN_COMMENT_LENGTH = int(os.environ.get("MIN_COMMENT_LENGTH", 50))
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
ENABLE_AI_RELEVANCE_CHECK = os.environ.get("ENABLE_AI_RELEVANCE_CHECK", "true").lower() == "true"

reddit = None

def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=60.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        time.sleep(delay)
                    else:
                        raise last_exception
            return None
        return wrapper
    return decorator

def generate_content_hash(content):
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def safe_reddit_operation(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except Exception as e:
        logger.error(f"Reddit operation failed: {e}")
        raise

def validate_post_data(post_data):
    required_fields = ['type', 'id', 'subreddit', 'created_utc', 'score']
    return all(field in post_data for field in required_fields)

def sanitize_post_data(post_data):
    if 'title' in post_data:
        post_data['title'] = post_data['title'][:500]
    if 'selftext' in post_data:
        post_data['selftext'] = post_data['selftext'][:10000]
    if 'body' in post_data:
        post_data['body'] = post_data['body'][:5000]
    return post_data

def get_reddit_credentials():
    secret_name = os.environ.get("REDDIT_SECRET_NAME")
    if not secret_name:
        raise ValueError("REDDIT_SECRET_NAME environment variable not set.")
    
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    return secret['client_id'], secret['client_secret']

def initialize_bedrock_client():
    global bedrock_runtime
    if bedrock_runtime is None:
        try:
            bedrock_runtime = boto3.client(
                service_name='bedrock-runtime',
                region_name=BEDROCK_REGION
            )
            return bedrock_runtime
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {e}")
            return None
    return bedrock_runtime

@retry_with_backoff(max_retries=2, base_delay=0.5)
def get_last_timestamp():
    try:
        parameter = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
        timestamp = float(parameter['Parameter']['Value'])
        return timestamp
    except ssm_client.exceptions.ParameterNotFound:
        return None

@retry_with_backoff(max_retries=2, base_delay=0.5)
def set_last_timestamp(timestamp):
    ssm_client.put_parameter(
        Name=SSM_PARAMETER_NAME,
        Value=str(timestamp),
        Type='String',
        Overwrite=True
    )

@retry_with_backoff(max_retries=3, base_delay=2.0, max_delay=30.0)
def is_post_relevant_by_ai(post, bedrock_client):
    global last_bedrock_call_time
    
    if not post or not bedrock_client:
        return False
    
    if len(post.title + post.selftext) < 50:
        return False
    
    # Rate limiting: ensure minimum interval between calls
    current_time = time.time()
    time_since_last_call = current_time - last_bedrock_call_time
    if time_since_last_call < BEDROCK_CALL_INTERVAL:
        sleep_time = BEDROCK_CALL_INTERVAL - time_since_last_call
        time.sleep(sleep_time)
    
    last_bedrock_call_time = time.time()
    
    system_prompt = "You are a financial analyst specializing in equity research and investment analysis."
    
    user_prompt = f"""Analyze the following Reddit post to determine if it contains ANY financial or stock-related discussion.

Post Title: {post.title[:200]}
Post Content: {post.selftext[:800]}

Criteria for RELEVANT (be PERMISSIVE):
- ANY mention of stocks, companies, or investing
- Financial news or earnings discussion
- Market analysis or opinions
- Company updates or product discussions
- Investment ideas or stock picks
- Trading discussions
- Economic news or analysis

Criteria for IRRELEVANT (be RESTRICTIVE):
- Pure memes with no financial content
- Off-topic personal posts
- Non-financial technical discussions

Be generous with RELEVANT decisions. When in doubt, choose RELEVANT.

Respond with only a JSON object: {{"decision": "RELEVANT"}} or {{"decision": "IRRELEVANT"}}"""

    try:
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 50,
            "temperature": 0,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }
        
        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(request_body),
            contentType='application/json'
        )
        
        response_body = json.loads(response['body'].read())
        
        if 'content' in response_body and len(response_body['content']) > 0:
            content = response_body['content'][0]['text']
            
            try:
                decision_json = json.loads(content.strip())
                decision = decision_json.get('decision', '').upper()
                is_relevant = decision == 'RELEVANT'
                return is_relevant
            except json.JSONDecodeError:
                is_relevant = 'RELEVANT' in content.upper()
                return is_relevant
        else:
            return False
            
    except Exception as e:
        error_msg = str(e)
        if "You don't have access to the model" in error_msg:
            logger.error("Bedrock model access denied")
            return False
        elif "ThrottlingException" in error_msg or "Too many requests" in error_msg:
            logger.warning(f"Bedrock throttling detected: {e}")
            # Return True to be permissive when throttled rather than rejecting all posts
            return True
        elif "ValidationException" in error_msg:
            logger.error(f"Bedrock validation error: {e}")
            return False
        else:
            logger.error(f"Unexpected error in Bedrock relevance check: {e}")
            # Return True to be permissive on unknown errors
            return True

def lambda_handler(event, context):
    global reddit
    
    logger.info("Starting Reddit ingestion process...")
    
    # Debug logging setup
    import logging
    logging.basicConfig(level=logging.INFO)
    logger.setLevel(logging.INFO)
    
    try:
        if not reddit:
            client_id, client_secret = get_reddit_credentials()
            import praw
            reddit = praw.Reddit(
                client_id=client_id, client_secret=client_secret, user_agent=REDDIT_USER_AGENT
            )

        bedrock_client = initialize_bedrock_client()
        if bedrock_client:
            logger.info("Bedrock client initialized successfully")
        else:
            logger.warning("Bedrock client initialization failed - AI relevance checking will be disabled")

        KEYWORDS = os.environ.get("KEYWORDS", "AAPL,TSLA,AMZN,GOOGL,MSFT").split(',')

        last_timestamp = get_last_timestamp()
        processed_data = []
        newest_timestamp = 0
        
        # Debug logging
        if last_timestamp:
            last_dt = datetime.fromtimestamp(last_timestamp)
            logger.info(f"Last processed timestamp: {last_timestamp} ({last_dt})")
        else:
            logger.info("No previous timestamp found - processing all posts")
        
        logger.info(f"Keywords to search for: {KEYWORDS}")
        logger.info(f"Subreddits to process: {SUBREDDITS}")
        logger.info(f"Post limit: {POST_LIMIT}, Min score: {MIN_POST_SCORE}, Min length: {MIN_POST_LENGTH}")
        logger.info(f"AI relevance check enabled: {ENABLE_AI_RELEVANCE_CHECK}")
        
        # Quick fix: You can set ENABLE_AI_RELEVANCE_CHECK=false in Lambda environment to bypass AI filtering

        for sub_name in SUBREDDITS:
            logger.info(f"Processing subreddit: {sub_name}")
            try:
                subreddit = reddit.subreddit(sub_name)
                posts = safe_reddit_operation(subreddit.new, limit=POST_LIMIT)
                
                posts_examined = 0
                posts_after_timestamp = 0
                posts_with_keywords = 0
                posts_meeting_score = 0
                posts_meeting_length = 0
                posts_ai_relevant = 0
                
                for post in posts:
                    try:
                        posts_examined += 1
                        
                        if last_timestamp and post.created_utc < last_timestamp:
                            logger.debug(f"Skipping old post {post.id} (created: {datetime.fromtimestamp(post.created_utc)})")
                            continue
                        
                        posts_after_timestamp += 1
                        newest_timestamp = max(newest_timestamp, post.created_utc)
                        
                        logger.debug(f"Examining post {post.id}: '{post.title[:50]}...' (score: {post.score}, length: {len(post.selftext)})")
                        
                        post_text = (post.title + " " + post.selftext).lower()
                        
                        # Keyword check
                        has_keywords = any(keyword.lower() in post_text for keyword in KEYWORDS)
                        if not has_keywords:
                            logger.debug(f"Post {post.id} rejected: no matching keywords")
                            continue
                        posts_with_keywords += 1
                        
                        # Ignore keywords check
                        has_ignore_keywords = any(ikw.lower() in post_text for ikw in IGNORE_KEYWORDS if ikw)
                        if has_ignore_keywords:
                            logger.debug(f"Post {post.id} rejected: contains ignore keywords")
                            continue
                        
                        # Score check
                        if post.score < MIN_POST_SCORE:
                            logger.debug(f"Post {post.id} rejected: score {post.score} < {MIN_POST_SCORE}")
                            continue
                        posts_meeting_score += 1
                        
                        # Length check
                        if len(post.selftext) < MIN_POST_LENGTH:
                            logger.debug(f"Post {post.id} rejected: length {len(post.selftext)} < {MIN_POST_LENGTH}")
                            continue
                        posts_meeting_length += 1
                        
                        if ENABLE_AI_RELEVANCE_CHECK and bedrock_client:
                            ai_relevant = is_post_relevant_by_ai(post, bedrock_client)
                            if not ai_relevant:
                                logger.debug(f"Post {post.id} rejected: AI relevance check failed")
                                continue
                            posts_ai_relevant += 1
                            logger.debug(f"Post {post.id} passed AI relevance check")
                        elif ENABLE_AI_RELEVANCE_CHECK and not bedrock_client:
                            logger.warning("AI relevance check is enabled but Bedrock client is not available")
                        else:
                            posts_ai_relevant += 1

                        post_data = {
                            "type": "post",
                            "id": post.id,
                            "title": post.title,
                            "selftext": post.selftext,
                            "url": post.url,
                            "subreddit": sub_name,
                            "created_utc": post.created_utc,
                            "score": post.score,
                            "num_comments": post.num_comments,
                            "content_hash": generate_content_hash(post.title + post.selftext)
                        }
                        
                        if not validate_post_data(post_data):
                            continue
                        
                        post_data = sanitize_post_data(post_data)
                        processed_data.append(post_data)
                        
                        logger.info(f"Added post {post.id}: '{post.title[:50]}...' (score: {post.score})")
                        
                        try:
                            safe_reddit_operation(post.comments.replace_more, limit=0)
                            comments = safe_reddit_operation(post.comments.list)
                            
                            for comment in comments:
                                try:
                                    if comment.score < MIN_COMMENT_SCORE:
                                        continue
                                    if len(comment.body) < MIN_COMMENT_LENGTH:
                                        continue
                                    
                                    comment_data = {
                                        "type": "comment",
                                        "id": comment.id,
                                        "post_id": post.id,
                                        "body": comment.body,
                                        "url": comment.permalink,
                                        "subreddit": sub_name,
                                        "created_utc": comment.created_utc,
                                        "score": comment.score,
                                        "content_hash": generate_content_hash(comment.body)
                                    }
                                    
                                    if not validate_post_data(comment_data):
                                        continue
                                    
                                    comment_data = sanitize_post_data(comment_data)
                                    processed_data.append(comment_data)
                                    
                                except Exception as comment_error:
                                    continue
                        
                        except Exception as comments_error:
                            pass
                        
                        if len(processed_data) >= POST_LIMIT:
                            break
                            
                    except Exception as post_error:
                        continue
                
                # Log subreddit statistics
                logger.info(f"Subreddit {sub_name} stats:")
                logger.info(f"  - Posts examined: {posts_examined}")
                logger.info(f"  - Posts after timestamp: {posts_after_timestamp}")
                logger.info(f"  - Posts with keywords: {posts_with_keywords}")
                logger.info(f"  - Posts meeting score: {posts_meeting_score}")
                logger.info(f"  - Posts meeting length: {posts_meeting_length}")
                logger.info(f"  - Posts AI relevant: {posts_ai_relevant}")
                
                if len(processed_data) >= POST_LIMIT:
                    break

            except Exception as sub_error:
                logger.error(f"Error processing subreddit {sub_name}: {sub_error}")
                continue
        
        if not processed_data:
            logger.warning("No new data collected after processing all subreddits")
            return {"statusCode": 200, "body": "No new data."}
        
        logger.info(f"Total items collected: {len(processed_data)}")

        timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
        filename = f"{timestamp}.json"
        s3_key = f"reddit-posts/{filename}"

        try:
            data_with_metadata = {
                "metadata": {
                    "timestamp": timestamp,
                    "total_items": len(processed_data),
                    "processed_subreddits": SUBREDDITS,
                    "keywords": KEYWORDS
                },
                "data": processed_data
            }
            
            s3_client.put_object(
                Bucket=RAW_BUCKET_NAME, 
                Key=s3_key,
                Body=json.dumps(data_with_metadata, indent=2),
                ContentType="application/json"
            )
            
            if newest_timestamp > 0:
                new_dt = datetime.fromtimestamp(newest_timestamp)
                logger.info(f"Updating timestamp to: {newest_timestamp} ({new_dt})")
                set_last_timestamp(newest_timestamp)
            
            logger.info(f"Successfully uploaded data to S3: {s3_key}")
            return {
                "statusCode": 200,
                "body": f"Successfully processed {len(processed_data)} items"
            }
            
        except Exception as upload_error:
            logger.error(f"Failed to upload to S3: {upload_error}")
            return {"statusCode": 500, "body": f"Upload error: {upload_error}"}
    
    except Exception as e:
        logger.error(f"Lambda execution failed: {e}")
        return {"statusCode": 500, "body": f"Error: {e}"}