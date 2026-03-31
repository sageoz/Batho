# Batho Webhook Setup Guide

This guide explains how to set up and run the Batho webhook server for real-time code graph updates.

## Overview

The Batho webhook server receives GitHub and GitLab webhook events and automatically updates the code graph using incremental patching. This enables continuous, real-time analysis without manual re-indexing.

## Quick Start

### 1. Configure Webhook

Copy the example configuration:
```bash
cp batho.yaml.example batho.yaml
```

Edit `./batho.yaml`:
```yaml
webhook:
  enabled: true
  server:
    host: "0.0.0.0"
    port: 8080
  repository:
    name: "your-username/your-repo"
    platform: "github"
    secret: "${WEBHOOK_SECRET}"  # Set as environment variable
    branches: ["main", "develop"]
```

### 2. Set Environment Variables

```bash
export WEBHOOK_SECRET="your-secret-key"
```

### 3. Start Webhook Server

```bash
batho webhook-server --root /path/to/repo
```

The server will start and listen for webhook events at:
- Webhook endpoint: `http://0.0.0.0:8080/webhook`
- Health check: `http://0.0.0.0:8080/health`

### 4. Configure GitHub/GitLab

#### GitHub

1. Go to your repository settings
2. Navigate to Webhooks
3. Add new webhook:
   - Payload URL: `http://your-server:8080/webhook`
   - Content type: `application/json`
   - Secret: Same as `WEBHOOK_SECRET`
   - Events: Pushes, Pull requests

#### GitLab

1. Go to your project settings
2. Navigate to Webhooks
3. Add new webhook:
   - URL: `http://your-server:8080/webhook`
   - Secret Token: Same as `WEBHOOK_SECRET`
   - Trigger events: Push events, Merge request events

## Configuration Options

### Server Configuration

```yaml
webhook:
  server:
    host: "0.0.0.0"        # Server bind address
    port: 8080             # Server port
    workers: 4             # Number of worker threads
```

### Repository Configuration

```yaml
webhook:
  repository:
    name: "user/repo"      # Repository name
    platform: "github"     # "github" or "gitlab"
    secret: "${SECRET}"    # Webhook secret (use env var)
    branches: ["main"]     # Branches to watch
    path: "/path/to/repo"  # Optional repo path
```

### Processing Configuration

```yaml
webhook:
  processing:
    queue_backend: "celery"              # "celery" or "sync"
    celery_broker_url: "memory://"       # Default local broker
    celery_result_backend: "cache+memory://"
    task_always_eager: true               # Local execution mode
    batch_size: 100                # Batch size for processing
    timeout_seconds: 300           # Processing timeout
    retry_attempts: 3
```

### Rate Limiting

```yaml
webhook:
  rate_limit:
    requests_per_hour: 100         # Global baseline limit
    burst_size: 10                 # Burst capacity
```

### Logging

```yaml
webhook:
  logging:
    level: "INFO"           # Log level
    file: "webhook.log"     # Optional log file
```

## How It Works

1. **Webhook Reception**: Server receives webhook from GitHub/GitLab
2. **Authentication**: Verifies signature/token
3. **Event Parsing**: Extracts file changes from payload
4. **Queueing**: Adds event to processing queue
5. **Processing**: Applies changes using incremental patching
6. **Snapshot Creation**: Creates new snapshot on success

## Monitoring

### Health Check

Check server status:
```bash
curl http://localhost:8080/health
```

Response:
```json
{
  "status": "healthy",
  "queue_stats": {
    "queue_size": 0,
    "dead_letter_size": 0,
    "processing": 1
  }
}
```

### Logs

The server logs all webhook processing:
- Webhook received
- Authentication success/failure
- Processing status
- Errors and retries

## Security Considerations

1. **Always use HTTPS** in production
2. **Set strong secrets** for webhook verification
3. **Restrict IP access** if possible
4. **Monitor logs** for suspicious activity
5. **Regularly rotate secrets**

## Troubleshooting

### Webhook Not Triggering

1. Check server is running: `curl http://localhost:8080/health`
2. Verify webhook URL is accessible from GitHub/GitLab
3. Check secret matches in both configurations
4. Review server logs for errors

### Processing Failures

1. Check repository path is correct
2. Ensure Batho has been run at least once: `batho index`
3. Verify file permissions
4. Check queue stats in health endpoint

### High Memory Usage

1. Switch to sync mode if async queueing is unnecessary: `queue_backend: "sync"`
2. Adjust batch size downward
3. Monitor queue size and processing rate

## Advanced Usage

### Using Celery Queue

Install optional dependencies:
```bash
pip install "batho[webhooks]"
```

Configure:
```yaml
webhook:
  processing:
    queue_backend: "celery"
    celery_broker_url: "memory://"
    celery_result_backend: "cache+memory://"
    task_always_eager: true
```

### Multiple Repositories

Run separate server instances for each repository with different configurations.

### Docker Deployment

```dockerfile
FROM python:3.11
COPY . /app
WORKDIR /app
RUN pip install -e .
EXPOSE 8080
CMD ["batho", "webhook-server"]
```

## Integration with CI/CD

### GitHub Actions

```yaml
name: Notify Batho
on:
  push:
    branches: [main]
jobs:
  webhook:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Trigger webhook
        run: |
          curl -X POST \
            -H "Content-Type: application/json" \
            -H "X-Hub-Signature-256: ${{ signature }}" \
            -d '${{ github.event }}' \
            ${{ secrets.WEBHOOK_URL }}
```

## API Reference

### Endpoints

- `POST /webhook` - Receive webhook events
- `GET /health` - Health check and statistics

### Event Types Supported

#### GitHub
- `push` - Code pushed to repository
- `pull_request` - PR opened, updated, or closed

#### GitLab
- `Push Hook` - Code pushed to repository
- `Merge Request Hook` - MR opened, updated, or closed

### Response Codes

- `202` - Webhook accepted for processing
- `200` - Webhook ignored (e.g., unwatched branch)
- `400` - Bad request or processing error
- `401` - Authentication failed
- `404` - Endpoint not found
- `500` - Internal server error
