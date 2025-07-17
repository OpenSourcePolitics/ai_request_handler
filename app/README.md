# ai\_request\_handler

## Installation

1. Load environment variables:

   ```bash
   source .env
   ```
2. Create and activate a virtual environment:

   ```bash
   make venv
   source .venv/bin/activate
   ```

## Configuration

Copy `.env.example` to `.env` and fill in the following variables:

```dotenv
# Langfuse SDK keys and endpoint
LANGFUSE_SECRET_KEY=<your_secret_key>
LANGFUSE_PUBLIC_KEY=<your_public_key>
LANGFUSE_BASE_URL=<langfuse_sdk_url>

# OpenAI (Cloud) API endpoint and key
CLOUD_BASE_URL=<openai_api_url>
CLOUD_API_KEY=<your_api_key>

# ScaleWay token (optional)
SCALEWAY_TOKEN=<your_scaleway_token>

# Logging level: DEBUG, INFO, or WARN (default: WARN)
LANGFUSE_LOG_LEVEL=INFO
```

## Usage

### Local with Makefile

* **Build** the Docker image:

  ```bash
  make build
  ```

* **Run** the container:

  ```bash
  make run
  ```

The service will be available at `http://localhost:5000/`.

* **Test** the `/spam/detection` endpoint:

  ```bash
  curl -i \
    -X POST \
    -H "Content-Type: application/json" \
    -H "X-Decidim-Host: example.com" \
    -H "X-Host: example.com" \
    -d '{"text":"Hello, this is a test spam message.","type":"Decidim::Comments::Comment"}' \
    http://localhost:5000/spam/detection
  ```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
