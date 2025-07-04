FROM python:3.12-alpine

RUN pip install --upgrade pip

RUN adduser -D nonroot
RUN mkdir /home/app/ && chown -R nonroot:nonroot /home/app
RUN mkdir -p /var/log/flask-app && touch /var/log/flask-app/flask-app.err.log && touch /var/log/flask-app/flask-app.out.log
RUN chown -R nonroot:nonroot /var/log/flask-app
WORKDIR /home/app
USER nonroot

COPY --chown=nonroot:nonroot ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY --chown=nonroot:nonroot . .

CMD ["gunicorn","-w", "4", "--bind", "0.0.0.0:80", "app:app"]