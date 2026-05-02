import os

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from extractors import build_context_preview, validate_upload
from narrator_full_context import generate_narrative


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or os.getenv("APP_ACCESS_CODE") or "local-dev-secret"
UPLOAD_LIMIT_MB = 256
app.config["MAX_CONTENT_LENGTH"] = UPLOAD_LIMIT_MB * 1024 * 1024

MODEL_OPTIONS = [
    {
        "id": "gpt-5.4-mini",
        "label": "GPT-5.4 mini - better quality, recommended",
    },
    {
        "id": "gpt-5.4",
        "label": "GPT-5.4 - stronger, higher cost",
    },
    {
        "id": "gpt-5.4-nano",
        "label": "GPT-5.4 nano - lower cost",
    },
    {
        "id": "gpt-5-mini",
        "label": "GPT-5 mini - cost-efficient",
    },
    {
        "id": "gpt-5-nano",
        "label": "GPT-5 nano - fastest GPT-5 option",
    },
    {
        "id": "gpt-5",
        "label": "GPT-5 - stronger reasoning",
    },
    {
        "id": "gpt-4.1-mini",
        "label": "GPT-4.1 mini - older, affordable",
    },
    {
        "id": "gpt-4.1",
        "label": "GPT-4.1 - older, strong non-reasoning",
    },
    {
        "id": "gpt-4o",
        "label": "GPT-4o - older, versatile",
    },
    {
        "id": "gpt-4o-mini",
        "label": "GPT-4o mini - older, very low cost",
    },
]


@app.route("/", methods=["GET"])
def index():
    if access_code_is_required() and not session.get("access_granted"):
        return render_template("index.html", access_gate=True, access_error="")

    default_model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    require_user_key = user_api_key_is_required()
    return render_template(
        "index.html",
        access_code_required=False,
        default_model=default_model,
        model_options=MODEL_OPTIONS,
        server_key_configured=bool(os.getenv("OPENAI_API_KEY")) and not require_user_key,
        require_user_api_key=require_user_key,
        show_api_key_field=require_user_key or not bool(os.getenv("OPENAI_API_KEY")),
    )


@app.route("/unlock", methods=["POST"])
def unlock():
    expected_access_code = os.getenv("APP_ACCESS_CODE")
    entered_access_code = (request.form.get("access_code") or "").strip()
    if not expected_access_code or entered_access_code == expected_access_code:
        session["access_granted"] = True
        return redirect(url_for("index"))
    return render_template(
        "index.html",
        access_gate=True,
        access_error="That access code is not correct.",
    ), 403


@app.route("/api/generate", methods=["POST"])
def generate():
    source_file = request.files.get("source")
    deck_file = request.files.get("deck")
    audience = (request.form.get("audience") or "general").strip()
    tone = (request.form.get("tone") or "semi-formal").strip()
    guidance = (request.form.get("guidance") or "").strip()
    api_key = (request.form.get("api_key") or "").strip()
    include_files = request.form.get("include_files") == "on"
    allowed_models = {option["id"] for option in MODEL_OPTIONS}
    model = (request.form.get("model") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
    if model not in allowed_models:
        model = "gpt-5.4-mini"

    if access_code_is_required() and not session.get("access_granted"):
        return jsonify({"error": "Please enter the access code before using the app."}), 403

    if user_api_key_is_required() and not api_key:
        return jsonify({"error": "Please enter your own OpenAI API key before generating."}), 400

    if not api_key and not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "OpenAI API key is not configured. Add one in the app before generating."}), 400

    if not source_file or not deck_file:
        return jsonify({"error": "Please upload both the source document and the slide deck."}), 400

    try:
        source = validate_upload(source_file, {"pdf", "doc", "docx", "txt", "md"})
        deck = validate_upload(deck_file, {"ppt", "pptx", "pdf"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    source_bytes = source_file.read()
    deck_bytes = deck_file.read()
    if not source_bytes or not deck_bytes:
        return jsonify({"error": "One of the uploaded files appears to be empty."}), 400

    context = build_context_preview(source["filename"], source_bytes, deck["filename"], deck_bytes)

    try:
        result = generate_narrative(
            source_name=source["filename"],
            source_bytes=source_bytes,
            deck_name=deck["filename"],
            deck_bytes=deck_bytes,
            audience=audience,
            tone=tone,
            guidance=guidance,
            model=model,
            context=context,
            api_key=api_key,
            include_files=include_files,
        )
    except Exception as exc:
        return jsonify({"error": f"Could not generate the narrative: {exc}"}), 500

    return jsonify(result)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "variant": "full_deck_context",
            "access_code_required": access_code_is_required(),
            "openai_key_configured": bool(os.getenv("OPENAI_API_KEY")) and not user_api_key_is_required(),
            "require_user_api_key": user_api_key_is_required(),
            "upload_limit_mb": UPLOAD_LIMIT_MB,
        }
    )


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(exc):
    return (
        jsonify(
            {
                "error": (
                    f"The uploaded files are too large for this local app. "
                    f"Please keep the combined upload under {UPLOAD_LIMIT_MB} MB."
                )
            }
        ),
        413,
    )


def access_code_is_required() -> bool:
    return bool(os.getenv("APP_ACCESS_CODE"))


def user_api_key_is_required() -> bool:
    return os.getenv("REQUIRE_USER_API_KEY", "false").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5001")), debug=False, threaded=True)
