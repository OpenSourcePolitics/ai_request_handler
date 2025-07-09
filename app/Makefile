venv:
	source .venv/bin/activate

build:
	docker buildx build --platform linux/amd64 -t ai_request_handler:0.0.1 .

run:
	docker run -e LANGFUSE_SECRET_KEY=$LANGFUSE_SECRET_KEY -e LANGFUSE_PUBLIC_KEY=$LANGFUSE_PUBLIC_KEY -e LANGFUSE_BASE_URL=$LANGFUSE_BASE_URL -e CLOUD_BASE_URL=$CLOUD_BASE_URL -e CLOUD_API_KEY=$CLOUD_API_KEY -e SCALEWAY_TOKEN=$SCALEWAY_TOKEN -p 5000:80 ai_request_handler:0.0.1
