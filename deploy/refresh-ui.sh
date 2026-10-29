#!/bin/bash
# Runs ON the EC2 instance, as root: at first boot (from user data) and after every deploy (GitHub Actions -> SSM Run Command).
# Pulls the web files and the nginx template from S3, fills in the API Gateway address and key from SSM
# Parameter Store, and reloads nginx. Safe to run repeatedly.
set -euo pipefail
source /etc/scribbleai.env                       # BUCKET, REGION, PROJECT  (written by user data)
export AWS_DEFAULT_REGION="$REGION"

URL=$(aws ssm get-parameter --name "/$PROJECT/api_url" --query Parameter.Value --output text)
KEY=$(aws ssm get-parameter --name "/$PROJECT/api_key" --with-decryption --query Parameter.Value --output text)
HOST=${URL#https://}; HOST=${HOST%%/*}           # abc123.execute-api.ap-south-1.amazonaws.com
STAGE=${URL##*/}                                 # prod

aws s3 sync "s3://$BUCKET/ui/" /usr/share/nginx/html/ --delete --only-show-errors
aws s3 cp "s3://$BUCKET/deploy/nginx.conf.tpl" /tmp/nginx.conf.tpl --only-show-errors

umask 077                                        # the rendered file contains the API key
sed -e "s|__API_HOST__|$HOST|g" -e "s|__STAGE__|$STAGE|g" -e "s|__API_KEY__|$KEY|g" \
    /tmp/nginx.conf.tpl > /etc/nginx/nginx.conf.new
mv /etc/nginx/nginx.conf.new /etc/nginx/nginx.conf
rm -f /tmp/nginx.conf.tpl

nginx -t
systemctl reload nginx || systemctl restart nginx
echo "refreshed: $(ls /usr/share/nginx/html | tr '\n' ' ')-> https://$HOST/$STAGE"
