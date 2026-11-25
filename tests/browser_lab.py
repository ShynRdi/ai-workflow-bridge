#!/usr/bin/env python3
"""Development-only browser fixture. Never install into the normal Bridge profile."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PORT = 18765
URL = f"http://127.0.0.1:{PORT}/c/fixture"
PRODUCTION_HOST = "io.github.shynrdi.ai_workflow_bridge"
MARKER = "awb-browser-lab.json"

HTML = r'''<!doctype html>
<meta charset="utf-8">
<title>AWB LOCAL TEST PROVIDER — no network</title>
<style>
body{font:16px system-ui;max-width:850px;margin:40px auto;padding:16px}
textarea{width:100%;height:120px} pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:12px}
button{padding:12px} h1{font-size:24px}
</style>
<h1>AWB LOCAL TEST PROVIDER</h1>
<p>Deterministic fixtures only. No model, network calls, accounts or credentials.</p>
<p id="status">Waiting for planning prompt</p>
<div id="messages"></div>
<form id="form"><textarea id="composer" aria-label="Prompt"></textarea>
<button type="submit" aria-label="Send">Send</button></form>
<script>
const messages=document.querySelector("#messages"), composer=document.querySelector("#composer");
let turn=0;
const plan="<<<AI_WORKFLOW_ROADMAP>>>\n"+JSON.stringify({phases:[{id:"P0",title:"Local browser fixture",stages:["BUILD"],acceptance_criteria:{BUILD:["result.txt contains 42"]}}]})+"\n<<<END_AI_WORKFLOW_ROADMAP>>>\nREADY_TO_ARM";
const contract="<<<AI_WORKFLOW>>>\n"+JSON.stringify({version:1,phase:"P0",stage:"BUILD",summary:"Write disposable result file",commands:[{cmd:"python3 -c \"from pathlib import Path; Path('result.txt').write_text('42')\"",cwd:".",purpose:"Local fixture only"}],success_conditions:["result.txt contains 42"],next_step:"Review result"})+"\n<<<END_AI_WORKFLOW>>>";
function append(role,text){const node=document.createElement("pre");node.dataset.role=role;node.textContent=text;messages.append(node);}
document.querySelector("#form").addEventListener("submit", e=>{
 e.preventDefault(); const prompt=composer.value.trim(); if(!prompt)return;
 append("user",prompt);composer.value="";composer.dispatchEvent(new Event("input",{bubbles:true}));
 let response;
 if(turn===0 && prompt.includes("PLAN ONLY")) response=plan;
 else if(turn===1 && !prompt.includes("EXECUTION REPORT") && !prompt.includes("FINISH PROJECT REQUEST")) response=contract;
 else if(turn===2 && prompt.includes("EXECUTION REPORT") && prompt.includes("exit_code=0")) response="Local execution reported success. Review the file before accepting.\n<<<AI_WORKFLOW_STOP>>>";
 else if(turn===3 && prompt.includes("FINISH PROJECT REQUEST")) response="Fixture closeout.\n<<<AI_WORKFLOW_PROJECT_DONE>>>";
 else {response="Unexpected fixture input. Pause and inspect the test; no executable contract.";document.querySelector("#status").textContent="UNEXPECTED INPUT — stop test";}
 if(response.startsWith("Unexpected")) {append("assistant",response);return;}
 turn++;document.querySelector("#status").textContent="Fixture turn "+turn+" / 4";
 setTimeout(()=>append("assistant",response),300);
});
</script>'''

def replace_once(path, old, new):
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"Fixture patch no longer matches {path.name}")
    path.write_text(source.replace(old, new), encoding="utf-8")


def prepare(root: Path) -> None:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    host = PRODUCTION_HOST + "_lab_" + uuid.uuid4().hex
    for name in ("extension", "native_host"):
        shutil.copytree(REPO / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("profile", "state", "workspace"):
        (root / name).mkdir(mode=0o700)
    extension = root / "extension"
    manifest = json.loads((extension / "manifest.json").read_text())
    manifest["name"] = "AWB LOCAL LAB — NOT FOR PRODUCTION"
    manifest.pop("key", None)
    manifest["optional_host_permissions"] = ["http://127.0.0.1/*"]
    manifest["host_permissions"] = []
    (extension / "manifest.json").write_text(json.dumps(manifest, indent=2))
    replace_once(extension / "background.js", f'const NATIVE_HOST = "{PRODUCTION_HOST}";', f'const NATIVE_HOST = "{host}";')
    provider = [{
        "id": "mock", "name": "Local Mock", "vendor": "Development fixture",
        "status": "experimental", "domains": ["127.0.0.1"],
        "origins": ["http://127.0.0.1/*"], "composer": ["#composer"],
        "assistant": ['[data-role="assistant"]'], "user": ['[data-role="user"]'],
        "stop": ['[data-role="stop"]'], "send": ['button[aria-label="Send"]'],
    }]
    (extension / "providers.js").write_text(
        "(() => { const providers = " + json.dumps(provider) + ";\n"
        "const normalizeHost = h => String(h || '');\n"
        "const detectProvider = h => h === '127.0.0.1' ? providers[0] : null;\n"
        "const getProvider = id => providers.find(p => p.id === id) || null;\n"
        "globalThis.AWB_PROVIDERS = providers;\n"
        "globalThis.AWB_PROVIDER_UTILS = {normalizeHost,detectProvider,getProvider,allOrigins:()=>providers[0].origins}; })();\n"
    )
    replace_once(extension / "conversation-identity.js", "const ROUTE_RULES = {", "const ROUTE_RULES = { mock: { provisional: new Set(['/']), conversation: [/^\\/c\\/[^/]+$/] },")
    replace_once(extension / "sidepanel.js", '$("providerId").value = "chatgpt";', '$("providerId").value = "mock";')
    config = {"project_name": "AWB Local Browser Lab", "project_goal": "Create result.txt containing 42 in the disposable fixture workspace; require human review.", "workspace_root": str(root / "workspace"), "provider_id": "mock", "provider_mode": "manual", "auto_run_low_risk": False}
    (root / "state" / "config.json").write_text(json.dumps(config))
    launcher = root / "launcher.sh"
    launcher.write_text("#!/bin/sh\nexport AI_WORKFLOW_BRIDGE_HOME=" + shlex.quote(str(root / "state")) + "\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(root / "native_host" / "native_host.py")) + "\n")
    launcher.chmod(0o700)
    (root / MARKER).write_text(json.dumps({"host": host, "root": str(root)}))
    print("LAB:", root)
    print("Chrome profile:", root / "profile")
    print("Load unpacked:", extension)
    print("Workspace:", root / "workspace")


def metadata(root: Path) -> dict:
    data = json.loads((root / MARKER).read_text())
    if data.get("root") != str(root) or not re.fullmatch(re.escape(PRODUCTION_HOST) + r"_lab_[a-f0-9]{32}", data.get("host", "")):
        raise ValueError("Not an isolated lab directory")
    return data


def register(root: Path, extension_id: str) -> None:
    data = metadata(root)
    if not re.fullmatch("[a-p]{32}", extension_id):
        raise ValueError("Use the extension ID from the isolated Chrome profile")
    directory = Path.home() / ("Library/Application Support/Google/Chrome/NativeMessagingHosts" if sys.platform == "darwin" else ".config/google-chrome/NativeMessagingHosts")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (data["host"] + ".json")
    payload = {"name": data["host"], "description": "AWB isolated development lab", "path": str(root / "launcher.sh"), "type": "stdio", "allowed_origins": ["chrome-extension://" + extension_id + "/"]}
    with target.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
    target.chmod(0o600)
    print("Registered isolated host:", target)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/c/fixture":
            self.send_error(404)
            return
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "register", "serve"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--extension-id")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.action == "prepare":
        prepare(root)
    elif args.action == "register":
        register(root, args.extension_id or "")
    else:
        metadata(root)
        print("Local fixture:", URL, flush=True)
        with HTTPServer(("127.0.0.1", PORT), Handler) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()
