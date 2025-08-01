import os
from enum import Enum
import logging
import redis
import sys
from flask import Flask, request, jsonify
from openai import OpenAI
from langfuse.model import PromptClient
from langfuse import Langfuse
from .models import Host
from .utils import send_webhook_notification, increase_spam_count

log_level_str = os.getenv("LANGFUSE_LOG_LEVEL", "WARN").upper()
log_level = getattr(logging, log_level_str.upper(), logging.WARN)
logging.basicConfig(
        stream=sys.stdout,
        level=log_level
    )
logger = logging.getLogger("ai_request_handler")

# REDIS
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")

# WEBHOOK
WEBHOOK_URL = os.getenv("WEBHOOK_ENDPOINT")
WEBHOOK_AUTH_TOKEN = os.getenv("WEBHOOK_AUTH_TOKEN")
WEBHOOK_AUTH_NAME = os.getenv("WEBHOOK_AUTH_NAME")
WEBHOOK = (WEBHOOK_URL, WEBHOOK_AUTH_NAME, WEBHOOK_AUTH_TOKEN)

SPAM_LIMIT = int(os.getenv("SPAM_LIMIT", "20"))
SPAM_PERIOD_LIMIT = int(os.getenv("SPAM_PERIOD_LIMIT", "1800"))

app = Flask(__name__)
r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    username=os.getenv("REDIS_USERNAME", ""),
    password=os.getenv("REDIS_PASSWORD", "")
)

langfuse = Langfuse(
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    host=os.getenv("LANGFUSE_BASE_URL"),
)
logger.info("Langfuse SDK v3 initialized")


class ContentType(Enum):
    COMMENT = "comment"
    PROPOSAL = "proposal"
    USER = "user"
    MEETING = "meeting"
    DEBATE = "debate"
    INITIATIVE = "initiative"
    COLLABORATIVE_DRAFT = "collaborative_draft"


CONTENT_TYPE_MAPPING = {
    "Decidim::Comments::Comment": ContentType.COMMENT,
    "Decidim::Proposals::Proposal": ContentType.PROPOSAL,
    "Decidim::Proposals::CollaborativeDraft": ContentType.COLLABORATIVE_DRAFT,
    "Decidim::User": ContentType.USER,
    "Decidim::Meetings::Meeting": ContentType.MEETING,
    "Decidim::Debates::Debate": ContentType.DEBATE,
    "Decidim::Initiative": ContentType.INITIATIVE,
}

PROMPT_NAME_MAPPING = {
    ContentType.COMMENT: "Spam Comment Detection",
    ContentType.PROPOSAL: "Spam Proposal Detection",
    ContentType.USER: "Spam User Detection",
    ContentType.MEETING: "Spam Meeting Detection",
    ContentType.DEBATE: "Spam Debate Detection",
    ContentType.INITIATIVE: "Spam Initiative Detection"
}


def resolve_content_type(content_type_raw: str):
    content_type = CONTENT_TYPE_MAPPING.get(content_type_raw)
    if not content_type:
        print(f"Unknown content type received: {content_type_raw}")
        print(f"Expected one of {list(CONTENT_TYPE_MAPPING.keys())} but got {content_type_raw}")
        logger.info(f"Unknown content type received: {content_type_raw}")
    return content_type


def get_prompt_client(content_type: ContentType) -> PromptClient:
    prompt_name = PROMPT_NAME_MAPPING.get(content_type)
    logger.info(f"(get_prompt_client)> {prompt_name}")
    return langfuse.get_prompt(prompt_name, label="latest")


def generate_model_response(**kwargs):
    model = kwargs.get("model")
    messages = kwargs.get("messages")
    openai_client = OpenAI(
        base_url=os.getenv("CLOUD_BASE_URL"),
        api_key=os.getenv("CLOUD_API_KEY"),
    )

    with langfuse.start_as_current_generation(
            name="generate_model_response",
            model=model,
            input={"messages": messages},
            metadata={k: v for k, v in kwargs.items() if k not in ["model", "messages"]},
    ) as gen_span:
        response = openai_client.chat.completions.create(**kwargs)
        completion = response.choices[0].message.content

        logger.info(f"prompt_tokens: {response.usage.prompt_tokens}")
        logger.info(f"completion_tokens: {response.usage.completion_tokens}")

        gen_span.update(
            output=completion,
            usage_details={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.prompt_tokens + response.usage.completion_tokens,
            }
        )
    return completion


def run_inference_pipeline(host, content_type_raw, content_user):
    content_type_enum = resolve_content_type(content_type_raw)
    logger.info("Inside run_inference_pipeline")
    if content_type_enum is None:
        logger.info(f"Unsupported content type: {content_type_raw}")
        raise ValueError(f"Unsupported content type: {content_type_raw}")

    try:
        logger.info(f"Content type enum {content_type_enum}")
        prompt_client = get_prompt_client(content_type_enum)
    except Exception as e:
        logger.info(f"Failed to fetch prompt from Langfuse : {e}")
        raise RuntimeError("Prompt loading failed")

    content_prompt = prompt_client.prompt
    content_config = prompt_client.config

    tags = [content_type_enum.value, host]

    with langfuse.start_as_current_span(
            name="run_inference_pipeline",
            input={"text": content_user},
    ) as span:
        result = generate_model_response(
            model=content_config["model"],
            messages=[
                {"role": "system", "content": content_prompt},
                {"role": "user", "content": content_user}
            ],
            max_tokens=content_config["max_tokens"],
            temperature=content_config["temperature"],
            top_p=content_config["top_p"],
            presence_penalty=content_config["presence_penalty"],
        )

        if result not in {"SPAM", "NOT_SPAM"}:
            tags.append("invalid_output")

        span.update_trace(
            tags=tags,
            metadata={
                "content_type": content_type_enum.value,
                "host": host
            },
            output=result,
        )

        return result


@app.route('/spam/detection', methods=['POST'])
def spam_detection():
    logger.info("Starting handle function")
    if not os.getenv("LANGFUSE_SECRET_KEY") or not os.getenv("LANGFUSE_PUBLIC_KEY"):
        return jsonify(error="Missing Langfuse configuration"), 500

    headers = request.headers
    host = headers.get("X-Host") or headers.get("X-Decidim-Host")
    if not host:
        return jsonify(error="Missing required header: X-Host or X-Decidim-Host"), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="Invalid JSON payload"), 400

    text = data.get("text", "").strip()
    content_type = data.get("type", "").strip()
    if not text:
        return jsonify(error="Text cannot be empty"), 400

    try:
        spam_result = run_inference_pipeline(host, content_type, text)
        langfuse.flush()
    except ValueError:
        logger.info("Client error during inference pipeline", exc_info=True)
        return jsonify(error="Unsupported content type"), 400
    except Exception:
        logger.error("Inference error", exc_info=True)
        return (
            jsonify(
                message="AI Detection temporarily unavailable; please try again later"
            ),
            503,
        )

    if spam_result == "SPAM" and any(WEBHOOK):
        h = Host(host=host)
        current, total, exceeded = increase_spam_count(h=h,
                                                       r=r,
                                                       spam_limit=SPAM_LIMIT,
                                                       spam_period_limit=SPAM_PERIOD_LIMIT)
        if exceeded:
            logger.info("-- Limit exceeded ({}/{})--".format(current, SPAM_LIMIT), exc_info=True)
            send_webhook_notification(h=h,
                                      webhook=WEBHOOK,
                                      r=r,
                                      limit=SPAM_LIMIT,
                                      current=current,
                                      total_count=total)
    return jsonify(spam=spam_result), 200
