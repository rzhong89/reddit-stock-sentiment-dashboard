-- Combined Sentiment and Content Type Analysis for Company Mentions
-- This query provides detailed analysis of posts mentioning specific companies
-- with both sentiment and informative/emotional classification

-- Example usage: Replace 'AAPL' with any ticker symbol you want to analyze
WITH company_posts AS (
    SELECT *
    FROM "altdata_sentiment_db"."reddit_posts"
    WHERE (
        UPPER(title) LIKE '%AAPL%' OR 
        UPPER(title) LIKE '%APPLE%' OR
        UPPER(body) LIKE '%AAPL%' OR 
        UPPER(body) LIKE '%APPLE%'
    )
    AND sentiment.sentiment IS NOT NULL
    AND content_type.classification IS NOT NULL
    AND content_type.classification != 'DISABLED'
)

SELECT
    'AAPL' AS ticker,
    date(from_unixtime(created_utc)) AS post_date,
    sentiment.sentiment AS sentiment_type,
    content_type.classification AS content_type,
    COUNT(*) AS post_count,
    AVG(score) AS avg_post_score,
    AVG(sentiment.sentimentscore.positive) AS avg_positive_sentiment,
    AVG(sentiment.sentimentscore.negative) AS avg_negative_sentiment,
    AVG(content_type.confidence) AS avg_content_confidence,
    -- Calculate combined metrics
    CASE 
        WHEN sentiment.sentiment = 'POSITIVE' AND content_type.classification = 'INFORMATIVE' THEN 'POSITIVE_INFORMATIVE'
        WHEN sentiment.sentiment = 'POSITIVE' AND content_type.classification = 'EMOTIONAL' THEN 'POSITIVE_EMOTIONAL'
        WHEN sentiment.sentiment = 'NEGATIVE' AND content_type.classification = 'INFORMATIVE' THEN 'NEGATIVE_INFORMATIVE'
        WHEN sentiment.sentiment = 'NEGATIVE' AND content_type.classification = 'EMOTIONAL' THEN 'NEGATIVE_EMOTIONAL'
        WHEN sentiment.sentiment = 'NEUTRAL' AND content_type.classification = 'INFORMATIVE' THEN 'NEUTRAL_INFORMATIVE'
        WHEN sentiment.sentiment = 'NEUTRAL' AND content_type.classification = 'EMOTIONAL' THEN 'NEUTRAL_EMOTIONAL'
        ELSE 'MIXED_OTHER'
    END AS combined_classification
FROM company_posts
GROUP BY
    date(from_unixtime(created_utc)),
    sentiment.sentiment,
    content_type.classification
ORDER BY
    post_date DESC,
    post_count DESC;