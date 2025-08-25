-- Content Type Trends Analysis
-- This query focuses specifically on informative vs emotional content trends

SELECT
    subreddit,
    date(from_unixtime(created_utc)) AS post_date,
    content_type.classification AS content_type,
    COUNT(*) AS post_count,
    AVG(content_type.confidence) AS avg_confidence,
    AVG(content_type.probabilities.informative) AS avg_informative_prob,
    AVG(content_type.probabilities.emotional) AS avg_emotional_prob,
    AVG(score) AS avg_post_score
FROM
    "altdata_sentiment_db"."reddit_posts"
WHERE
    content_type.classification IS NOT NULL
    AND content_type.classification IN ('INFORMATIVE', 'EMOTIONAL')
    AND content_type.confidence >= 0.7  -- Only high-confidence classifications
GROUP BY
    subreddit,
    date(from_unixtime(created_utc)),
    content_type.classification
ORDER BY
    post_date DESC,
    subreddit,
    post_count DESC;