"""Milestone 5, step 3: Gradio interface for the FSU Unofficial Advising Guide.

Run as: python app.py  ->  http://localhost:7860
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "pipeline"))

import gradio as gr

from query import ask
from retrieve import _get_collection

INSUFFICIENT_WARNING = (
    "⚠️ INSUFFICIENT CONTEXT: The system could not find relevant "
    "information for this question. Do not rely on the following response."
)

WARNING_CSS = """
.warning-box {
    background-color: #fff3cd;
    border: 1px solid #ffe08a;
    border-radius: 8px;
    padding: 12px 16px;
    color: #664d03;
}
"""


def _most_recent_scrape_date() -> str:
    """Most recent scraped_at across the whole collection, read at startup."""
    all_meta = _get_collection().get(include=["metadatas"])["metadatas"]
    most_recent = max(
        (m.get("scraped_at", "") for m in all_meta if m.get("scraped_at")),
        default="unknown",
    )
    return most_recent.split("T")[0] if "T" in most_recent else most_recent


def on_ask(question: str):
    question = (question or "").strip()
    if not question:
        return "Please enter a question.", []

    result = ask(question)
    answer = result["answer"]
    if not result["has_sufficient_context"]:
        answer = INSUFFICIENT_WARNING + "\n\n" + answer

    rows = [
        [i, source["doc_type"], source["course_program"],
         source["scraped_at"] or "", source["source_url"] or ""]
        for i, source in enumerate(result["sources"], 1)
    ]
    return answer, rows


with gr.Blocks(title="FSU Unofficial Advising Guide", css=WARNING_CSS) as demo:
    gr.Markdown("# FSU Unofficial Advising Guide")
    gr.Markdown(
        "Answers drawn from the FSU course catalog, program requirements, "
        "and course schedule. Always verify with your advisor before "
        "registering."
    )
    gr.Markdown(
        "⚠️ Seat availability data was last scraped on %s. Verify current "
        "availability on the FSU SEATS site before registering."
        % _most_recent_scrape_date(),
        elem_classes="warning-box",
    )

    question_box = gr.Textbox(
        label="Your question",
        placeholder="e.g. What do I need before I can take HIST 3900?",
    )
    ask_button = gr.Button("Ask", variant="primary")
    answer_box = gr.Textbox(label="Answer", lines=10, interactive=False)
    sources_table = gr.Dataframe(
        headers=["#", "Type", "Course/Program", "As of", "URL"],
        label="Sources",
        interactive=False,
    )

    ask_button.click(on_ask, inputs=question_box,
                     outputs=[answer_box, sources_table])
    question_box.submit(on_ask, inputs=question_box,
                        outputs=[answer_box, sources_table])


if __name__ == "__main__":
    demo.launch(server_port=7860)
