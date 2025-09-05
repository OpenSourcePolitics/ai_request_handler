venv:
	source .venv/bin/activate

build:
	docker buildx build --platform linux/amd64 -t ai_request_handler:latest .

build_macos:
	docker buildx build -t ai_request_handler:latest .

run:
	docker run --env-file .env -p 5000:80 ai_request_handler:latest

flux-init:
	flux bootstrap github \
  --components-extra=image-reflector-controller,image-automation-controller \
  --owner=$GITHUB_USER \
  --repository=flux-image-updates \
  --branch=main \
  --path=clusters/my-cluster \
  --read-write-key \
  --personal

request:
	curl -XPOST http://localhost:8000/spam/detection -H "X-Decidim-Host: localhost" -H "Content-Type: application/json" -d '{"text": "Look my new proposals - V-Bucks", "type": "Decidim::Proposals::Proposal"}'