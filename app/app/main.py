import os
from enum import Enum
import logging
import redis
import sys
import time

from flask import Flask, request, jsonify
from openai import OpenAI

from .models import Host
from .utils import send_webhook_notification, increase_spam_count, _insert_model_call_pg
from .grist_prompt_store import GristPromptStore, PromptBundle

# ---- logging ----
log_level_str = os.getenv("LOG_LEVEL", os.getenv("LANGFUSE_LOG_LEVEL", "WARN")).upper()
log_level = getattr(logging, log_level_str, logging.WARN)
logging.basicConfig(stream=sys.stdout, level=log_level)
logger = logging.getLogger("ai_request_handler")

# ---- Redis ----
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")

# ---- Webhook ----
WEBHOOK_URL = os.getenv("WEBHOOK_ENDPOINT")
WEBHOOK_AUTH_TOKEN = os.getenv("WEBHOOK_AUTH_TOKEN")
WEBHOOK_AUTH_NAME = os.getenv("WEBHOOK_AUTH_NAME")
WEBHOOK = (WEBHOOK_URL, WEBHOOK_AUTH_NAME, WEBHOOK_AUTH_TOKEN)

SPAM_LIMIT = int(os.getenv("SPAM_LIMIT", "20"))
SPAM_PERIOD_LIMIT = int(os.getenv("SPAM_PERIOD_LIMIT", "1800"))

# ---- App ----
app = Flask(__name__)
r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    username=os.getenv("REDIS_USERNAME", ""),
    password=os.getenv("REDIS_PASSWORD", "")
)

prompt_store = GristPromptStore(
    doc_id=os.getenv("GRIST_DOC_ID"),
    api_key=os.getenv("GRIST_API_KEY"),
    server=os.getenv("GRIST_SERVER"),
)

openai_client = OpenAI(
    base_url=os.getenv("CLOUD_BASE_URL"),
    api_key=os.getenv("CLOUD_API_KEY"),
)

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

def resolve_content_type(content_type_raw: str):
    content_type = CONTENT_TYPE_MAPPING.get(content_type_raw)
    if not content_type:
        logger.info(f"Unknown content type received: {content_type_raw}; expected one of {list(CONTENT_TYPE_MAPPING.keys())}")
    return content_type

def get_prompt_bundle(content_type: ContentType) -> PromptBundle:
    return prompt_store.get_for_content_type(content_type)

def generate_model_response(model_input_cost_per_million, model_output_cost_per_million, **kwargs) -> str:
    """
    Calls the model, records usage/latency, inserts one row in public.model_calls, returns completion text.
    """
    model = kwargs.get("model")
    messages = kwargs.get("messages", [])
    input_text = next((m.get("content") for m in messages if m.get("role") == "user"), None)

    headers = request.headers
    host = headers.get("X-Host") or headers.get("X-Decidim-Host") or "unknown"
    payload = request.get_json(silent=True) or {}
    content_type_lbl = payload.get("type") or "unknown"

    # measure latency
    t0 = time.perf_counter()
    status = 200
    completion = None
    prompt_t = 0
    compl_t = 0

    try:
        response = openai_client.chat.completions.create(**kwargs)
        completion = response.choices[0].message.content
        prompt_t = int(getattr(response.usage, "prompt_tokens", 0) or 0)
        compl_t  = int(getattr(response.usage, "completion_tokens", 0) or 0)
        logger.info(f"prompt_tokens: {prompt_t} | completion_tokens: {compl_t}")
    except Exception as e:
        status = 500
        logger.error("OpenAI call failed", exc_info=True)
        raise
    finally:
        latency_ms = int((time.perf_counter() - t0) * 1000)

        pt = int(prompt_t or 0)
        ct = int(compl_t or 0)
        cost = (pt * model_input_cost_per_million + ct * model_output_cost_per_million) / 1_000_000.0

        try:
            _insert_model_call_pg(
                host=host,
                content_type=content_type_lbl,
                provider="openai",
                model=model,
                latency_ms=latency_ms,
                status=status,
                prompt_tokens=prompt_t,
                completion_tokens=compl_t,
                total_tokens=(prompt_t + compl_t) if (prompt_t or compl_t) else None,
                cost=cost,
                tags=[content_type_lbl, host],
                metadata={k: v for k, v in kwargs.items() if k not in ("model", "messages")},
                input=input_text,
                output=completion,
            )
        except Exception:
            logger.error("Postgres insert failed", exc_info=True)

    return completion

def run_inference_pipeline(host, content_type_raw, content_user):
    content_type_enum = resolve_content_type(content_type_raw)
    logger.info("Inside run_inference_pipeline")
    if content_type_enum is None:
        raise ValueError(f"Unsupported content type: {content_type_raw}")

    try:
        bundle = get_prompt_bundle(content_type_enum)
    except Exception as e:
        logger.info(f"Failed to fetch prompt from Grist: {e}")
        raise RuntimeError("Prompt loading failed")

    content_prompt = bundle.prompt
    content_config = bundle.config

    result = generate_model_response(
        model_input_cost_per_million=content_config.get("model_input_cost_per_million", 0),
        model_output_cost_per_million=content_config.get("model_output_cost_per_million", 0),
        model=content_config["model"],
        messages=[
            {"role": "system", "content": content_prompt},
            {"role": "user", "content": content_user}
        ],
        max_tokens=content_config.get("max_tokens"),
        temperature=content_config.get("temperature", 0),
        top_p=content_config.get("top_p", 1),
        presence_penalty=content_config.get("presence_penalty", 0),
    )
    return result


# ---- Route ----
@app.route('/spam/detection', methods=['POST'])
def spam_detection():
    logger.info("Starting handle function")

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
    except ValueError:
        logger.info("Client error during inference pipeline", exc_info=True)
        return jsonify(error="Unsupported content type"), 400
    except Exception:
        logger.error("Inference error", exc_info=True)
        return jsonify(message="AI Detection temporarily unavailable; please try again later"), 503

    if spam_result == "SPAM" and any(WEBHOOK):
        h = Host(host=host)
        current, total, exceeded = increase_spam_count(
            h=h,
            r=r,
            spam_limit=SPAM_LIMIT,
            spam_period_limit=SPAM_PERIOD_LIMIT
        )
        if exceeded:
            logger.info(f"-- Limit exceeded ({current}/{SPAM_LIMIT}) --", exc_info=True)
            send_webhook_notification(
                h=h,
                webhook=WEBHOOK,
                r=r,
                limit=SPAM_LIMIT,
                current=current,
                total_count=total
            )

    return jsonify(spam=spam_result), 200
