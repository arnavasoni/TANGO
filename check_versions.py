packages = [
    "fitz", "httpx", "langchain", "langchain_community", "langchain_groq",
    "numpy", "pandas", "PIL", "pydantic", "python_dotenv",
    "rapidfuzz", "sentence_transformers", "streamlit"
]

for pkg in packages:
    try:
        mod = __import__(pkg)
        print(f"{pkg}=={mod.__version__}")
    except Exception as e:
        print(f"{pkg} - could not import ({e})")
