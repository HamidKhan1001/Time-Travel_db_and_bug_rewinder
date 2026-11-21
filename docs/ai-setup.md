# AI Setup Guide (Gemini & AWS Bedrock)

The Time-Travel DB & Bug Rewinder agent uses an LLM for:
1. **Natural-language intent parsing** (extracting targets, preserve lists, and remediation intent)
2. **Root cause analysis & surgical code patch proposal** (fixing the bug and testing on a clone)
3. **Plain-English merge explanations** (explaining why an order was kept, backordered, or clamped)

If no API key or provider credentials are set, the system **automatically and gracefully falls back** to deterministic regex parsing and pattern patching. The live demo never crashes.

---

## Option A: Google Gemini (Recommended for default demo)

### 1. Get an API Key
Get a key at [Google AI Studio](https://aistudio.google.com/apikey).

### 2. Install Dependencies
```bash
pip install -r requirements-gemini.txt
```

### 3. Run with Gemini
**PowerShell:**
```powershell
$env:TT_LLM_PROVIDER = "gemini"
$env:GEMINI_API_KEY   = "your-gemini-api-key"
python server.py
```

**Bash:**
```bash
export TT_LLM_PROVIDER="gemini"
export GEMINI_API_KEY="your-gemini-api-key"
python3 server.py
```

---

## Option B: AWS Bedrock (For AWS Sponsor Prize)

### 1. Request Model Access
1. Open the AWS Console → **Amazon Bedrock** → **Model access**.
2. Click **Manage model access**.
3. Enable **Anthropic Claude 3 Haiku** (`anthropic.claude-3-haiku-20240307-v1:0`).

### 2. Install Dependencies
```bash
pip install -r requirements-bedrock.txt
```

### 3. Run with Bedrock
**PowerShell:**
```powershell
$env:TT_LLM_PROVIDER       = "bedrock"
$env:AWS_ACCESS_KEY_ID     = "your-access-key-id"
$env:AWS_SECRET_ACCESS_KEY = "your-secret-access-key"
$env:AWS_DEFAULT_REGION    = "us-east-1"
python server.py
```

**Bash:**
```bash
export TT_LLM_PROVIDER="bedrock"
export AWS_ACCESS_KEY_ID="your-access-key-id"
export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
export AWS_DEFAULT_REGION="us-east-1"
python3 server.py
```

---

## Environment Variable Reference

| Variable | Default | Purpose |
|---|---|---|
| `TT_LLM_PROVIDER` | `gemini` | `gemini` or `bedrock` |
| `GEMINI_API_KEY` | `""` | Google Gemini API key |
| `TT_LLM_MODEL` | `gemini-3.8-flash` | Gemini model name |
| `TT_BEDROCK_REGION` | `us-east-1` | AWS region for Bedrock client |
| `TT_BEDROCK_MODEL` | `anthropic.claude-3-haiku-20240307-v1:0` | Bedrock model ID |
| `TT_LLM_TIMEOUT` | `10` | Hard timeout (in seconds) for LLM calls |
| `TT_LLM_MIN_CONFIDENCE` | `0.7` | Confidence threshold before logging a human escalation warning |
| `TT_LLM_EXPLAIN` | `true` | `false` disables parallel conflict explanations |
| `TT_PACE` | `0.4` | Orchestrator pacing delay between steps |
