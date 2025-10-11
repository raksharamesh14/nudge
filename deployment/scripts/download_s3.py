#!/usr/bin/env python3
"""
Simple S3 download script.
Downloads all files from S3 bucket and organizes them in the root path.
"""

import os
import boto3
from pathlib import Path

def download_from_s3():
    """Download all files from S3 bucket to local directory."""
    
    # Get configuration from environment variables
    bucket_name = os.getenv('MODEL_S3_BUCKET', 'nudgedaily')
    s3_prefix = os.getenv('MODEL_S3_PREFIX', 'models/')
    local_dir = os.getenv('MODEL_LOCAL_DIR', '/home/app/models/smart-turn-v2')
    
    print(f"📥 Downloading from S3 bucket: {bucket_name}")
    print(f"📁 Local directory: {local_dir}")
    print(f"💡 Note: This maps to /opt/nudge/models/smart-turn-v2 on the host")
    
    # Create local directory
    Path(local_dir).mkdir(parents=True, exist_ok=True)
    
    # Initialize S3 client
    s3_client = boto3.client('s3')
    
    # Download all files
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix)
    
    for page in pages:
        if 'Contents' in page:
            for obj in page['Contents']:
                s3_key = obj['Key']
                local_file_path = Path(local_dir) / Path(s3_key).name
                
                print(f"📥 Downloading: {s3_key} -> {local_file_path}")
                s3_client.download_file(bucket_name, s3_key, str(local_file_path))
    
    print("✅ Download complete!")
    
    # Set environment variable for the application
    os.environ['SMART_TURN_MODEL_PATH'] = local_dir
    print(f"🔧 Set SMART_TURN_MODEL_PATH={local_dir}")

if __name__ == "__main__":
    download_from_s3()
