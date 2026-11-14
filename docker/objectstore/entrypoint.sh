#!/bin/sh
# SeaweedFS satu node dengan gateway S3 (ADR 0019). Identitas S3 dibuat dari variabel lingkungan,
# sehingga kredensial tidak ditulis di repository.
set -eu
mkdir -p /etc/seaweedfs /data
cat > /etc/seaweedfs/s3.json <<JSON
{"identities": [{"name": "ceteris",
  "credentials": [{"accessKey": "${S3_ACCESS_KEY}", "secretKey": "${S3_SECRET_KEY}"}],
  "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}
JSON
exec weed server -dir=/data -ip=objectstore -ip.bind=0.0.0.0 -volume.max=0 \
  -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json
