#!/usr/bin/env python3
"""Строгий исполнитель утверждённой DRAKON-схемы 08.

Без --execute этот файл не поднимает VPN и не запускает nmap. Сухие прогоны
предназначены для проверки переходов конечного автомата.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
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
        subprocess.run(["git", "-C", str(repo), "fetch", "origin", ref], check=True)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", f"{ref}^{{commit}}"], text=True).strip()


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
    args = parser.parse_args()
    if args.task_id <= 0:
        parser.error("task ID должен быть положительным")
    resolved = git_sha(args.repo, args.schema_ref, args.fetch)
    _, contract = load_workflow(args.repo, resolved)
    output = args.output or Path.home() / ".local/state/red_drakon/runs" / f"{int(time.time())}-{args.task_id}.json"
    journal = Journal(output, args.task_id, args.schema_ref, resolved, bool(args.dry_run))
    journal.add("3", {"contract": digest(contract)})
    if args.dry_run:
        status, blocks = dry_result(args.dry_run)
        for block in blocks[1:]:
            journal.add(block, {"simulated": True})
        print(json.dumps({"status": status, "journal": str(output), "sha": resolved}, ensure_ascii=False))
        return 0 if status in {"live", "empty", "checkpoint"} else 2
    if not args.execute:
        journal.add("4", {"status": "blocked", "reason": "Нужен --execute; сетевые действия не запускались"})
        print(json.dumps({"status": "blocked", "journal": str(output), "sha": resolved}, ensure_ascii=False))
        return 2
    pc_api = Path("/root/agent_api/pc_api.py")
    subprocess.run([str(pc_api), "vpn-up", str(args.task_id)], check=True)
    journal.add("5", {"status": "vpn-up"})
    snapshot = route_snapshot()
    journal.add("7", snapshot)
    journal.add("9", {"status": "checkpoint", "name": "before-discovery", "reason": "Требуется отдельное возобновление реализации discovery"})
    print(json.dumps({"status": "checkpoint", "journal": str(output), "sha": resolved, "routes": snapshot["routes"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
