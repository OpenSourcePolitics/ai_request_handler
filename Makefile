venv:
	source .venv/bin/activate

build:
	docker build -t ai_request_handler:0.0.1 .

run:
	docker run -p 5000:80 ai_request_handler:0.0.1