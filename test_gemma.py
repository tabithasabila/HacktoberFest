from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("Set the GEMINI_API_KEY environment variable before running this script.")

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
     model="gemma-4-26b-a4b-it",
    contents="You are a financial advisor. Analyse a student budget with UGX 400,000 income and UGX 150,000 spent on entertainment",
)

print(response.text)