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

WORKFLOW = "08-no-creds-siluet"
DIAGRAM_PATH = Path("workflows/08-no-creds-siluet.drakon")
TERMINAL = {"1"}
FORBIDDEN = ("credential", "парол", "port", "порт", "service", "сервис", "mitre")
BLOCK_PREFIXES = {
    "3": "Зафиксировать номер задачи", "4": "Есть номер задачи", "5": "Поднять VPN",
    "6": "VPN подключён", "7": "Сохранить CIDR-маршруты", "8": "Маршруты ppp0",
    "9": "Контрольная точка", "10": "Оператор разрешил discovery", "11": "Найти живые хосты",
    "12": "Найдены живые хосты", "13": "Сохранить список живых хостов",
    "14": "Сохранить coverage", "15": "Завершить эксперимент", "16": "Завершить со статусом blocked",
    "17": "Завершить со статусом dead", "18": "Завершить со статусом blocked",
    "19": "Завершить со статусом blocked",
}


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
    validate(diagram)
    return diagram


def validate(diagram):
    if diagram.get("type") != "drakon" or diagram.get("name") != WORKFLOW:
        raise ValueError("Неверная исполнимая схема")
    items = diagram.get("items")
    if not isinstance(items, dict):
        raise ValueError("Нет блоков схемы")
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
        if item.get("type") in {"action", "question"} and not item.get("content", "").startswith(BLOCK_PREFIXES[item_id]):
            raise ValueError(f"Текст блока {item_id} не соответствует исполнимой схеме")
    if "только VPN и поиск живых хостов" not in diagram.get("params", ""):
        raise ValueError("Схема должна быть ограничена VPN и discovery")


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

    def terminal_result(self):
        """Итог существует только после финального блока схемы."""
        last = self.data["events"][-1]
        result = last.get("result", {})
        if last.get("block") != "15" or result.get("status") not in {"live", "empty"}:
            raise ValueError("Эксперимент не завершён: нет успешного финального блока 15")
        return result


def git_sha(repo, ref, fetch):
    if fetch:
        subprocess.run(["git", "-C", str(repo), "fetch", "--tags", "origin"], check=True)
        subprocess.run(["git", "-C", str(repo), "fetch", "origin", ref], check=True)
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", f"{ref}^{{commit}}"], text=True).strip()


def approved_tag(repo, sha):
    tags = subprocess.check_output(
        ["git", "-C", str(repo), "tag", "--points-at", sha, "workflow/08-no-creds-siluet/v*"], text=True
    ).splitlines()
    if not tags:
        raise ValueError("SHA не утверждён тегом workflow/08-no-creds-siluet/vN")
    return sorted(tags)[-1]


def route_snapshot():
    networks = []
    for _ in range(20):
        result = subprocess.run(["ip", "-j", "route", "show", "dev", "ppp0"], text=True, capture_output=True, check=True)
        routes = json.loads(result.stdout)
        networks = [item.get("dst") for item in routes if item.get("dst") and item.get("dst") != "default"]
        if networks:
            break
        time.sleep(1)
    if not networks:
        raise ValueError("У ppp0 нет CIDR-маршрутов после ожидания маршрутизации")
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


def ensure_claimed_task(task_id):
    """Свободный воркер занимает первую совместимую задачу из очереди."""
    pc_api = Path("/root/agent_api/pc_api.py")
    if not pc_api.is_file():
        raise FileNotFoundError("Не найден /root/agent_api/pc_api.py")
    current = subprocess.run([str(pc_api), "task-env"], text=True, capture_output=True, check=False)
    if current.returncode == 0:
        task = json.loads(current.stdout)
        if task.get("taskId") != task_id:
            raise RuntimeError(f"Воркер уже занят задачей {task.get('taskId')}, а не {task_id}")
        subprocess.run([str(pc_api), "task-heartbeat", str(task_id)], check=True, capture_output=True, text=True)
        return {"status": "already-claimed", "taskId": task_id, "engagementId": task.get("engagementId")}
    claimed = subprocess.run([str(pc_api), "task-claim-next"], text=True, capture_output=True, check=True)
    task = json.loads(claimed.stdout)
    claimed_id = task.get("id")
    if claimed_id != task_id:
        subprocess.run([str(pc_api), "task-release", str(claimed_id), "--reason",
                        "workflow SHA ожидает другую задачу"], check=False, capture_output=True, text=True)
        raise RuntimeError(f"Первая совместимая задача — {claimed_id}, а не {task_id}")
    return {"status": "claimed-from-queue", "taskId": task_id, "engagementId": task.get("engagementId")}


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


def record_hosts(task_id, engagement_id, hosts, artifact):
    pc_api = Path("/root/agent_api/pc_api.py")
    if not pc_api.is_file():
        raise FileNotFoundError("Не найден /root/agent_api/pc_api.py")
    environment = os.environ | {
        "OPENCODE_AGENT_TASK_ID": str(task_id),
        "OPENCODE_ENGAGEMENT_ID": str(engagement_id),
    }
    for index, host in enumerate(hosts):
        if index and index % 10 == 0:
            subprocess.run([str(pc_api), "task-heartbeat", str(task_id)], check=True, env=environment,
                           capture_output=True, text=True)
        subprocess.run([str(pc_api), "host", host], check=True, env=environment,
                       capture_output=True, text=True)
        subprocess.run([
            str(pc_api), "timeline", host,
            "--summary", "Обнаружение живого хоста workflow 08",
            "--command", "nmap -sn -n (см. файл доказательства)",
            "--result", f"Хост отвечает; доказательство: {artifact.name}", "--status", "success",
        ], check=True, env=environment, capture_output=True, text=True)


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
    parser.add_argument("--finalize", type=Path, help="Передать в панель сохранённый результат discovery после сбоя")
    args = parser.parse_args()
    if args.task_id <= 0:
        parser.error("task ID должен быть положительным")
    resolved = git_sha(args.repo, args.schema_ref, args.fetch)
    diagram = load_workflow(args.repo, resolved)
    tag = approved_tag(args.repo, resolved)
    if args.finalize:
        if args.dry_run or args.execute or args.resume or args.approve_discovery:
            parser.error("Финализация не совмещается с другими режимами")
        journal = Journal.open(args.finalize)
        if journal.data.get("taskId") != args.task_id or journal.data.get("resolvedSha") != resolved:
            raise ValueError("Задача или SHA не совпадают с журналом")
        last = journal.data["events"][-1]
        if last.get("block") != "11" or not isinstance(last.get("result", {}).get("hosts"), list):
            raise ValueError("В журнале нет непереданного результата discovery")
        task = ensure_claimed_task(args.task_id)
        hosts, artifact = last["result"]["hosts"], Path(last["result"]["evidence"])
        record_hosts(args.task_id, task["engagementId"], hosts, artifact)
        status, block = ("live", "13") if hosts else ("empty", "14")
        journal.add("12", {"status": status, "count": len(hosts), "recovered": True})
        journal.add(block, {"status": status, "hosts": hosts, "recovered": True})
        journal.add("15", {"status": status, "vpn": "already-disconnected", "evidence": str(artifact)})
        journal.terminal_result()
        print(json.dumps({"status": status, "journal": str(journal.path), "sha": resolved, "tag": tag, "hosts": hosts, "recovered": True}, ensure_ascii=False))
        return 0
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
        task = ensure_claimed_task(args.task_id)
        record_hosts(args.task_id, task["engagementId"], hosts, artifact)
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
        journal.terminal_result()
        print(json.dumps({"status": status, "journal": str(journal.path), "sha": resolved, "tag": tag,
                          "coverage": snapshot["routes"], "hosts": hosts}, ensure_ascii=False))
        return 0
    output = args.output or Path.home() / ".local/state/red_drakon/runs" / f"{int(time.time())}-{args.task_id}.json"
    journal = Journal(output, args.task_id, args.schema_ref, resolved, bool(args.dry_run))
    journal.add("3", {"diagram": digest(diagram)})
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
    journal.add("4", ensure_claimed_task(args.task_id))
    vpn_connected = False
    try:
        journal.add("5", vpn_up(args.task_id))
        vpn_connected = True
        journal.add("6", {"status": "ppp0-present"})
        snapshot = route_snapshot()
        journal.add("7", snapshot)
        journal.add("8", {"status": "routes-valid", "routes": snapshot["routes"]})
    except Exception as error:
        journal.add("18", {"status": "blocked", "error": str(error)})
        if vpn_connected:
            try:
                vpn_down()
                journal.add("cleanup", {"vpn": "disconnected"})
            except Exception as cleanup_error:
                journal.add("cleanup", {"vpn": "disconnect-failed", "error": str(cleanup_error)})
        raise
    journal.add("9", {"status": "checkpoint", "name": "before-discovery", "reason": "Требуется отдельное возобновление реализации discovery"})
    print(json.dumps({"status": "checkpoint", "journal": str(output), "sha": resolved, "tag": tag, "routes": snapshot["routes"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
