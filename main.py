import os
import json
from enum import Enum
import logging
import sys
from langfuse import Langfuse
from langfuse.decorators import observe, langfuse_context
from langfuse.model import PromptClient
from flask import Flask
from openai import OpenAI

app = Flask(__name__)
logging.basicConfig(stream=sys.stdout, level=logging.WARN)
logger = logging.getLogger("langfuse_faas")

logger.info("Starting> 0001")

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

    langfuse = Langfuse(
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        host=os.getenv("LANGFUSE_BASE_URL")
    )
    return langfuse.get_prompt(prompt_name, label="latest")


def tag_trace_with_metadata(content_type: ContentType, host: str, extra_tags, langfuse_context):
    base_tags = [content_type.value, host]
    all_tags = base_tags + extra_tags

    langfuse_context.update_current_trace(tags=all_tags)
    langfuse_context.update_current_trace(metadata={
        "content_type": content_type.value,
        "host": host
    })


@observe(as_type="generation")
def generate_model_response(**kwargs):
    model = kwargs.get("model")
    messages = kwargs.get("messages")
    openai_client = OpenAI(
        base_url=os.getenv("CLOUD_BASE_URL"),
        api_key=os.getenv("CLOUD_API_KEY"),
    )

    langfuse_context.update_current_observation(
        input=messages,
        model=model,
        metadata={k: v for k, v in kwargs.items() if k not in ["model", "messages"]}
    )

    response = openai_client.chat.completions.create(**kwargs)
    completion = response.choices[0].message.content

    logger.info(f"Langfuse_context prompt_tokens : {response.usage.prompt_tokens}")
    logger.info(f"Langfuse_context completion_tokens : {response.usage.completion_tokens}")

    langfuse_context.update_current_observation(
        output=completion,
        usage_details={
            "input": response.usage.prompt_tokens,
            "output": response.usage.completion_tokens
        }
    )

    return completion


@observe()
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

    extra_tags = []
    if result not in {"SPAM", "NOT_SPAM"}:
        extra_tags.append("invalid_output")
        result = ""

    tag_trace_with_metadata(content_type_enum, host, extra_tags, langfuse_context)
    return result


def handle(event, context):
    logger.info("Starting handle function")

    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
    LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL")

    logger.info(f"Langfuse host: {LANGFUSE_BASE_URL}")
    logger.info(f"Langfuse secret key: {LANGFUSE_SECRET_KEY}")
    logger.info(f"Langfuse public key: {LANGFUSE_PUBLIC_KEY}")

    if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
        return { "statusCode": 500, "body": json.dumps({"error": "Missing Langfuse configuration"}) }

    langfuse_context.configure(
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            host=os.getenv("LANGFUSE_BASE_URL"),
            enabled=True,
        )

    headers = event.get("headers", {})
    decidim = headers.get("X-Decidim-Host", "")
    logger.info(f"Headers {headers}")
    logger.info(f"Decidim {decidim}")
    if not decidim:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing Decidim Header"})
        }

    try:
        body = json.loads(event.get("body", "{}"))
        text = body.get("text", "")
        content_type = body.get("type", "")
        host = event.get("headers", {}).get("X-Host", "")
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid request payload"})
        }

    if not text:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Text cannot be empty"})
        }

    try:
        spam_result = run_inference_pipeline(host, content_type, text)
        langfuse_context.flush()
    except Exception as e:
        print(f"The error is : {e}")
        logger.info(f"The error is : {e}")
        return {
            "statusCode": 503,
            "body": json.dumps({"message": "AI Detection Error", "error": e})
        }

    return {
        "statusCode": 200,
        "body": json.dumps({"spam": spam_result})
    }

@app.route('/')
def spam_detection():
    logger.info("Starting handle function")

    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
    LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL")

    logger.info(f"Langfuse host: {LANGFUSE_BASE_URL}")
    logger.info(f"Langfuse secret key: {LANGFUSE_SECRET_KEY}")
    logger.info(f"Langfuse public key: {LANGFUSE_PUBLIC_KEY}")

    if not LANGFUSE_SECRET_KEY or not LANGFUSE_PUBLIC_KEY:
        return { "statusCode": 500, "body": json.dumps({"error": "Missing Langfuse configuration"}) }


    langfuse_context.configure(
            secret_key=LANGFUSE_SECRET_KEY,
            public_key=LANGFUSE_PUBLIC_KEY,
            host=LANGFUSE_BASE_URL,
            enabled=True,
        )

    try:
        spam_result = run_inference_pipeline("example.org", "Decidim::Proposals::Proposal", "More trees in our streets")
        langfuse_context.flush()
    except Exception as e:
        print(f"The error is : {e}")
        logger.info(f"The error is : {e}")
        return {
            "statusCode": 503,
            "body": json.dumps({"message": "AI Detection Error", "error": e})
        }

    return {
        "statusCode": 200,
        "body": json.dumps({"spam": spam_result})
    }

if __name__ == '__main__':
    app.run(debug=True)
