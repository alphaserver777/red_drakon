#!/usr/bin/env python3
"""Строгий исполнитель утверждённой DRAKON-схемы 08.

Без --execute этот файл не поднимает VPN и не запускает nmap. Сухие прогоны
предназначены для проверки переходов конечного автомата.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid

WORKFLOW = "08-vpn-discovery"
DIAGRAM_PATH = Path("workflows/08-vpn-discovery.drakon")
CONTRACT_PATH = Path("workflows/08-vpn-discovery.contract.json")
TERMINAL = {"1"}
FORBIDDEN = ("credential", "парол", "port", "порт", "service", "сервис", "mitre")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def git_json(repo, sha, relative):
    content = subprocess.check_output(["git", "-C", str(repo), "show", f"{sha}:{relative.as_posix()}"], text=True)
    return json.loads(content)


def load_workflow(repo, sha=None):
    diagram = git_json(repo, sha, DIAGRAM_PATH) if sha else read_json(repo / DIAGRAM_PATH)
    contract = git_json(repo, sha, CONTRACT_PATH) if sha else read_json(repo / CONTRACT_PATH)
    validate(diagram, contract)
    return diagram, contract


def validate(diagram, contract):
    if diagram.get("type") != "drakon" or contract.get("workflow") != WORKFLOW:
        raise ValueError("Неверная пара схемы и контракта")
    items = diagram.get("items")
    operations = contract.get("operations")
    if not isinstance(items, dict) or not isinstance(operations, dict):
        raise ValueError("Нет блоков схемы или операций")
    reachable, pending = set(), ["2"]
    while pending:
        item_id = pending.pop()
        if item_id in reachable:
            continue
        if item_id not in items:
            raise ValueError(f"Переход на отсутствующий блок {item_id}")
        reachable.add(item_id)
        for edge in ("one", "two"):
            if items[item_id].get(edge):
                pending.append(str(items[item_id][edge]))
    if "1" not in reachable or set(items) != reachable:
        raise ValueError("Схема должна быть полностью достижимой и завершаться")
    for item_id, item in items.items():
        text = item.get("content", "").lower()
        if any(token in text for token in FORBIDDEN):
            raise ValueError(f"Запрещённый этап в блоке {item_id}")
        if item.get("type") in {"action", "question"} and item_id not in operations:
            raise ValueError(f"Для блока {item_id} нет машинной операции")
    for item_id, operation in operations.items():
        if item_id not in items:
            raise ValueError(f"Операция ссылается на отсутствующий блок {item_id}")
        transitions = [operation[key] for key in ("next", "success", "failure") if operation.get(key)]
        if not transitions or any(target not in items and target not in TERMINAL for target in transitions):
            raise ValueError(f"Некорректный переход операции {item_id}")
    if contract.get("policy", {}).get("scope") != "all-ppp0-routes":
        raise ValueError("Первый опыт ограничен только маршрутами ppp0")


class Journal:
    def __init__(self, output, task_id, schema_ref, resolved_sha, dry_run):
        self.path = output
        self.data = {"runId": str(uuid.uuid4()), "workflow": WORKFLOW, "taskId": task_id,
                     "schemaRef": schema_ref, "resolvedSha": resolved_sha, "dryRun": dry_run,
                     "events": []}
        self.add("run-created", {"pid": os.getpid()})

    @classmethod
    def open(cls, path):
        instance = cls.__new__(cls)
        instance.path = path
        instance.data = read_json(path)
        events = instance.data.get("events")
        if not isinstance(events, list) or not events:
            raise ValueError("Журнал не содержит событий")
        previous = ""
        for event in events:
            stored = event.get("hash")
            bare = {key: value for key, value in event.items() if key != "hash"}
            if event.get("previous") != previous or stored != digest(bare):
                raise ValueError("Нарушена хеш-цепочка журнала")
            previous = stored
        return instance

    def add(self, block, result):
        previous = self.data["events"][-1]["hash"] if self.data["events"] else ""
        event = {"at": int(time.time()), "block": block, "result": result, "previous": previous}
        event["hash"] = digest(event)
        self.data["events"].append(event)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".new")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


def git_sha(repo, ref, fetch):
    if fetch:
        subprocess.run(["git", "-C", str(repo), "fetch", "--tags", "origin"], check=True)
        subprocess.run(["git", "-C", str(repo), "fetch", "origin", ref], check=True)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", f"{ref}^{{commit}}"], text=True).strip()


def approved_tag(repo, sha):
    tags = subprocess.check_output(
        ["git", "-C", str(repo), "tag", "--points-at", sha, "workflow/08-vpn-discovery/v*"], text=True
    ).splitlines()
    if not tags:
        raise ValueError("SHA не утверждён тегом workflow/08-vpn-discovery/vN")
    return sorted(tags)[-1]


def route_snapshot():
    result = subprocess.run(["ip", "-j", "route", "show", "dev", "ppp0"], text=True, capture_output=True, check=True)
    routes = json.loads(result.stdout)
    networks = [item.get("dst") for item in routes if item.get("dst") and item.get("dst") != "default"]
    if not networks:
        raise ValueError("У ppp0 нет CIDR-маршрутов")
    oversized = [network for network in networks if int(network.rsplit("/", 1)[1]) < 16]
    if oversized:
        raise ValueError(f"Маршруты крупнее /16 требуют отдельного разрешения: {', '.join(oversized)}")
    control = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True).strip()
    if "ppp0" in control:
        raise ValueError("Управляющий маршрут ошибочно направлен через ppp0")
    return {"routes": networks, "controlRoute": control}


def vpn_up(task_id):
    """Получить цель задачи без вывода секрета и запустить штатный wrapper."""
    if os.geteuid() != 0:
        raise PermissionError("VPN-запуск требует root")
    base_url = os.environ.get("OPS_PANEL_URL", "").rstrip("/")
    token = os.environ.get("AGENT_API_TOKEN", "")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or not token:
        raise ValueError("Нужны OPS_PANEL_URL (HTTPS) и AGENT_API_TOKEN")
    request = Request(f"{base_url}/api/agent-tasks/{task_id}/vpn-target", method="POST",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode() or "{}")
    target = result.get("vpn") if isinstance(result, dict) else None
    if not isinstance(target, dict) or not all(target.get(key) for key in ("host", "port", "username", "password")):
        raise RuntimeError("Панель вернула неполную VPN-цель")
    if any("\n" in str(target[key]) or "\r" in str(target[key]) for key in ("host", "username", "password")):
        raise RuntimeError("Панель вернула недопустимые VPN-данные")
    script = Path("/root/agent_api/vpn-connect.sh")
    if not script.is_file():
        raise FileNotFoundError("Не найден /root/agent_api/vpn-connect.sh")
    runtime = Path("/run/agent-api-vpn")
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=runtime, prefix="workflow-", suffix=".env", delete=False) as stream:
        config = Path(stream.name)
        os.chmod(config, 0o600)
        for key, value in (("VPN_HOST", target["host"]), ("VPN_PORT", target["port"]),
                           ("VPN_USERNAME", target["username"]), ("VPN_PASSWORD", target["password"])):
            stream.write(f"{key}={value}\n")
    try:
        environment = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "VPN_ENV": str(config)}
        subprocess.run([str(script), "up"], env=environment, text=True, capture_output=True, check=True)
    finally:
        config.unlink(missing_ok=True)
    return {"taskId": result.get("taskId"), "engagementId": result.get("engagementId"), "status": "vpn-up"}


def vpn_down():
    script = Path("/root/agent_api/vpn-connect.sh")
    if script.is_file():
        subprocess.run([str(script), "down"], text=True, capture_output=True, check=True)


def discovery(routes, artifact):
    """Единственное активное действие: host discovery в разрешённых CIDR."""
    reports, live = [], set()
    for network in routes:
        command = ["nmap", "-sn", "-n", "--max-rate", "500", "--host-timeout", "300s", network]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        reports.append("$ " + " ".join(command) + "\n" + result.stdout + result.stderr)
        if result.returncode not in (0, 1):
            raise RuntimeError(f"nmap завершился с кодом {result.returncode} для {network}")
        for line in result.stdout.splitlines():
            if "Nmap scan report for" not in line:
                continue
            candidates = re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", line)
            if candidates:
                address = ipaddress.ip_address(candidates[-1])
                if address in ipaddress.ip_network(network, strict=False):
                    live.add(str(address))
    artifact.write_text("\n\n".join(reports) + "\n", encoding="utf-8")
    return sorted(live)


def record_hosts(task_id, hosts, artifact):
    pc_api = Path("/root/agent_api/pc_api.py")
    if not pc_api.is_file():
        raise FileNotFoundError("Не найден /root/agent_api/pc_api.py")
    for host in hosts:
        subprocess.run([str(pc_api), "host", host], check=True)
        subprocess.run([
            str(pc_api), "timeline", host,
            "--summary", "Обнаружение живого хоста workflow 08",
            "--command", "nmap -sn -n (см. файл доказательства)",
            "--result", f"Хост отвечает; доказательство: {artifact.name}", "--status", "success",
        ], check=True)


def dry_result(scenario):
    mapping = {
        "missing-scope": ("blocked", ["3", "4", "16"]),
        "vpn-failed": ("dead", ["3", "4", "5", "6", "17"]),
        "route-failed": ("blocked", ["3", "4", "5", "6", "7", "8", "18"]),
        "checkpoint": ("checkpoint", ["3", "4", "5", "6", "7", "8", "9"]),
        "empty": ("empty", ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "14", "15"]),
        "live": ("live", ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "15"]),
    }
    return mapping[scenario]


def main():
    parser = argparse.ArgumentParser(description="Исполнитель DRAKON workflow 08")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--schema-ref", required=True)
    parser.add_argument("--workflow", default=WORKFLOW, choices=[WORKFLOW])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--dry-run", choices=["missing-scope", "vpn-failed", "route-failed", "checkpoint", "empty", "live"])
    parser.add_argument("--execute", action="store_true", help="Разрешить только VPN и остановку перед discovery")
    parser.add_argument("--resume", type=Path, help="Продолжить журнал из before-discovery")
    parser.add_argument("--approve-discovery", action="store_true", help="Явно разрешить discovery при --resume")
    args = parser.parse_args()
    if args.task_id <= 0:
        parser.error("task ID должен быть положительным")
    resolved = git_sha(args.repo, args.schema_ref, args.fetch)
    _, contract = load_workflow(args.repo, resolved)
    tag = approved_tag(args.repo, resolved)
    if args.resume:
        if args.dry_run or args.execute or not args.approve_discovery:
            parser.error("Возобновление требует только --resume и --approve-discovery")
        journal = Journal.open(args.resume)
        if journal.data.get("taskId") != args.task_id or journal.data.get("resolvedSha") != resolved:
            raise ValueError("Задача или SHA не совпадают с журналом")
        last = journal.data["events"][-1]
        if last.get("block") != "9" or last.get("result", {}).get("name") != "before-discovery":
            raise ValueError("Журнал не находится в контрольной точке before-discovery")
        snapshot = route_snapshot()
        journal.add("10", {"status": "approved", "tag": tag, "routes": snapshot["routes"]})
        artifact = journal.path.with_suffix(".discovery.txt")
        hosts = discovery(snapshot["routes"], artifact)
        journal.add("11", {"status": "completed", "coverage": snapshot["routes"], "evidence": str(artifact), "hosts": hosts})
        record_hosts(args.task_id, hosts, artifact)
        status, block = ("live", "13") if hosts else ("empty", "14")
        journal.add("12", {"status": status, "count": len(hosts)})
        journal.add(block, {"status": status, "hosts": hosts})
        try:
            vpn_down()
            finish = {"status": status, "vpn": "disconnected", "evidence": str(artifact)}
        except Exception as error:
            finish = {"status": "error", "vpn": "disconnect-failed", "error": str(error), "evidence": str(artifact)}
        journal.add("15", finish)
        if finish["status"] == "error":
            print(json.dumps({"status": "error", "journal": str(journal.path), "sha": resolved, "tag": tag}, ensure_ascii=False))
            return 2
        print(json.dumps({"status": status, "journal": str(journal.path), "sha": resolved, "tag": tag,
                          "coverage": snapshot["routes"], "hosts": hosts}, ensure_ascii=False))
        return 0
    output = args.output or Path.home() / ".local/state/red_drakon/runs" / f"{int(time.time())}-{args.task_id}.json"
    journal = Journal(output, args.task_id, args.schema_ref, resolved, bool(args.dry_run))
    journal.add("3", {"contract": digest(contract)})
    if args.dry_run:
        status, blocks = dry_result(args.dry_run)
        for block in blocks[1:]:
            journal.add(block, {"simulated": True})
        print(json.dumps({"status": status, "journal": str(output), "sha": resolved, "tag": tag}, ensure_ascii=False))
        return 0 if status in {"live", "empty", "checkpoint"} else 2
    if not args.execute:
        journal.add("4", {"status": "blocked", "reason": "Нужен --execute; сетевые действия не запускались"})
        print(json.dumps({"status": "blocked", "journal": str(output), "sha": resolved, "tag": tag}, ensure_ascii=False))
        return 2
    journal.add("5", vpn_up(args.task_id))
    journal.add("6", {"status": "ppp0-present"})
    snapshot = route_snapshot()
    journal.add("7", snapshot)
    journal.add("8", {"status": "routes-valid", "routes": snapshot["routes"]})
    journal.add("9", {"status": "checkpoint", "name": "before-discovery", "reason": "Требуется отдельное возобновление реализации discovery"})
    print(json.dumps({"status": "checkpoint", "journal": str(output), "sha": resolved, "tag": tag, "routes": snapshot["routes"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
