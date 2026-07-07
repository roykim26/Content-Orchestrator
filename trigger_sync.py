import httpx
import json
import sys


def main():
    url = "http://127.0.0.1:8020/automation/publish-autopilot/run"
    print("Triggering publish-autopilot sync...")
    print(f"POST {url}")
    print("")

    try:
        resp = httpx.post(url, timeout=120)
        print(f"HTTP Status: {resp.status_code}")
        print("")

        try:
            data = resp.json()
        except Exception:
            print("Response (raw):")
            print(resp.text)
            return

        # Pretty print results
        print("Response:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # Quick summary
        results = data.get("results", [])
        print("")
        print("=" * 50)
        for lane_result in results:
            lane = lane_result.get("lane", "?")
            status = lane_result.get("status", "?")
            stage = lane_result.get("stage", "?")
            err = lane_result.get("error_message", "")
            summary = lane_result.get("summary", {})

            print(f"Lane: {lane} | Status: {status} | Stage: {stage}")
            if err:
                print(f"  Error: {err}")

            feishu_sync = summary.get("feishu_sync", {})
            if feishu_sync:
                created = feishu_sync.get("created", 0)
                skipped = feishu_sync.get("skipped", 0)
                src = feishu_sync.get("source", {})
                print(f"  Feishu sync: created={created}, skipped={skipped}")
                if src.get("field_setup_error"):
                    print(f"  Field setup error: {src['field_setup_error']}")

            artifact_id = lane_result.get("artifact_id")
            if artifact_id:
                print(f"  Artifact: {artifact_id}")
        print("=" * 50)

    except httpx.ConnectError:
        print("[ERROR] Cannot connect to http://127.0.0.1:8020")
        print("        Is the Content Orchestrator service running?")
        sys.exit(1)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
