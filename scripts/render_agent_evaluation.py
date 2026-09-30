"""Render one model's planning-question results and their scores as a Markdown report.

The table has a row per question: the prompt and its pass criterion, the model's exact answer, every audited
tool call, the verdict with its rationale, the time taken, and the model's tokens. A table before it gives
the model's time and tokens over every question: in total, per question, in GridLens tools, and in the
model. A report written before the harness recorded accounting takes it from each result's session folder. A call is shown with the arguments that
differ from the tool's defaults, so it can be reproduced exactly, and with the size or error of its result.
The report comes from `evaluate_agent_questions.py`. The scores are a JSON object keyed by question ID,
each value holding "verdict" (Pass, Partial, or Fail) and "rationale". An optional preamble, such as a
summary and findings written by the scorer, goes before the table.

    python scripts/render_agent_evaluation.py --report evaluation_report.json --scores scores.json \
      --model gemma4:31b --preamble preamble.md --output docs/plans/agent_evaluation_gemma4_31b.md
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
import statistics

from gridlens.agent.accounting import duration, turn_accounting
from gridlens.agent.tools import TOOL_NAMES, ToolService

ORDER = ("1", "2a", "2b", *(str(number) for number in range(3, 30)), "30a", "30b")


def defaults() -> dict[str, dict[str, object]]:
    """Return each tool's parameter defaults, so a call can be shown with only the arguments it changed."""
    table = {}
    for name in TOOL_NAMES:
        signature = inspect.signature(getattr(ToolService, name))
        table[name] = {key: item.default for key, item in signature.parameters.items() if item.default is not inspect.Parameter.empty}
    return table


def cell(text: str) -> str:
    """Make text safe for one Markdown table cell, keeping its line breaks. Only pipes are escaped, so text and code read as written."""
    return text.replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def call_line(call: dict, known: dict[str, dict[str, object]]) -> str:
    """Show one audited call: its ID, tool, changed arguments, and the size or error of its result."""
    base = known.get(call["tool"], {})
    arguments = {key: value for key, value in (call.get("arguments") or {}).items() if key not in base or value != base[key]}
    shown = ", ".join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in arguments.items())
    counts = call.get("counts") or {}
    if call.get("error"):
        outcome = f"error {call['error']}"
    elif "total_matching" in counts:
        outcome = f"{counts.get('returned', 0):,} of {counts['total_matching']:,} rows"
    else:
        outcome = "ok"
    return f"`{call['call_id']}` `{call['tool']}({shown})` → {outcome}"


def row(question: str, turn: dict, score: dict, record: dict, known: dict) -> str:
    """Render one table row for one turn."""
    prompt = f"{cell(turn['prompt'])}<br><br>*Pass: {cell(turn['pass'])}*"
    answer = cell(turn["answer"]) if turn.get("answer") else f"Runtime error {turn['error']['code']}: {cell(turn['error']['detail'])}"
    lines = [call_line(call, known) for call in turn["calls"]] or ["No tool calls."]
    rejected = len(turn.get("attempted_tools") or []) - len(turn["calls"])
    if rejected > 0:
        lines.append(f"{rejected} further call(s) failed the tool schema and were rejected before the tool ran.")
    execution = turn.get("script_execution")
    if execution:
        output = (execution.get("output_excerpt") or execution.get("reason") or "").strip()
        lines.insert(0, f"Before this turn the harness approved and ran the saved script: {execution.get('status', 'not run')}, exit code {execution.get('exit_code')}, output: {output[:300]}")
    if record.get("cleanup") and turn is record["turns"][-1]:
        lines.append("Harness cleanup: " + "; ".join(record["cleanup"]))
    verdict = f"**{score['verdict']}.** {score['rationale']}" if score else "Not scored."
    spent = turn.get("accounting") or {}
    counts = spent.get("tokens")
    used = f"{counts['total']:,}<br>({counts['output']:,} out)" if counts else "not reported"
    return f"| {question} | {prompt} | {answer} | {cell(chr(10).join(lines))} | {cell(verdict)} | {turn['seconds']:.0f} | {used} |"


def with_accounting(record: dict) -> dict:
    """Return a result with each turn's accounting, taken from its session folder when the report lacks it."""
    if all(turn.get("accounting") for turn in record["turns"]):
        return record
    session = Path(record.get("session", ""))
    found = turn_accounting(session) if session.is_dir() else []
    turns = [{**turn, "accounting": turn.get("accounting") or (found[index] if index < len(found) else None)} for index, turn in enumerate(record["turns"])]
    return {**record, "turns": turns}


def time_and_tokens(turns: list[dict]) -> list[str]:
    """Return a Markdown table of one model's time and tokens over the questions it answered."""
    spent = [turn["accounting"] for turn in turns if turn.get("accounting")]
    counted = [item["tokens"] for item in spent if item.get("tokens")]
    seconds = [turn["seconds"] for turn in turns]
    rates = [item["output_tokens_per_second"] for item in spent if item.get("output_tokens_per_second")]
    total = lambda name: sum(item[name] for item in counted)
    rows = [
        ("Prompts", f"{len(turns)}"),
        ("Total time", duration(sum(seconds))),
        ("Median time per prompt", duration(statistics.median(seconds)) if seconds else "unknown"),
        ("Time in GridLens tools, including waits for jobs", duration(sum(item["tool_seconds"] for item in spent))),
        ("Time in the model and runtime", duration(sum(item["model_seconds"] or 0.0 for item in spent))),
        ("Prompt tokens read", f"{total('prompt'):,}, {total('cache_read'):,} of them from the cache" if counted else "not reported"),
        ("Output tokens written", f"{total('output'):,}; median {statistics.median(item['output'] for item in counted):,.0f} per prompt" if counted else "not reported"),
        ("Median output tokens per second of model time", f"{statistics.median(rates):.1f}" if rates else "not reported"),
    ]
    if len(counted) < len(turns):
        rows.append(("Prompts without token counts", f"{len(turns) - len(counted)}"))
    return ["| Measure | Value |", "|---|---|", *(f"| {name} | {value} |" for name, value in rows), ""]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--scores", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--preamble", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    scores = json.loads(args.scores.read_text())
    known = defaults()
    turns = {}
    for record in report["results"]:
        if record["model"] == args.model:
            record = with_accounting(record)
            for turn in record["turns"]:
                turns[turn["id"]] = (turn, record)
    lines = [args.preamble.read_text().rstrip() + "\n"] if args.preamble else []
    lines += [f"Time and tokens for {args.model}:", "", *time_and_tokens([turns[question][0] for question in ORDER if question in turns])]
    lines += [
        "| # | Question and pass criterion | Response | Tool calls | Evaluation | Seconds | Tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for question in ORDER:
        if question in turns:
            turn, record = turns[question]
            lines.append(row(question, turn, scores.get(question), record, known))
    args.output.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.output}: {sum(1 for question in ORDER if question in turns)} rows")


if __name__ == "__main__":
    main()
