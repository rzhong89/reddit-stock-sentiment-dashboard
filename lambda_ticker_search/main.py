import os
import json
import boto3
import requests
from datetime import datetime, timedelta
import re
import time

# --- AWS Clients ---
s3_client = boto3.client("s3")
secrets_client = boto3.client("secretsmanager")
comprehend_client = boto3.client("comprehend")

# --- Configuration ---
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "sentiment-analyzer by /u/your-username")
SUBREDDITS = ["stocks", "investing", "wallstreetbets", "SecurityAnalysis", "ValueInvesting"]
IGNORE_KEYWORDS = ["yolo", "gain", "loss", "portfolio", "bought", "sold", "trade"]
COMPREHEND_LANGUAGE = "en"

# Filter settings
MIN_POST_SCORE = 5
MIN_POST_LENGTH = 100
MIN_COMMENT_SCORE = 3
MIN_COMMENT_LENGTH = 30
POST_LIMIT = 50

# Rate limiting in-memory storage (simple approach)
request_counts = {}

# --- Helper Functions ---

def validate_ticker(ticker):
    """Validate ticker format"""
    if not ticker or not isinstance(ticker, str):
        return False
    
    # Remove whitespace and convert to uppercase
    ticker = ticker.strip().upper()
    
    # Check if it's 1-5 uppercase letters
    if not re.match(r'^[A-Z]{1,5}$', ticker):
        return False
    
    return ticker

def get_timeframe_hours(timeframe):
    """Convert timeframe string to hours"""
    timeframe_map = {
        '1h': 1,
        '6h': 6,
        '12h': 12,
        '24h': 24,
        '2d': 48,
        '7d': 168,
        '30d': 720
    }
    return timeframe_map.get(timeframe, 24)  # Default to 24 hours

def check_rate_limit(ip_address):
    """Simple rate limiting - 10 requests per hour per IP"""
    current_time = time.time()
    hour_ago = current_time - 3600  # 1 hour ago
    
    if ip_address not in request_counts:
        request_counts[ip_address] = []
    
    # Remove old requests
    request_counts[ip_address] = [req_time for req_time in request_counts[ip_address] if req_time > hour_ago]
    
    # Check if limit exceeded
    if len(request_counts[ip_address]) >= 10:
        return False
    
    # Add current request
    request_counts[ip_address].append(current_time)
    return True

def get_reddit_credentials():
    """Retrieves Reddit credentials from AWS Secrets Manager"""
    secret_name = os.environ.get("REDDIT_SECRET_NAME")
    if not secret_name:
        raise ValueError("REDDIT_SECRET_NAME environment variable not set")
    
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    return secret['client_id'], secret['client_secret']

def search_reddit_posts(reddit, ticker, hours_back):
    """Search Reddit for posts containing the ticker"""
    cutoff_time = time.time() - (hours_back * 3600)
    found_posts = []
    
    for sub_name in SUBREDDITS:
        try:
            subreddit = reddit.subreddit(sub_name)
            
            # Search recent posts
            for post in subreddit.new(limit=200):
                if post.created_utc < cutoff_time:
                    continue
                
                # Check if post contains ticker
                post_text = (post.title + " " + post.selftext).lower()
                if ticker.lower() not in post_text:
                    continue
                
                # Apply filters
                if any(kw.lower() in post_text for kw in IGNORE_KEYWORDS):
                    continue
                if post.score < MIN_POST_SCORE:
                    continue
                if len(post.selftext) < MIN_POST_LENGTH:
                    continue
                
                # Add post
                found_posts.append({
                    "type": "post",
                    "id": post.id,
                    "title": post.title,
                    "selftext": post.selftext,
                    "url": post.url,
                    "subreddit": sub_name,
                    "created_utc": post.created_utc,
                    "score": post.score,
                    "num_comments": post.num_comments
                })
                
                # Add comments
                try:
                    post.comments.replace_more(limit=0)
                    for comment in post.comments.list()[:10]:  # Limit comments per post
                        if comment.score < MIN_COMMENT_SCORE:
                            continue
                        if len(comment.body) < MIN_COMMENT_LENGTH:
                            continue
                        
                        found_posts.append({
                            "type": "comment",
                            "id": comment.id,
                            "post_id": post.id,
                            "body": comment.body,
                            "subreddit": sub_name,
                            "created_utc": comment.created_utc,
                            "score": comment.score
                        })
                except:
                    # Skip comments if there's an error
                    continue
                
                if len(found_posts) >= POST_LIMIT:
                    break
            
            if len(found_posts) >= POST_LIMIT:
                break
                
        except Exception as e:
            print(f"Error searching subreddit {sub_name}: {e}")
            continue
    
    return found_posts

def analyze_sentiment(items):
    """Analyze sentiment for all items"""
    analyzed_items = []
    
    for item in items:
        try:
            # Get text to analyze
            text_to_analyze = ""
            if item.get("type") == "post":
                text_to_analyze = item.get("title", "") + " " + item.get("selftext", "")
            elif item.get("type") == "comment":
                text_to_analyze = item.get("body", "")
            
            if not text_to_analyze.strip():
                continue
            
            # Truncate text if too long (Comprehend has limits)
            if len(text_to_analyze) > 5000:
                text_to_analyze = text_to_analyze[:5000]
            
            # Analyze sentiment
            sentiment_response = comprehend_client.detect_sentiment(
                Text=text_to_analyze,
                LanguageCode=COMPREHEND_LANGUAGE
            )
            
            # Add sentiment to item
            item["sentiment"] = {
                "Sentiment": sentiment_response["Sentiment"],
                "SentimentScore": sentiment_response["SentimentScore"]
            }
            
            analyzed_items.append(item)
            
        except Exception as e:
            print(f"Error analyzing sentiment for item {item.get('id')}: {e}")
            # Add item without sentiment
            analyzed_items.append(item)
    
    return analyzed_items

def calculate_summary_stats(items):
    """Calculate summary statistics"""
    if not items:
        return {
            "total_items": 0,
            "posts": 0,
            "comments": 0,
            "sentiment_breakdown": {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0, "MIXED": 0},
            "average_score": 0,
            "timeframe_coverage": "No data"
        }
    
    posts = [item for item in items if item.get("type") == "post"]
    comments = [item for item in items if item.get("type") == "comment"]
    
    # Sentiment breakdown
    sentiment_counts = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0, "MIXED": 0}
    for item in items:
        if "sentiment" in item:
            sentiment = item["sentiment"]["Sentiment"]
            sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
    
    # Average score
    scores = [item.get("score", 0) for item in items]
    avg_score = sum(scores) / len(scores) if scores else 0
    
    # Time coverage
    timestamps = [item.get("created_utc", 0) for item in items]
    if timestamps:
        oldest = min(timestamps)
        newest = max(timestamps)
        hours_span = (newest - oldest) / 3600
        timeframe_coverage = f"{hours_span:.1f} hours"
    else:
        timeframe_coverage = "No data"
    
    return {
        "total_items": len(items),
        "posts": len(posts),
        "comments": len(comments),
        "sentiment_breakdown": sentiment_counts,
        "average_score": round(avg_score, 2),
        "timeframe_coverage": timeframe_coverage
    }

def lambda_handler(event, context):
    """Main Lambda handler for on-demand ticker search"""
    
    try:
        # Get client IP for rate limiting
        client_ip = event.get('requestContext', {}).get('identity', {}).get('sourceIp', 'unknown')
        
        # Check rate limit
        if not check_rate_limit(client_ip):
            return {
                'statusCode': 429,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type',
                    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
                },
                'body': json.dumps({
                    'error': 'Rate limit exceeded. Maximum 10 requests per hour.'
                })
            }
        
        # Get parameters
        query_params = event.get('queryStringParameters') or {}
        ticker = query_params.get('ticker')
        timeframe = query_params.get('timeframe', '24h')
        
        # Validate ticker
        validated_ticker = validate_ticker(ticker)
        if not validated_ticker:
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type',
                    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
                },
                'body': json.dumps({
                    'error': 'Invalid ticker format. Please provide a valid stock ticker (e.g., AAPL, TSLA).'
                })
            }
        
        # Get timeframe in hours
        hours_back = get_timeframe_hours(timeframe)
        
        print(f"Searching for ticker: {validated_ticker}, timeframe: {timeframe} ({hours_back} hours)")
        
        # Initialize Reddit client
        client_id, client_secret = get_reddit_credentials()
        import praw
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=REDDIT_USER_AGENT
        )
        
        # Search Reddit posts
        posts = search_reddit_posts(reddit, validated_ticker, hours_back)
        
        if not posts:
            return {
                'statusCode': 200,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type',
                    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
                },
                'body': json.dumps({
                    'ticker': validated_ticker,
                    'timeframe': timeframe,
                    'message': 'No relevant posts found for this ticker in the specified timeframe.',
                    'data': [],
                    'summary': calculate_summary_stats([])
                })
            }
        
        # Analyze sentiment
        analyzed_posts = analyze_sentiment(posts)
        
        # Calculate summary statistics
        summary = calculate_summary_stats(analyzed_posts)
        
        # Return results
        return {
            'statusCode': 200,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
            },
            'body': json.dumps({
                'ticker': validated_ticker,
                'timeframe': timeframe,
                'timestamp': datetime.utcnow().isoformat(),
                'summary': summary,
                'data': analyzed_posts[:20]  # Return first 20 items to limit response size
            })
        }
        
    except Exception as e:
        print(f"Error in lambda_handler: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS'
            },
            'body': json.dumps({
                'error': f'Internal server error: {str(e)}'
            })
        }