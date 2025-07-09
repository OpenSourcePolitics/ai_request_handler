FROM python:3.12-alpine

WORKDIR /app

RUN pip install --upgrade pip

COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY . .

CMD ["gunicorn","-w", "4", "--bind", "0.0.0.0:80", "app:app"]