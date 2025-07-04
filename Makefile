venv:
	source .venv/bin/activate

build:
	docker build -t ai_request_handler:latest .

run:
	docker run -p 5000:80 ai_request_handler:latest