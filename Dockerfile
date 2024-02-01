FROM python:3.12-slim-bookworm

WORKDIR /mediafusion

# Create a non-root user
RUN useradd -m mediafusion
RUN chown -R mediafusion:mediafusion /mediafusion

# Set up the PATH to include the user's local bin
ENV PATH="/home/mediafusion/.local/bin:$PATH"

RUN apt-get update && \
    apt-get install -y git

# Switch to non-root user
USER mediafusion

# Install dependencies
RUN pip install --user --no-cache-dir pipenv

COPY Pipfile Pipfile.lock ./

RUN pipenv install --deploy --ignore-pipfile

# Copy the source code
COPY . .

# Expose the port
EXPOSE 8000

CMD ["pipenv", "run", "gunicorn", "api.main:app", "-w", "10", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120", "--max-requests", "500", "--max-requests-jitter", "200"]
