-- Dual Classification Analysis Query
-- This query analyzes Reddit posts by both sentiment (POSITIVE, NEGATIVE, NEUTRAL) 
-- and content type (INFORMATIVE, EMOTIONAL), providing comprehensive insights

SELECT
    subreddit,
    date(from_unixtime(created_utc)) AS post_date,
    sentiment.sentiment AS sentiment_type,
    content_type.classification AS content_type,
    COUNT(*) AS post_count,
    AVG(sentiment.sentimentscore.positive) AS avg_positive_score,
    AVG(sentiment.sentimentscore.negative) AS avg_negative_score,
    AVG(sentiment.sentimentscore.neutral) AS avg_neutral_score,
    AVG(content_type.confidence) AS avg_content_type_confidence
FROM
    "altdata_sentiment_db"."reddit_posts"
WHERE
    sentiment.sentiment IS NOT NULL
    AND content_type.classification IS NOT NULL
    AND content_type.classification != 'DISABLED'
    AND content_type.classification != 'UNKNOWN'
GROUP BY
    subreddit,
    date(from_unixtime(created_utc)),
    sentiment.sentiment,
    content_type.classification
ORDER BY
    post_date DESC,
    subreddit,
    post_count DESC;