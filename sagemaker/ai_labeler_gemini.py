#!/usr/bin/env python3
"""
AI-Assisted Labeling using Google Gemini 2.5 Flash
This script uses Gemini API to pre-label Reddit posts as informative or emotional.
"""

import pandas as pd
import requests
import json
import time
import os
from datetime import datetime
import sys

# Configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def check_setup():
    """Check if API key is configured"""
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY environment variable not set!")
        print("\nTo set up:")
        print("1. Go to https://aistudio.google.com/app/apikey")
        print("2. Create a new API key")
        print("3. Set environment variable:")
        print("   Windows: set GEMINI_API_KEY=your_api_key_here")
        print("   PowerShell: $env:GEMINI_API_KEY='your_api_key_here'")
        print("   Linux/Mac: export GEMINI_API_KEY='your_api_key_here'")
        return False
    return True

def classify_with_gemini(text, retry_count=0):
    """Use Gemini 2.5 Flash to classify a Reddit post"""
    if retry_count > 3:
        return "error"
    
    # Truncate text to avoid token limits
    text = text[:800] if len(text) > 800 else text
    
    prompt = f"""You are a financial content classifier. Classify this Reddit post as either "informative" or "emotional".

INFORMATIVE posts contain:
- Factual information, news, earnings reports
- Market data, analysis, financial metrics  
- Company announcements, SEC filings
- Objective market observations
- Price movements with data/reasoning

EMOTIONAL posts contain:
- Personal opinions, feelings, reactions
- Excitement, frustration, hope, fear
- Memes, slang like "moon", "diamond hands", "YOLO"
- Personal trading experiences
- Subjective commentary without data

Post text: "{text}"

Respond with ONLY ONE WORD: either "informative" or "emotional" """

    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "topK": 1,
            "topP": 0.8
        },
        "safetySettings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_ONLY_HIGH"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH", 
                "threshold": "BLOCK_ONLY_HIGH"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_ONLY_HIGH"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_ONLY_HIGH"
            }
        ]
    }
    
    try:
        response = requests.post(
            f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # Debug: Print the response structure for troubleshooting
            if retry_count == 0:  # Only print on first try
                print(f"Debug - API Response: {result}")
            
            if 'candidates' in result and len(result['candidates']) > 0:
                candidate = result['candidates'][0]
                
                # Check if response was cut off due to MAX_TOKENS
                if candidate.get('finishReason') == 'MAX_TOKENS':
                    print(f"Response truncated due to MAX_TOKENS. Increase maxOutputTokens.")
                    return 'error'
                
                # Handle different response structures
                try:
                    if 'content' in candidate and 'parts' in candidate['content']:
                        content = candidate['content']['parts'][0]['text'].strip().lower()
                    elif 'text' in candidate:
                        content = candidate['text'].strip().lower()
                    elif 'output' in candidate:
                        content = candidate['output'].strip().lower()
                    else:
                        print(f"Unexpected candidate structure: {candidate}")
                        return 'error'
                    
                    # Clean up the response
                    if 'informative' in content:
                        return 'informative'
                    elif 'emotional' in content:
                        return 'emotional'
                    else:
                        print(f"Unexpected response content: {content}")
                        return 'unknown'
                        
                except KeyError as e:
                    print(f"KeyError accessing response: {e}")
                    print(f"Full candidate structure: {candidate}")
                    return 'error'
            else:
                print(f"No candidates in response: {result}")
                return 'error'
        else:
            print(f"API Error {response.status_code}: {response.text}")
            
            # Rate limiting - wait and retry
            if response.status_code == 429:
                print("Rate limited, waiting 60 seconds...")
                time.sleep(60)
                return classify_with_gemini(text, retry_count + 1)
            
            return 'error'
            
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        time.sleep(5)  # Wait before retry
        return classify_with_gemini(text, retry_count + 1)

def test_api():
    """Test API with a simple example"""
    print("Testing Gemini API...")
    test_result = classify_with_gemini("Apple reported strong earnings this quarter.")
    print(f"Test result: {test_result}")
    if test_result not in ['informative', 'emotional']:
        print("ERROR: API test failed. Check your API key and connection.")
        return False
    print("SUCCESS: API test successful!")
    return True

def main():
    if not check_setup():
        return
    
    if len(sys.argv) != 2:
        print("Usage: python ai_labeler_gemini.py <csv_file>")
        print("Example: python ai_labeler_gemini.py training_data.csv")
        return
    
    # Test API first
    if not test_api():
        return
    
    csv_file = sys.argv[1]
    
    try:
        df = pd.read_csv(csv_file)
        print(f"Loaded {len(df)} posts from {csv_file}")
    except Exception as e:
        print(f"ERROR: Error loading CSV: {e}")
        return
    
    # Find unlabeled posts
    unlabeled_mask = df['informative_emotional_label'].isna() | (df['informative_emotional_label'] == '')
    unlabeled_posts = df[unlabeled_mask]
    
    if len(unlabeled_posts) == 0:
        print("All posts are already labeled!")
        return
    
    print(f"Found {len(unlabeled_posts)} unlabeled posts")
    print("Starting AI labeling with Gemini 2.5 Flash...")
    print("Note: This may take several minutes depending on API rate limits")
    
    # Progress tracking
    start_time = datetime.now()
    labeled_count = 0
    error_count = 0
    
    # Create backup
    base_filename = os.path.basename(csv_file).replace('.csv', '')
    backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{base_filename}.csv"
    df.to_csv(backup_file, index=False)
    print(f"💾 Created backup: {backup_file}")
    
    for idx, row in unlabeled_posts.iterrows():
        if pd.isna(row['informative_emotional_label']) or row['informative_emotional_label'] == '':
            print(f"🔄 Labeling post {labeled_count + 1}/{len(unlabeled_posts)}: ", end="")
            
            # Get AI classification
            label = classify_with_gemini(row['text'])
            
            if label in ['informative', 'emotional']:
                df.at[idx, 'informative_emotional_label'] = label
                df.at[idx, 'labeler'] = 'gemini-2.5-flash'
                df.at[idx, 'labeling_notes'] = f'AI labeled on {datetime.now().strftime("%Y-%m-%d %H:%M")}'
                labeled_count += 1
                print(f"SUCCESS: {label}")
            else:
                df.at[idx, 'informative_emotional_label'] = 'needs_review'
                df.at[idx, 'labeler'] = 'gemini-error'
                error_count += 1
                print(f"ERROR: classification failed")
            
            # Save progress every 50 posts
            if labeled_count % 50 == 0 and labeled_count > 0:
                progress_file = f"progress_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{base_filename}.csv"
                df.to_csv(progress_file, index=False)
                print(f"Auto-saved progress: {progress_file}")
            
            # Rate limiting - be nice to the API
            time.sleep(1)  # 1 second between requests
    
    # Final save
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    final_file = f"ai_labeled_{timestamp}_{base_filename}.csv"
    df.to_csv(final_file, index=False)
    
    # Statistics
    end_time = datetime.now()
    duration = end_time - start_time
    
    print("\n" + "="*60)
    print("AI LABELING COMPLETE!")
    print("="*60)
    print(f"Total posts processed: {labeled_count + error_count}")
    print(f"Successfully labeled: {labeled_count}")
    print(f"Errors/needs review: {error_count}")
    print(f"Time taken: {duration}")
    print(f"Final file: {final_file}")
    
    # Show label distribution
    labeled_df = df[df['informative_emotional_label'].isin(['informative', 'emotional'])]
    if len(labeled_df) > 0:
        print(f"\nLabel Distribution:")
        label_counts = labeled_df['informative_emotional_label'].value_counts()
        for label, count in label_counts.items():
            percentage = (count / len(labeled_df)) * 100
            print(f"   {label}: {count} ({percentage:.1f}%)")
    
    print(f"\nNext steps:")
    print(f"   1. Review posts with 'needs_review' labels")
    print(f"   2. Spot-check some AI labels for accuracy")
    print(f"   3. Upload {final_file} to S3 for training")
    print(f"   4. Start SageMaker training job")

if __name__ == "__main__":
    main()