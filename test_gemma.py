from google import genai
import os

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("Set the GEMINI_API_KEY environment variable before running this script.")

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
     model="gemma-4-26b-a4b-it",
    contents="Roses are red...",
)

print(response.text)