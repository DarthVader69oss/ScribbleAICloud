# nginx on the EC2 front end. deploy/refresh-ui.sh fills in the three __PLACEHOLDERS__ from SSM Parameter Store.
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;

events {
    worker_connections 256;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log /var/log/nginx/access.log;
    sendfile on;
    server_tokens off;
    client_max_body_size 2m;
    gzip on;
    gzip_types text/css application/javascript application/json;

    # Second line of defence behind API Gateway's own throttling: 10 requests/s per client address.
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_status 429;

    server {
        listen 80 default_server;
        server_name _;
        root /usr/share/nginx/html;
        index index.html;

        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy no-referrer always;

        # Load-balancer / uptime style check that does not touch the API.
        location = /healthz {
            access_log off;
            default_type text/plain;
            return 200 "ok\n";
        }

        location = /dashboard {
            return 302 /dashboard.html;
        }

        location / {
            add_header Cache-Control "no-cache";
            add_header X-Content-Type-Options nosniff always;
            add_header Referrer-Policy no-referrer always;
            try_files $uri $uri/ =404;
        }

        # Browser: /api/recognize  ->  API Gateway: https://<id>.execute-api.<region>.amazonaws.com/<stage>/predict
        # The API key is added here, on the server, so it is never sent to (or visible in) a browser.
        location ~ ^/api/(recognize|info|stats|health)$ {
            limit_req zone=api burst=20 nodelay;
            rewrite ^/api/recognize$ /__STAGE__/predict break;
            rewrite ^/api/(.*)$ /__STAGE__/$1 break;
            proxy_pass https://__API_HOST__;
            proxy_http_version 1.1;
            proxy_ssl_server_name on;
            proxy_set_header Host __API_HOST__;
            proxy_set_header x-api-key __API_KEY__;
            proxy_set_header Connection "";
            proxy_read_timeout 35s;
            add_header Cache-Control "no-store";
        }

        location /api/ {
            return 404;
        }
    }
}
