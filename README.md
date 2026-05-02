# Slide Narrative Builder

Local web app for generating a slide-by-slide English speaker narrative from:

- a source document: PDF, Word, text, or markdown
- a slide deck: PowerPoint or PDF
- an audience type and required tone

The app uses the OpenAI Responses API when `OPENAI_API_KEY` is configured. Without a key, it still opens in preview mode and drafts a basic narration from locally extracted slide text.

## Run

```powershell
python -m pip install -r requirements.txt
$env:OPENAI_API_KEY="your_api_key"
python app.py
```

Then open `http://127.0.0.1:5000`.

To run the full-context version locally:

```powershell
python app_full_context.py
```

Then open `http://127.0.0.1:5001`.

Optional default model:

```powershell
$env:OPENAI_MODEL="gpt-5.4-mini"
```

The app includes a model dropdown with current GPT-5.4/5.5 choices and older GPT-4.1/GPT-4o choices.

You can also paste an API key into the app's API key field for a single browser session. The app does not save that key.

## Deploy on Render

1. Push this folder to a GitHub repository.
2. In Render, create a new Web Service from that repository.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app_full_context:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1`
4. Add environment variables:
   - `OPENAI_API_KEY`: your OpenAI API key
   - `APP_ACCESS_CODE`: a shared code colleagues must enter
   - `OPENAI_MODEL`: optional, for example `gpt-5.4-mini`
   - `REQUIRE_USER_API_KEY`: `false` to use the server key after access-code login
   - `SECRET_KEY`: a random private string used for the access-code session
5. Deploy and share the Render URL plus the access code with colleagues.

`render.yaml` is included if you prefer Render Blueprint deployment.

Security note: uploaded documents and decks are processed by the deployed app and sent to OpenAI when generating narratives. Do not share the public URL without an access code.

## Notes

- `.docx` and `.pptx` get local text previews.
- By default, the model receives extracted text from the uploaded files. Turn on "Upload original files to OpenAI" when PDF or visual fidelity matters.
- Legacy `.doc` and `.ppt` files are accepted by the model path, but local previews are limited.
- Combined uploads are limited to 256 MB.
