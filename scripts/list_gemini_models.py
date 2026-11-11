"""List the Gemini API models available to YOUR key (run it yourself; it calls Google).

Usage (from the repository root, with the project venv):
    venv\\Scripts\\python.exe scripts\\list_gemini_models.py
    venv\\Scripts\\python.exe scripts\\list_gemini_models.py --all     # also non-text models

The key is taken from the GEMINI_API_KEY environment variable, or from .env via
python-dotenv (the key itself is never printed). Compare the printed IDs with
GEMINI_MODEL_DEFAULT / GEMINI_MODEL_SMART / GEMINI_FALLBACK_MODELS in your .env.
"""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="show models that cannot generate text too")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set (environment or .env).")

    from google import genai

    client = genai.Client(api_key=api_key)
    configured = {
        os.getenv("GEMINI_MODEL_DEFAULT", "gemini-3.5-flash-lite"),
        os.getenv("GEMINI_MODEL_SMART", "gemini-3.8-flash"),
        *[m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemma-4-31b-it").split(",") if m.strip()],
    }
    rows = []
    for model in client.models.list():
        actions = getattr(model, "supported_actions", None) or []
        if not args.all and actions and "generateContent" not in actions:
            continue
        model_id = (model.name or "").removeprefix("models/")
        rows.append((model_id, getattr(model, "display_name", "") or "",
                     getattr(model, "input_token_limit", "") or "", getattr(model, "output_token_limit", "") or ""))

    print(f"{'model id':40} {'display name':32} {'in tokens':>10} {'out tokens':>10}  configured")
    for model_id, name, tin, tout in sorted(rows):
        mark = "  <-- in use" if model_id in configured else ""
        print(f"{model_id:40} {name[:32]:32} {str(tin):>10} {str(tout):>10}{mark}")
    missing = sorted(m for m in configured if m not in {r[0] for r in rows})
    if missing:
        print("\nConfigured but NOT available to this key:", ", ".join(missing))


if __name__ == "__main__":
    main()
