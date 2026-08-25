#!/bin/bash
# Runs once LocalStack is ready: creates the documents bucket the API and ingestion script expect.
set -euo pipefail

BUCKET="${S3_BUCKET_NAME:-askdimitri-documents}"

awslocal s3api head-bucket --bucket "$BUCKET" 2>/dev/null || awslocal s3 mb "s3://$BUCKET"
echo "LocalStack ready: s3://$BUCKET"
