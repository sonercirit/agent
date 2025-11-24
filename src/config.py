import os
import argparse
from dotenv import load_dotenv

load_dotenv()

parser = argparse.ArgumentParser(description="Agent Configuration")
parser.add_argument("--mode", "-m", choices=["auto", "manual"], default="manual", help="Operation mode")
parser.add_argument("--model", default="google/gemini-3-pro-preview", help="Model to use")
parser.add_argument("--provider", choices=["openrouter", "gemini"], default="gemini", help="LLM Provider")

args, unknown = parser.parse_known_args()

class Config:
    api_key = os.getenv("OPENROUTER_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("DEFAULT_MODEL", args.model) if args.model == "google/gemini-3-pro-preview" else args.model
    provider = args.provider
    mode = args.mode
    context_limit = 50000
    tool_output_limit = 1000

config = Config()
