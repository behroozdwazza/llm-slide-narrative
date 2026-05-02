import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from app import MODEL_OPTIONS, UPLOAD_LIMIT_MB
from extractors import build_context_preview, validate_upload
from narrator_full_context import generate_narrative


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = UPLOAD_LIMIT_MB * 1024 * 1024


@app.route("/", methods=["GET"])
def index():
    default_model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    return render_template(
        "index.html",
        access_code_required=bool(os.getenv("APP_ACCESS_CODE")),
        default_model=default_model,
        model_options=MODEL_OPTIONS,
        server_key_configured=bool(os.getenv("OPENAI_API_KEY")),
    )


@app.route("/api/generate", methods=["POST"])
def generate():
    source_file = request.files.get("source")
    deck_file = request.files.get("deck")
    audience = (request.form.get("audience") or "general").strip()
    tone = (request.form.get("tone") or "semi-formal").strip()
    guidance = (request.form.get("guidance") or "").strip()
    api_key = (request.form.get("api_key") or "").strip()
    access_code = (request.form.get("access_code") or "").strip()
    include_files = request.form.get("include_files") == "on"
    allowed_models = {option["id"] for option in MODEL_OPTIONS}
    model = (request.form.get("model") or os.getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
    if model not in allowed_models:
        model = "gpt-5.4-mini"

    expected_access_code = os.getenv("APP_ACCESS_CODE")
    if expected_access_code and access_code != expected_access_code:
        return jsonify({"error": "The access code is missing or incorrect."}), 403

    if not api_key and not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "OpenAI API key is not configured on the server. Add one in the app or set OPENAI_API_KEY."}), 400

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
            "access_code_required": bool(os.getenv("APP_ACCESS_CODE")),
            "openai_key_configured": bool(os.getenv("OPENAI_API_KEY")),
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5001")), debug=False, threaded=True)
