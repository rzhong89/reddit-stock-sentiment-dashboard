#!/usr/bin/env python3
"""
SageMaker Training Script for Informative vs Emotional Classification
This script trains a BERT-based model to classify Reddit posts as informative or emotional.
"""

import argparse
import logging
import os
import sys
import pandas as pd
import numpy as np
import pickle
import json
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, classification_report
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from transformers import (
    AutoTokenizer, 
    AutoModelForSequenceClassification,
    AdamW,
    get_linear_schedule_with_warmup
)
from tqdm import tqdm
import boto3

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RedditPostDataset(Dataset):
    """Dataset class for Reddit posts classification"""
    
    def __init__(self, texts, labels, tokenizer, max_length=512):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length
    
    def __len__(self):
        return len(self.texts)
    
    def __getitem__(self, idx):
        text = str(self.texts[idx])
        label = self.labels[idx]
        
        encoding = self.tokenizer(
            text,
            truncation=True,
            padding='max_length',
            max_length=self.max_length,
            return_tensors='pt'
        )
        
        return {
            'input_ids': encoding['input_ids'].flatten(),
            'attention_mask': encoding['attention_mask'].flatten(),
            'labels': torch.tensor(label, dtype=torch.long)
        }

class InformativeEmotionalClassifier:
    """Main classifier class"""
    
    def __init__(self, model_name='distilbert-base-uncased', num_classes=2):
        self.model_name = model_name
        self.num_classes = num_classes
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Initialize tokenizer and model
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_name, 
            num_labels=num_classes
        )
        self.model.to(self.device)
        
        # Label mapping
        self.label_map = {'informative': 0, 'emotional': 1}
        self.reverse_label_map = {0: 'informative', 1: 'emotional'}
    
    def prepare_data(self, data_path):
        """Load and prepare training data"""
        logger.info(f"Loading data from {data_path}")
        
        # Load CSV data
        df = pd.read_csv(data_path)
        
        # Filter out unlabeled data
        df = df[df['informative_emotional_label'].notna()]
        df = df[df['informative_emotional_label'].isin(['informative', 'emotional'])]
        
        if len(df) == 0:
            raise ValueError("No labeled data found in the dataset")
        
        logger.info(f"Loaded {len(df)} labeled examples")
        
        # Prepare features and labels
        texts = df['text'].tolist()
        labels = [self.label_map[label.lower().strip()] for label in df['informative_emotional_label']]
        
        # Split data
        train_texts, val_texts, train_labels, val_labels = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )
        
        logger.info(f"Training examples: {len(train_texts)}")
        logger.info(f"Validation examples: {len(val_texts)}")
        
        # Create datasets
        train_dataset = RedditPostDataset(train_texts, train_labels, self.tokenizer)
        val_dataset = RedditPostDataset(val_texts, val_labels, self.tokenizer)
        
        return train_dataset, val_dataset
    
    def train(self, train_dataset, val_dataset, epochs=3, batch_size=16, learning_rate=2e-5):
        """Train the model"""
        # Create data loaders
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=batch_size)
        
        # Setup optimizer and scheduler
        optimizer = AdamW(self.model.parameters(), lr=learning_rate)
        total_steps = len(train_loader) * epochs
        scheduler = get_linear_schedule_with_warmup(
            optimizer,
            num_warmup_steps=0,
            num_training_steps=total_steps
        )
        
        best_accuracy = 0
        
        for epoch in range(epochs):
            logger.info(f"Epoch {epoch + 1}/{epochs}")
            
            # Training phase
            self.model.train()
            total_loss = 0
            
            train_pbar = tqdm(train_loader, desc="Training")
            for batch in train_pbar:
                optimizer.zero_grad()
                
                input_ids = batch['input_ids'].to(self.device)
                attention_mask = batch['attention_mask'].to(self.device)
                labels = batch['labels'].to(self.device)
                
                outputs = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    labels=labels
                )
                
                loss = outputs.loss
                total_loss += loss.item()
                
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                
                train_pbar.set_postfix({'loss': loss.item()})
            
            avg_train_loss = total_loss / len(train_loader)
            
            # Validation phase
            val_accuracy = self.evaluate(val_loader)
            
            logger.info(f"Epoch {epoch + 1} - Train Loss: {avg_train_loss:.4f}, Val Accuracy: {val_accuracy:.4f}")
            
            # Save best model
            if val_accuracy > best_accuracy:
                best_accuracy = val_accuracy
                self.save_model('/opt/ml/model')
        
        logger.info(f"Training completed. Best validation accuracy: {best_accuracy:.4f}")
        return best_accuracy
    
    def evaluate(self, data_loader):
        """Evaluate the model"""
        self.model.eval()
        predictions = []
        actual_labels = []
        
        with torch.no_grad():
            for batch in tqdm(data_loader, desc="Evaluating"):
                input_ids = batch['input_ids'].to(self.device)
                attention_mask = batch['attention_mask'].to(self.device)
                labels = batch['labels'].to(self.device)
                
                outputs = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask
                )
                
                _, predicted = torch.max(outputs.logits, dim=1)
                predictions.extend(predicted.cpu().tolist())
                actual_labels.extend(labels.cpu().tolist())
        
        accuracy = accuracy_score(actual_labels, predictions)
        
        # Detailed classification report
        precision, recall, f1, _ = precision_recall_fscore_support(
            actual_labels, predictions, average='weighted'
        )
        
        logger.info(f"Accuracy: {accuracy:.4f}")
        logger.info(f"Precision: {precision:.4f}")
        logger.info(f"Recall: {recall:.4f}")
        logger.info(f"F1: {f1:.4f}")
        
        # Print classification report
        class_names = ['informative', 'emotional']
        report = classification_report(actual_labels, predictions, target_names=class_names)
        logger.info(f"Classification Report:\n{report}")
        
        return accuracy
    
    def save_model(self, model_dir):
        """Save model and tokenizer"""
        logger.info(f"Saving model to {model_dir}")
        
        # Save model and tokenizer
        self.model.save_pretrained(model_dir)
        self.tokenizer.save_pretrained(model_dir)
        
        # Save label mapping
        with open(os.path.join(model_dir, 'label_mapping.json'), 'w') as f:
            json.dump({
                'label_map': self.label_map,
                'reverse_label_map': self.reverse_label_map
            }, f)
        
        logger.info("Model saved successfully")

def main():
    """Main training function"""
    parser = argparse.ArgumentParser()
    
    # SageMaker arguments
    parser.add_argument('--model-dir', type=str, default=os.environ.get('SM_MODEL_DIR', '/opt/ml/model'))
    parser.add_argument('--train', type=str, default=os.environ.get('SM_CHANNEL_TRAIN', '/opt/ml/input/data/train'))
    parser.add_argument('--hosts', type=list, default=json.loads(os.environ.get('SM_HOSTS', '["localhost"]')))
    parser.add_argument('--current-host', type=str, default=os.environ.get('SM_CURRENT_HOST', 'localhost'))
    
    # Training arguments
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--learning-rate', type=float, default=2e-5)
    parser.add_argument('--model-name', type=str, default='distilbert-base-uncased')
    
    args = parser.parse_args()
    
    logger.info("Starting training job")
    logger.info(f"Arguments: {args}")
    
    # Initialize classifier
    classifier = InformativeEmotionalClassifier(model_name=args.model_name)
    
    # Find training data file
    train_files = [f for f in os.listdir(args.train) if f.endswith('.csv')]
    if not train_files:
        raise ValueError(f"No CSV files found in {args.train}")
    
    train_file = os.path.join(args.train, train_files[0])
    logger.info(f"Using training file: {train_file}")
    
    # Prepare data
    train_dataset, val_dataset = classifier.prepare_data(train_file)
    
    # Train model
    final_accuracy = classifier.train(
        train_dataset, 
        val_dataset,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate
    )
    
    # Log final results
    logger.info(f"Training completed with final accuracy: {final_accuracy:.4f}")
    
    # Save training metrics
    metrics = {
        'final_accuracy': final_accuracy,
        'epochs': args.epochs,
        'batch_size': args.batch_size,
        'learning_rate': args.learning_rate,
        'model_name': args.model_name
    }
    
    with open(os.path.join(args.model_dir, 'training_metrics.json'), 'w') as f:
        json.dump(metrics, f)

if __name__ == '__main__':
    main()