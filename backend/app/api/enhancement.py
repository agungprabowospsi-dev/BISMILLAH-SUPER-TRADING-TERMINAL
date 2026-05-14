from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
import subprocess, anthropic, os, re

router = APIRouter(prefix="/api/enhancement", tags=["enhancement"])
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY",""))

SYSTEM_PROMPT = """Kamu adalah AI Terminal Assistant untuk BISMILLAH SUPER TRADING TERMINAL.

Kamu bisa melakukan APA SAJA yang diminta:
- Baca, edit, buat file kode (Python, JSX, JS, dll)
- Jalankan git command
- Debug dan fix bug
- Tambah fitur baru
- Cek status sistem
- Analisis kode

STRUKTUR PROJECT di /app:
- /app/app/api/          → Backend API endpoints
- /app/app/engines/      → 34 Trading Engines
- /app/app/ml/           → ML Engine
- /app/app/core/         → Invesgo client
- /app/app/knowledge_base/ → RAG KB

Ketika perlu jalankan command, gunakan tag:
<cmd>command_disini</cmd>

Bisa multiple commands:
<cmd>cat /app/app/api/analytic.py | head -20</cmd>
<cmd>git log --oneline -5</cmd>

Selalu Bahasa Indonesia. Jelaskan dulu apa yang akan dilakukan."""

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]

class ExecRequest(BaseModel):
    command: str

@router.post("/chat")
async def enhancement_chat(req: ChatRequest):
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=3000,
            system=SYSTEM_PROMPT,
            messages=[{"role": m.role, "content": m.content} for m in req.messages]
        )
        content = response.content[0].text
        commands = re.findall(r'<cmd>(.*?)</cmd>', content, re.DOTALL)
        commands = [c.strip() for c in commands]
        return {
            "status": "ok",
            "content": content,
            "commands": commands,
        }
    except Exception as e:
        return {"status": "error", "content": str(e), "commands": []}

@router.post("/exec")
async def execute_command(req: ExecRequest):
    try:
        result = subprocess.run(
            req.command, shell=True, capture_output=True,
            text=True, timeout=60, cwd="/app"
        )
        return {
            "status": "ok",
            "command": req.command,
            "stdout": result.stdout[-5000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "command": req.command, "stdout": "Timeout >60s", "stderr": ""}
    except Exception as e:
        return {"status": "error", "command": req.command, "stdout": "", "stderr": str(e)}
