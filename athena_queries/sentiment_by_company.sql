-- This query calculates the count of each sentiment type (POSITIVE, NEGATIVE, NEUTRAL)
-- for each subreddit, grouped by day. This is useful for tracking sentiment trends over time.

-- Note: Replace 'altdata_sentiment_db' and 'reddit_posts' with your actual
-- database and table names if they differ.

SELECT
    subreddit,
    date(from_unixtime(created_utc)) AS post_date,
    sentiment.sentiment AS sentiment_type,
    COUNT(*) AS post_count
FROM
    "altdata_sentiment_db"."reddit_posts"
GROUP BY
    subreddit,
    date(from_unixtime(created_utc)),
    sentiment.sentiment
ORDER BY
    post_date DESC,
    subreddit,
    post_count DESC;