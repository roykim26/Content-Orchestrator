import sqlite3
from pathlib import Path


def main():
    db_path = Path.home() / "AppData" / "Local" / "ContentOrchestrator" / "content_orchestrator.sqlite3"
    if not db_path.exists():
        print(f"[ERROR] Database not found: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print("========================================")
    print("  Content Orchestrator - Sync Check")
    print("========================================\n")

    # 1. Topic overview
    c.execute("SELECT COUNT(*) as cnt FROM topic")
    total_topics = c.fetchone()["cnt"]
    print(f"[1] Total topics in local DB: {total_topics}")

    # 2. New topics (created after 2026-05-27)
    c.execute("""
        SELECT id, master_topic, status, target_platforms, note_account, feishu_record_id, created_at
        FROM topic
        WHERE created_at > '2026-05-27'
        ORDER BY created_at DESC
    """)
    new_topics = c.fetchall()
    print(f"[2] New topics (after 2026-05-27): {len(new_topics)}\n")

    if new_topics:
        for row in new_topics[:10]:
            platforms = row["target_platforms"] or ""
            print(f"    {row['id'][:16]} | {row['status']:8} | {platforms[:30]:30} | {row['master_topic'][:35]}")
        if len(new_topics) > 10:
            print(f"    ... and {len(new_topics) - 10} more")
    else:
        print("    No new topics found. Feishu sync may not have run yet.")

    print("")

    # 3. Distribution tasks for new topics
    c.execute("""
        SELECT dt.platform, dt.status, COUNT(*) as cnt
        FROM distributiontask dt
        JOIN topic t ON dt.topic_id = t.id
        WHERE t.created_at > '2026-05-27'
        GROUP BY dt.platform, dt.status
        ORDER BY dt.platform, dt.status
    """)
    task_stats = c.fetchall()
    print("[3] Distribution tasks for new topics:")
    if task_stats:
        for row in task_stats:
            print(f"    {row['platform']:12} | {row['status']:8} | {row['cnt']}")
    else:
        print("    No tasks found for new topics.")

    print("")

    # 4. Pending note/ameba tasks specifically
    c.execute("""
        SELECT dt.platform, t.note_account, COUNT(*) as cnt
        FROM distributiontask dt
        JOIN topic t ON dt.topic_id = t.id
        WHERE dt.status = 'pending' AND dt.platform IN ('note', 'ameba')
        GROUP BY dt.platform, t.note_account
        ORDER BY dt.platform, t.note_account
    """)
    pending = c.fetchall()
    print("[4] Pending note/ameba tasks:")
    if pending:
        for row in pending:
            acc = row["note_account"] or "(none)"
            print(f"    {row['platform']:12} | account={acc:10} | {row['cnt']}")
    else:
        print("    No pending note/ameba tasks.")

    print("")

    # 5. Feishu record coverage
    c.execute("SELECT COUNT(*) as cnt FROM topic WHERE feishu_record_id IS NOT NULL AND feishu_record_id != ''")
    with_feishu = c.fetchone()["cnt"]
    print(f"[5] Topics with feishu_record_id: {with_feishu} / {total_topics}")

    # 6. Recommendations
    print("\n========================================")
    print("  Recommendations")
    print("========================================")

    if len(new_topics) >= 40:
        print("New topics synced successfully!")
    elif len(new_topics) > 0:
        print(f"Only {len(new_topics)} new topics synced. Expected 50. Check publish-autopilot logs.")
    else:
        print("No new topics found. Please trigger publish-autopilot manually:")
        print("  curl http://127.0.0.1:8020/api/automation/publish-autopilot -Method POST")

    if pending:
        note_pending = sum(r["cnt"] for r in pending if r["platform"] == "note")
        ameba_pending = sum(r["cnt"] for r in pending if r["platform"] == "ameba")
        print(f"\nReady to publish:")
        print(f"  - note:   {note_pending} pending tasks")
        print(f"  - ameba:  {ameba_pending} pending tasks")
    else:
        print("\nNo pending note/ameba tasks. Next run may generate them.")

    conn.close()
    print("")
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
