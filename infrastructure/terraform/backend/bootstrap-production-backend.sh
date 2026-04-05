#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
BUCKET="${TF_BACKEND_BUCKET:-quantgambit-terraform-state}"
TABLE="${TF_LOCK_TABLE:-quantgambit-terraform-locks}"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

require aws

echo "Ensuring S3 backend bucket exists: ${BUCKET} (${REGION})"
if ! aws s3api head-bucket --bucket "${BUCKET}" >/dev/null 2>&1; then
  aws s3api create-bucket \
    --bucket "${BUCKET}" \
    --region "${REGION}" \
    --create-bucket-configuration "LocationConstraint=${REGION}"
fi

aws s3api put-bucket-versioning \
  --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket "${BUCKET}" \
  --server-side-encryption-configuration '{
    "Rules": [
      {
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        }
      }
    ]
  }'

echo "Ensuring DynamoDB lock table exists: ${TABLE} (${REGION})"
if ! aws dynamodb describe-table --table-name "${TABLE}" --region "${REGION}" >/dev/null 2>&1; then
  aws dynamodb create-table \
    --table-name "${TABLE}" \
    --region "${REGION}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
  aws dynamodb wait table-exists --table-name "${TABLE}" --region "${REGION}"
fi

echo "Backend bootstrap complete."
echo "Bucket: ${BUCKET}"
echo "Lock table: ${TABLE}"
