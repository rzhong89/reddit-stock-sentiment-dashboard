#!/usr/bin/env python3
"""
SageMaker Inference Script for Informative vs Emotional Classification
This script handles real-time inference for the trained BERT model.
"""

import json
import logging
import os
import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ModelHandler:
    """
    Custom model handler for SageMaker inference
    """
    
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.label_mapping = None
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"Using device: {self.device}")

def model_fn(model_dir):
    """
    Load the model and tokenizer from the model directory.
    This function is called once when the endpoint starts.
    """
    logger.info(f"Loading model from {model_dir}")
    
    try:
        # Load the tokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        
        # Load the model
        model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        model.eval()  # Set to evaluation mode
        
        # Move to appropriate device
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model.to(device)
        
        # Load label mapping
        label_mapping_path = os.path.join(model_dir, 'label_mapping.json')
        with open(label_mapping_path, 'r') as f:
            label_mapping = json.load(f)
        
        # Create model handler
        handler = ModelHandler()
        handler.model = model
        handler.tokenizer = tokenizer
        handler.label_mapping = label_mapping
        
        logger.info("Model loaded successfully")
        return handler
        
    except Exception as e:
        logger.error(f"Error loading model: {str(e)}")
        raise e

def input_fn(request_body, request_content_type):
    """
    Parse input data for inference.
    
    Args:
        request_body: The body of the request sent to the model.
        request_content_type: The content type of the request.
    
    Returns:
        Parsed input data
    """
    logger.info(f"Received content type: {request_content_type}")
    
    if request_content_type == 'application/json':
        input_data = json.loads(request_body)
        
        # Handle different input formats
        if isinstance(input_data, dict):
            if 'instances' in input_data:
                # Batch format: {"instances": [{"text": "..."}, {"text": "..."}]}
                texts = [instance.get('text', '') for instance in input_data['instances']]
            elif 'text' in input_data:
                # Single instance: {"text": "..."}
                texts = [input_data['text']]
            else:
                raise ValueError("Input must contain 'text' field or 'instances' array")
        elif isinstance(input_data, list):
            # List of texts: ["text1", "text2", ...]
            texts = input_data
        else:
            # Single text string
            texts = [str(input_data)]
        
        return texts
        
    elif request_content_type == 'text/plain':
        # Plain text input
        return [request_body]
    
    else:
        raise ValueError(f"Unsupported content type: {request_content_type}")

def predict_fn(input_data, model_handler):
    """
    Run inference on the input data.
    
    Args:
        input_data: List of texts to classify
        model_handler: The loaded model handler
    
    Returns:
        Predictions
    """
    logger.info(f"Running inference on {len(input_data)} texts")
    
    try:
        model = model_handler.model
        tokenizer = model_handler.tokenizer
        reverse_label_map = model_handler.label_mapping['reverse_label_map']
        
        # Convert string keys back to int keys
        reverse_label_map = {int(k): v for k, v in reverse_label_map.items()}
        
        predictions = []
        
        # Process each text
        with torch.no_grad():
            for text in input_data:
                # Tokenize input
                inputs = tokenizer(
                    text,
                    truncation=True,
                    padding='max_length',
                    max_length=512,
                    return_tensors='pt'
                )
                
                # Move to device
                inputs = {k: v.to(model_handler.device) for k, v in inputs.items()}
                
                # Run inference
                outputs = model(**inputs)
                logits = outputs.logits
                
                # Get prediction probabilities
                probabilities = torch.softmax(logits, dim=-1)
                predicted_class = torch.argmax(logits, dim=-1).item()
                confidence = probabilities[0][predicted_class].item()
                
                # Get all class probabilities
                class_probabilities = {
                    reverse_label_map[i]: prob.item() 
                    for i, prob in enumerate(probabilities[0])
                }
                
                prediction = {
                    'predicted_class': reverse_label_map[predicted_class],
                    'confidence': confidence,
                    'probabilities': class_probabilities
                }
                
                predictions.append(prediction)
        
        logger.info(f"Inference completed successfully")
        return predictions
        
    except Exception as e:
        logger.error(f"Error during inference: {str(e)}")
        raise e

def output_fn(prediction, accept):
    """
    Format the prediction output.
    
    Args:
        prediction: The prediction result
        accept: The content type that the client expects
    
    Returns:
        Formatted prediction output
    """
    logger.info(f"Formatting output for content type: {accept}")
    
    if accept == 'application/json':
        if len(prediction) == 1:
            # Single prediction
            return json.dumps(prediction[0])
        else:
            # Multiple predictions
            return json.dumps({
                'predictions': prediction
            })
    else:
        # Default to JSON
        return json.dumps(prediction)

# Health check function for SageMaker endpoints
def ping():
    """
    Health check endpoint for SageMaker
    """
    return '', 200

# Optional: Custom exception handler
def handle_error(error):
    """
    Custom error handler
    """
    logger.error(f"Inference error: {str(error)}")
    return {
        'error': str(error),
        'message': 'An error occurred during inference'
    }