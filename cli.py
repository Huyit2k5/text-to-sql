"""Giao diện terminal.

  python cli.py                          # Mức 1: baseline, hỏi-đáp một lượt
  python cli.py --config production      # Mức 3: hội thoại nhiều lượt, hỏi lại, giải thích, phân quyền
  python cli.py --config production --role analyst

Lệnh trong phiên: /role <admin|analyst|sales>, /reset (xóa lịch sử), /good, /bad (phản hồi câu vừa rồi), /exit
"""
import argparse
import sys

from t2sql.executor import format_table
from t2sql.llm import LLMError, default_llm
from t2sql.logstore import QueryLogger
from t2sql.pipeline import CONFIGS, TextToSQL
from t2sql.safety import POLICIES


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="baseline", choices=list(CONFIGS))
    ap.add_argument("--role", default="admin", choices=list(POLICIES))
    ap.add_argument("--max-print", type=int, default=20, help="số dòng tối đa in ra")
    ap.add_argument("-q", "--question", help="hỏi một câu rồi thoát")
    args = ap.parse_args()

    try:
        llm = default_llm()
    except Exception as e:
        sys.exit(f"Không khởi tạo được LLM: {e}")
    logger = QueryLogger()
    pipe = TextToSQL(llm, args.config, logger=logger)
    role, history, last = args.role, [], None
    multi_turn = pipe.config.rewrite_followups

    model = getattr(llm, "model", "?")
    print(f"Text-to-SQL [{args.config}] - model {model} - vai trò {role}. Gõ câu hỏi (tiếng Việt), /exit để thoát.")
    while True:
        if args.question:
            q = args.question
        else:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        if not q:
            continue
        if q in ("/exit", "/quit"):
            break
        if q == "/reset":
            history.clear()
            print("Đã xóa lịch sử hội thoại.")
            continue
        if q.startswith("/role"):
            parts = q.split()
            if len(parts) == 2 and parts[1] in POLICIES:
                role = parts[1]
                print(POLICIES[role].describe())
            else:
                print("Dùng: /role " + "|".join(POLICIES))
            continue
        if q in ("/good", "/bad"):
            if last:
                logger.feedback(last.id, q == "/good")
                print("Đã ghi nhận phản hồi, cảm ơn!")
            continue

        ans = pipe.ask(q, history=history if multi_turn else None, policy=role)
        last = ans
        if ans.standalone_question and ans.standalone_question != q:
            print(f"(hiểu là: {ans.standalone_question})")
        if ans.kind == "result":
            print(f"SQL: {ans.sql}")
            if len(ans.attempts) > 1:
                print(f"(đã tự sửa {len(ans.attempts) - 1} lần)")
            if ans.explanation:
                print(f"Giải thích: {ans.explanation}")
            print(format_table(ans.result, max_rows=args.max_print))
            if ans.result.ok:
                history.append({"question": ans.standalone_question or q, "sql": ans.sql})
        elif ans.kind == "clarify":
            print(f"Câu hỏi hơi mơ hồ: {ans.message}")
            history.append({"question": q, "sql": None, "clarify": ans.message})
        elif ans.kind in ("cannot", "refused"):
            print(f"Không thể trả lời từ dữ liệu này: {ans.message}")
        else:
            print(f"[Lỗi] {ans.message}")
        if args.question:
            break


if __name__ == "__main__":
    try:
        main()
    except LLMError as e:
        sys.exit(str(e))
