FROM python:3.13-alpine

WORKDIR /app

RUN pip install --upgrade pip

COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY ./app .

# Defines 1 worker
# Expose the app on port 80
CMD ["gunicorn", "--bind", "0.0.0.0:80", "app.main:app"]