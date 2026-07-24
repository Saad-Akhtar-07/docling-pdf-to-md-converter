"""Builds the compiled LangGraph for Module 4's turn skeleton.

No checkpointer is attached (CLAUDE.md invariant #3): the graph runs once
per run_turn() call, start to finish, entirely in-process, and all durable
state lives in Postgres (written by persist_turn/return_existing) rather
than in any LangGraph-managed store.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from slidevision.graph.nodes import (
    generate_turn,
    load_state,
    persist_turn,
    retrieve_grounding,
    return_existing,
    select_action_node,
)
from slidevision.graph.state import TurnState


def _route_after_load(state: TurnState) -> str:
    return "return_existing" if state["is_duplicate"] else "select_action"


def build_graph():
    graph = StateGraph(TurnState)
    graph.add_node("load_state", load_state)
    graph.add_node("select_action", select_action_node)
    graph.add_node("retrieve_grounding", retrieve_grounding)
    graph.add_node("generate_turn", generate_turn)
    graph.add_node("persist_turn", persist_turn)
    graph.add_node("return_existing", return_existing)

    graph.set_entry_point("load_state")
    graph.add_conditional_edges(
        "load_state",
        _route_after_load,
        {"return_existing": "return_existing", "select_action": "select_action"},
    )
    graph.add_edge("select_action", "retrieve_grounding")
    graph.add_edge("retrieve_grounding", "generate_turn")
    graph.add_edge("generate_turn", "persist_turn")
    graph.add_edge("persist_turn", END)
    graph.add_edge("return_existing", END)

    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
