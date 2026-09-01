# GridLens Web Deployment

This guide covers three paths:

1. local testing on a development machine
2. local or GitHub Pages frontend against an EC2 API
3. publishing the frontend on GitHub Pages while EC2 runs the API and GridPACK

The instructions below assume the repository lives at `/Users/hannah/Documents/GridLens` locally and `/home/ubuntu/GridLens` on Ubuntu EC2.

## 1. Local Test Against A Local API

Use this path when you want both the frontend and API running on the same machine.

### Backend

```bash
cd /Users/hannah/Documents/GridLens
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[web]"
export GRIDLENS_API_HOST=127.0.0.1
export GRIDLENS_API_PORT=8000
export GRIDLENS_API_CORS_ORIGINS=http://localhost:5173
export GRIDLENS_API_PROJECTS_ROOT="$HOME/GridLensWebProjects"
gridlens-api
```

Verify the API:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/projects
```

### Frontend

Open a second terminal:

```bash
cd /Users/hannah/Documents/GridLens/webapp
npm install
npm run dev
```

Open:

- `http://localhost:5173`

In local mode, Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`.

### What To Test Locally

1. Create a project with a `.raw` file and any optional support files such as `.csv`, `.con`, `.mon`, or an existing `.xml`.
2. Open the `XML Configuration` panel and generate `input.xml`.
3. Start a run.
4. Open `Run Details` and confirm the log updates.
5. Use `Export Run ZIP`.
6. Download at least one individual output file.
7. Generate the interactive analysis charts.

## 2. Local Frontend Against The EC2 API

Use this path when GridPACK and Docker should run on EC2 but you still want to test the frontend from your own machine.

### Backend On EC2

```bash
cd /home/ubuntu/GridLens
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[web]"
export GRIDLENS_API_HOST=0.0.0.0
export GRIDLENS_API_PORT=8000
export GRIDLENS_API_CORS_ORIGINS=http://localhost:5173
export GRIDLENS_API_PROJECTS_ROOT=/home/ubuntu/GridLensWebProjects
gridlens-api
```

Verify on EC2:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/projects
```

Make sure the EC2 security group allows inbound `TCP 8000` from your IP while testing.

### Frontend On Your Local Machine

Create `webapp/.env.local`:

```env
VITE_GRIDLENS_API_BASE_URL=http://3.18.103.82:8000
```

Then run:

```bash
cd /Users/hannah/Documents/GridLens/webapp
npm install
npm run dev
```

Open:

- `http://localhost:5173`

## 3. Frontend On GitHub Pages, API On EC2

This is the recommended public architecture:

- GitHub Pages hosts the static React frontend
- EC2 runs the GridLens FastAPI backend and GridPACK Docker jobs
- Amazon Cognito handles email-and-password authentication
- the API stores each authenticated user under a private per-user folder on EC2

### Backend Environment On EC2

Add these environment variables to the API service:

```ini
Environment=GRIDLENS_API_HOST=0.0.0.0
Environment=GRIDLENS_API_PORT=8000
Environment=GRIDLENS_API_PROJECTS_ROOT=/home/ubuntu/GridLensWebProjects
Environment=GRIDLENS_API_CORS_ORIGINS=https://<github-username>.github.io
Environment=GRIDLENS_AUTH_MODE=cognito
Environment=GRIDLENS_COGNITO_REGION=<aws-region>
Environment=GRIDLENS_COGNITO_USER_POOL_ID=<user-pool-id>
Environment=GRIDLENS_COGNITO_CLIENT_ID=<app-client-id>
```

If your GitHub Pages site is repo-scoped, use the full Pages origin such as:

```ini
Environment=GRIDLENS_API_CORS_ORIGINS=https://<github-username>.github.io
```

### Frontend Repository Variables For GitHub Actions

Set these repository variables in GitHub:

```text
VITE_GRIDLENS_API_BASE_URL=http://3.18.103.82:8000
VITE_GRIDLENS_AUTH_MODE=cognito
VITE_GRIDLENS_COGNITO_DOMAIN=https://<your-domain>.auth.<region>.amazoncognito.com
VITE_GRIDLENS_COGNITO_CLIENT_ID=<app-client-id>
VITE_PUBLIC_BASE_PATH=/<repo-name>/
```

Use `VITE_PUBLIC_BASE_PATH=/` only if you later attach a custom domain.

### Cognito Configuration

In the Cognito app client:

1. Enable the authorization code grant.
2. Enable a hosted UI domain.
3. Add your GitHub Pages URL as an allowed callback URL.
4. Add your GitHub Pages URL as an allowed sign-out URL.
5. Use email as the sign-in identifier.

### GitHub Pages Workflow

This repository now includes:

- [`.github/workflows/github-pages.yml`](/Users/hannah/Documents/GridLens/.github/workflows/github-pages.yml)

Enable `Pages -> Build and deployment -> Source: GitHub Actions`, then push to `main`.

## 4. Can It Be Published Now?

Yes. The repository now has the pieces needed for a working hosted web app:

- FastAPI backend for project creation, XML generation, run launch, log polling, output listing, file download, ZIP export, and interactive analysis
- React frontend that talks to the API
- production frontend build via `npm run build`

The main remaining work is operational:

- keep the API alive with `systemd`
- serve the frontend build with `nginx`
- reverse-proxy `/api` to the backend
- add DNS and HTTPS
- optionally add authentication before broad public access

## 5. Publish On EC2

This is the simplest deployment shape for now:

- one EC2 instance runs the API and GridPACK
- `nginx` serves the frontend static files
- `nginx` proxies `/api` to `127.0.0.1:8000`

### Build The Frontend

If you build on your local machine, create `webapp/.env.production` with:

```env
VITE_GRIDLENS_API_BASE_URL=/api
```

Then build:

```bash
cd /Users/hannah/Documents/GridLens/webapp
npm install
npm run build
```

Copy `webapp/dist` to the EC2 host, or build directly on EC2.

### Install Runtime Packages On EC2

```bash
sudo apt update
sudo apt install -y nginx python3.10 python3.10-venv python3-pip docker.io
sudo systemctl enable --now docker
sudo systemctl enable --now nginx
```

### Prepare The App On EC2

```bash
cd /home/ubuntu/GridLens
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[web]"
mkdir -p /home/ubuntu/GridLensWebProjects
```

### Create The API Service

Create `/etc/systemd/system/gridlens-api.service`:

```ini
[Unit]
Description=GridLens FastAPI service
After=network.target docker.service
Requires=docker.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/GridLens
Environment=GRIDLENS_API_HOST=127.0.0.1
Environment=GRIDLENS_API_PORT=8000
Environment=GRIDLENS_API_PROJECTS_ROOT=/home/ubuntu/GridLensWebProjects
ExecStart=/home/ubuntu/GridLens/.venv/bin/python -m gridlens.webapi.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gridlens-api
sudo systemctl status gridlens-api
```

To protect the API with Cognito in this EC2-served mode, add:

```ini
Environment=GRIDLENS_AUTH_MODE=cognito
Environment=GRIDLENS_COGNITO_REGION=<aws-region>
Environment=GRIDLENS_COGNITO_USER_POOL_ID=<user-pool-id>
Environment=GRIDLENS_COGNITO_CLIENT_ID=<app-client-id>
```

### Publish The Frontend With Nginx

Copy the built frontend to a web directory:

```bash
sudo mkdir -p /var/www/gridlens
sudo cp -r /home/ubuntu/GridLens/webapp/dist/* /var/www/gridlens/
```

Create `/etc/nginx/sites-available/gridlens` for the initial HTTP-only setup:

```nginx
server {
    listen 80;
    server_name 3.18.103.82;

    root /var/www/gridlens;
    index index.html;

    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it:

```bash
sudo ln -sf /etc/nginx/sites-available/gridlens /etc/nginx/sites-enabled/gridlens
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Then open:

- `http://3.18.103.82`

## 5. Add Basic Auth, HTTPS, And Rate Limiting

This is the recommended protection layer for the current internal deployment.

### Prerequisite: Use A Real Domain Name

HTTPS with Let's Encrypt works best with a real DNS name such as:

- `gridlens.example.com`
- `internal-gridlens.example.org`

Point your domain's `A` record to:

- `3.18.103.82`

Update the `server_name` in the nginx config before requesting the certificate.

### Step 1: Install Certbot And htpasswd Tools

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx apache2-utils
```

### Step 2: Create A Basic Auth User

Create the password file and your first user:

```bash
sudo htpasswd -c /etc/nginx/.htpasswd gridlensadmin
```

If you need to add more users later:

```bash
sudo htpasswd /etc/nginx/.htpasswd anotheruser
```

### Step 3: Add Rate Limiting And Basic Auth To Nginx

Edit `/etc/nginx/sites-available/gridlens` to use your real domain and add auth plus rate limiting:

```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    listen 80;
    server_name gridlens.example.com;

    root /var/www/gridlens;
    index index.html;

    auth_basic "GridLens";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
    }

    location /health {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:8000/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Check and reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Step 4: Request The HTTPS Certificate

Run certbot:

```bash
sudo certbot --nginx -d gridlens.example.com
```

Choose the redirect-to-HTTPS option when prompted.

After certbot finishes, nginx will be updated to listen on `443` with the certificate paths added automatically.

### Step 5: Confirm HTTPS And Authentication

Open:

- `https://gridlens.example.com`

You should see:

1. a browser username/password prompt
2. the GridLens app after successful login
3. HTTPS enabled with a valid certificate

You can also verify from the EC2 host:

```bash
curl -I https://gridlens.example.com
```

### Step 6: Tighten The Security Group

Once nginx is serving the app and proxying the API, your EC2 security group should allow:

- `TCP 22` from your admin IP only
- `TCP 80` from `0.0.0.0/0`
- `TCP 443` from `0.0.0.0/0`

Remove public access to:

- `TCP 8000`

The FastAPI service should remain bound to:

- `127.0.0.1:8000`

### Notes On Rate Limiting

The example above uses:

- `rate=10r/s`
- `burst=20`

That is a reasonable starting point for an internal tool. If legitimate users trigger too many API requests while browsing logs or refreshing results, raise the burst first before raising the sustained rate.

For very long-running requests, nginx rate limiting only controls request frequency. It does not limit how much compute GridPACK jobs consume once the API accepts them. For that, add job queueing or run-concurrency limits later.

### Optional Hardening

For a slightly safer internal release, also add:

1. upload size limits in nginx with `client_max_body_size`
2. log rotation for nginx and GridLens API logs
3. fail2ban or AWS WAF later if the site becomes more broadly exposed

Example upload limit:

```nginx
client_max_body_size 500m;
```

Add that inside the `server` block if your RAW files are large.

### Security Group

For a published web app, allow:

- `TCP 80` from `0.0.0.0/0`
- `TCP 443` from `0.0.0.0/0`
- `TCP 22` from your admin IP

Do not leave `TCP 8000` publicly open once `nginx` is proxying requests.

## 6. Recommended Next Production Steps

Before broad public rollout, add:

1. authentication
2. rate limiting
3. background job queueing if you expect many simultaneous runs
4. HTTPS with a real domain
5. persistent monitoring and log rotation

For a small internal launch, the single-EC2 + nginx + FastAPI setup is enough to publish now.
