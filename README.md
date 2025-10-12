# Setup

Required dependencies:

google-genai
jsonschema
python-dotenv

Set up a .env file with GEMINI_API_KEY variable.

# Usage

`extraction_sync.py` has all logic for extracting structured AIR permit data. It relies on `extraction_prompt.md` to load in how-to instructions for the LLM. 

# Validation

`validate_extraction.py` loads in the `schema.json` file and validates a directory of JSON outputs against this. Example usage:

`python validate_extraction.py extracted_data --schema schema.json`