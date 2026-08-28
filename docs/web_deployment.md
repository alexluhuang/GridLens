# GridLens Web Deployment

This guide covers two paths:

1. local testing on a development machine
2. publishing the web app on an EC2 host that also runs the GridLens API

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

## 3. Can It Be Published Now?

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

## 4. Publish On EC2

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

### Publish The Frontend With Nginx

Copy the built frontend to a web directory:

```bash
sudo mkdir -p /var/www/gridlens
sudo cp -r /home/ubuntu/GridLens/webapp/dist/* /var/www/gridlens/
```

Create `/etc/nginx/sites-available/gridlens`:

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

### Security Group

For a published web app, allow:

- `TCP 80` from `0.0.0.0/0`
- `TCP 443` from `0.0.0.0/0` once HTTPS is added
- `TCP 22` from your admin IP

Do not leave `TCP 8000` publicly open once `nginx` is proxying requests.

## 5. Recommended Next Production Steps

Before broad public rollout, add:

1. authentication
2. rate limiting
3. background job queueing if you expect many simultaneous runs
4. HTTPS with a real domain
5. persistent monitoring and log rotation

For a small internal launch, the single-EC2 + nginx + FastAPI setup is enough to publish now.
