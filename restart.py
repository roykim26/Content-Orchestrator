import os
import subprocess
import time


def stop_port_8020():
    print("[1/3] Stopping existing service on port 8020...")
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        found = False
        for line in result.stdout.splitlines():
            if ":8020" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    capture_output=True,
                )
                print(f"      Stopped process PID {pid}")
                found = True
                break
        if not found:
            print("      No process found on port 8020")
    except Exception as exc:
        print(f"      Error: {exc}")
    time.sleep(2)


def load_env():
    print("[2/3] Loading environment variables...")
    env_path = r"E:\yanque\海外投放\note-auto-publisher\.env"
    if not os.path.exists(env_path):
        print(f"      Warning: .env not found at {env_path}")
        return

    loaded = []
    with open(env_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in {
                "FEISHU_APP_ID",
                "FEISHU_APP_SECRET",
                "FEISHU_APP_TOKEN",
                "FEISHU_TABLE_ID",
                "FEISHU_NOTIFY_RECEIVE_ID_TYPE",
                "FEISHU_NOTIFY_RECEIVE_ID",
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "OPENAI_MODEL",
            }:
                os.environ[key] = value
                loaded.append(key)

    if "FEISHU_APP_TOKEN" in loaded:
        os.environ["FEISHU_LEGACY_TOPIC_APP_TOKEN"] = os.environ["FEISHU_APP_TOKEN"]
    if "FEISHU_TABLE_ID" in loaded:
        os.environ["FEISHU_LEGACY_TOPIC_TABLE_ID"] = os.environ["FEISHU_TABLE_ID"]

    os.environ["FEISHU_TOPIC_APP_TOKEN"] = "RqcTbRx11aX4Yvsj5ITcSEGtnAe"
    os.environ["FEISHU_TOPIC_TABLE_ID"] = "tblRmJfu5dpBGPpt"
    os.environ["ENABLE_TOPIC_SELECTION_SCHEDULER"] = "false"

    print(f"      Loaded {len(loaded)} variables")


def start_service():
    print("[3/3] Starting Content Orchestrator...")
    print("      URL: http://127.0.0.1:8020")
    print("")
    project_dir = r"E:\yanque\海外投放\Content Orchestrator"
    os.chdir(project_dir)
    subprocess.run(
        [
            r"C:\Users\jinlo\AppData\Local\Python\pythoncore-3.14-64\python.exe",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8020",
        ]
    )


if __name__ == "__main__":
    print("========================================")
    print("  Content Orchestrator - Restart")
    print("========================================")
    print("")
    stop_port_8020()
    load_env()
    start_service()
