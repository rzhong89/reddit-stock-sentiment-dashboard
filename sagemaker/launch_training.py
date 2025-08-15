#!/usr/bin/env python3
"""
Launch SageMaker training job for informative/emotional classification
"""

import boto3
import sagemaker
from sagemaker.pytorch import PyTorch
from datetime import datetime
import os

# Configuration
TRAINING_DATA_S3_PATH = "s3://altdata-sagemaker-training-data/labeled/training_data_final.csv"
MODEL_OUTPUT_PATH = "s3://altdata-sagemaker-models/"
SAGEMAKER_ROLE = "arn:aws:iam::ACCOUNT_ID:role/sagemaker-informative-emotional-execution-role"

def get_account_id():
    """Get current AWS account ID"""
    sts = boto3.client('sts')
    return sts.get_caller_identity()['Account']

def launch_training():
    """Launch SageMaker training job"""
    
    # Get account ID and build role ARN
    account_id = get_account_id()
    role_arn = f"arn:aws:iam::{account_id}:role/sagemaker-informative-emotional-execution-role"
    
    print(f"Launching SageMaker training job...")
    print(f"Training data: {TRAINING_DATA_S3_PATH}")
    print(f"IAM Role: {role_arn}")
    
    # Initialize SageMaker session
    sagemaker_session = sagemaker.Session()
    
    # Create timestamp for job name
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    job_name = f"informative-emotional-{timestamp}"
    
    # Create PyTorch estimator
    estimator = PyTorch(
        entry_point='train.py',
        source_dir='./sagemaker',
        role=role_arn,
        instance_type='ml.m5.xlarge',  # Start with CPU instance
        instance_count=1,
        framework_version='1.12.0',
        py_version='py38',
        job_name=job_name,
        output_path=MODEL_OUTPUT_PATH,
        
        # Hyperparameters
        hyperparameters={
            'epochs': 3,
            'batch-size': 16,
            'learning-rate': '2e-5',
            'model-name': 'distilbert-base-uncased'
        },
        
        # Resource configuration
        volume_size=20,  # GB
        max_run=3600,    # 1 hour max
        
        # Enable network isolation for security
        enable_network_isolation=False,  # Needs internet for model download
        
        tags=[
            {'Key': 'Project', 'Value': 'Reddit-Sentiment-Analysis'},
            {'Key': 'Purpose', 'Value': 'Informative-Emotional-Classification'}
        ]
    )
    
    # Start training
    print(f"Starting training job: {job_name}")
    
    try:
        estimator.fit({
            'train': TRAINING_DATA_S3_PATH
        }, wait=False)  # Don't wait for completion
        
        print("Training job launched successfully!")
        print(f"Job name: {job_name}")
        print(f"Monitor progress:")
        print(f"   AWS Console: https://console.aws.amazon.com/sagemaker/home#/jobs")
        print(f"   CloudWatch Logs: /aws/sagemaker/TrainingJobs")
        print(f"\nTraining typically takes 30-90 minutes")
        print(f"Estimated cost: $2-5 for ml.m5.xlarge")
        
        return estimator, job_name
        
    except Exception as e:
        print(f"ERROR: Error launching training job: {e}")
        return None, None

def check_training_status(job_name):
    """Check status of training job"""
    sagemaker_client = boto3.client('sagemaker')
    
    try:
        response = sagemaker_client.describe_training_job(TrainingJobName=job_name)
        status = response['TrainingJobStatus']
        
        print(f"Training Job Status: {status}")
        
        if status == 'Completed':
            model_artifacts = response['ModelArtifacts']['S3ModelArtifacts']
            print(f"Training completed!")
            print(f"Model artifacts: {model_artifacts}")
            return model_artifacts
        elif status == 'Failed':
            failure_reason = response.get('FailureReason', 'Unknown error')
            print(f"Training failed: {failure_reason}")
        elif status in ['InProgress', 'Stopping']:
            print(f"Training is {status.lower()}...")
            
        return None
        
    except Exception as e:
        print(f"Error checking training status: {e}")
        return None

def main():
    print("SageMaker Training Job Launcher")
    print("=" * 50)
    
    # Verify training data exists
    print("Checking training data...")
    s3 = boto3.client('s3')
    
    try:
        # Parse S3 path
        bucket = TRAINING_DATA_S3_PATH.split('/')[2]
        key = '/'.join(TRAINING_DATA_S3_PATH.split('/')[3:])
        
        s3.head_object(Bucket=bucket, Key=key)
        print("Training data found")
        
    except Exception as e:
        print(f"Training data not found: {e}")
        print(f"Please upload your labeled data to: {TRAINING_DATA_S3_PATH}")
        print("   Use: aws s3 cp your_labeled_file.csv s3://altdata-sagemaker-training-data/labeled/training_data_final.csv")
        return
    
    # Launch training
    estimator, job_name = launch_training()
    
    if job_name:
        print(f"\nNext steps:")
        print(f"1. Monitor training job in AWS Console")
        print(f"2. Check logs: aws logs tail /aws/sagemaker/TrainingJobs/{job_name} --follow")
        print(f"3. Check status: python -c \"from launch_training import check_training_status; check_training_status('{job_name}')\"")
        print(f"4. After completion, uncomment SageMaker resources in terraform/sagemaker.tf")
        print(f"5. Update model artifact path and run terraform apply")

if __name__ == "__main__":
    main()