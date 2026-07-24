"""Generates tests/fixtures/assessments.jsonl -- Module 5's 40 hand-labelled
(objective, question, answer, expected_verdict) rows.

Three independent evidence cards (MapReduce shuffle, TCP handshake,
photosynthesis light reactions) so the suite isn't overfit to one card's
vocabulary. Labels are a first draft for human review (docs/…§Module 5:
"I will review these labels — generate a first draft and show me") --
edit rows directly in this file and re-run to regenerate the fixture, don't
hand-edit the .jsonl output.
"""

from __future__ import annotations

import json
from pathlib import Path

_OUT_PATH = Path(__file__).resolve().parent / "assessments.jsonl"

CARD_SHUFFLE = {
    "objective_id": "obj_mapreduce_shuffle",
    "objective_statement": "Student can explain why intermediate values must be grouped by key during the shuffle phase",
    "source_text": (
        "During the shuffle phase, the MapReduce framework takes the key-value pairs emitted by every "
        "mapper and groups all values that share the same key into a single list, regardless of which "
        "mapper produced them. This grouped list is then handed to the reducer. The shuffle phase itself "
        "does not compute any aggregate -- it only rearranges and groups data by key."
    ),
    "question": "Why does the shuffle phase need to group intermediate values by key before reduction can happen?",
    "card": {
        "objective_id": "obj_mapreduce_shuffle",
        "expected_ideas": [
            {"id": "idea_1", "idea": "mapper outputs carry intermediate keys paired with values"},
            {"id": "idea_2", "idea": "values sharing the same key are collected together before reduction"},
            {"id": "idea_3", "idea": "grouping happens across every mapper's output, not just one mapper's"},
        ],
        "known_misconceptions": [
            {"code": "shuffle_is_reduce", "text": "shuffle performs the reduction/aggregation itself"},
            {"code": "shuffle_is_sort_only", "text": "shuffle only sorts keys alphabetically, it doesn't group values"},
        ],
    },
}

CARD_HANDSHAKE = {
    "objective_id": "obj_tcp_handshake",
    "objective_statement": "Student can explain why TCP uses a three-way handshake to establish a connection",
    "source_text": (
        "TCP establishes a reliable connection using a three-way handshake. First, the client sends a SYN "
        "segment carrying its initial sequence number. The server replies with a SYN-ACK segment, "
        "acknowledging the client's sequence number and supplying its own. Finally, the client sends an ACK "
        "segment acknowledging the server's sequence number. Only after all three segments are exchanged do "
        "both sides know that the other can both send and receive data reliably."
    ),
    "question": "Why does TCP need three segments instead of just one or two to set up a connection?",
    "card": {
        "objective_id": "obj_tcp_handshake",
        "expected_ideas": [
            {"id": "idea_1", "idea": "the client sends a SYN to propose an initial sequence number"},
            {"id": "idea_2", "idea": "the server responds with SYN-ACK, acknowledging the client and proposing its own sequence number"},
            {"id": "idea_3", "idea": "the client sends a final ACK so both sides confirm they can send and receive"},
        ],
        "known_misconceptions": [
            {"code": "handshake_is_encryption", "text": "the three-way handshake encrypts the connection"},
            {"code": "two_way_is_enough", "text": "two messages would be enough, the third ACK is unnecessary"},
        ],
    },
}

CARD_PHOTOSYNTHESIS = {
    "objective_id": "obj_photosynthesis_electrons",
    "objective_statement": "Student can explain where the electrons that power the light-dependent reactions come from",
    "source_text": (
        "In the light-dependent reactions, chlorophyll in photosystem II absorbs light energy and loses "
        "electrons. These lost electrons are replaced by splitting water molecules (H2O), a process called "
        "photolysis, which also releases oxygen gas as a byproduct. The freed electrons then travel down an "
        "electron transport chain."
    ),
    "question": "Where do the electrons that photosystem II uses come from, and what else does that process produce?",
    "card": {
        "objective_id": "obj_photosynthesis_electrons",
        "expected_ideas": [
            {"id": "idea_1", "idea": "electrons come from splitting water molecules (photolysis)"},
            {"id": "idea_2", "idea": "splitting water also releases oxygen gas as a byproduct"},
            {"id": "idea_3", "idea": "the electrons replace those chlorophyll lost after absorbing light"},
        ],
        "known_misconceptions": [
            {"code": "electrons_from_co2", "text": "the electrons come from splitting carbon dioxide, not water"},
            {"code": "oxygen_from_co2", "text": "the oxygen released comes from splitting carbon dioxide, not water"},
        ],
    },
}


def _row(card_key: str, suffix: str, answer: str, expected_verdict: str, note: str) -> dict:
    card = {"shuffle": CARD_SHUFFLE, "handshake": CARD_HANDSHAKE, "photosynthesis": CARD_PHOTOSYNTHESIS}[card_key]
    return {
        "id": f"{card_key}_{suffix}",
        "objective_id": card["objective_id"],
        "objective_statement": card["objective_statement"],
        "card": card["card"],
        "source_text": card["source_text"],
        "question": card["question"],
        "answer": answer,
        "expected_verdict": expected_verdict,
        "note": note,
    }


ROWS: list[dict] = [
    # --- MapReduce shuffle (14 rows) ---------------------------------------
    _row("shuffle", "01", "Because all the values for the same key have to end up together in one list before the reducer can combine them, otherwise it would only see a fraction of the values for that key.", "correct", "clear, uses card vocabulary"),
    _row("shuffle", "02", "Grouping by key means every value tied to that key, no matter which mapper produced it, gets bundled into one list handed to the reducer.", "correct", "clear, standard vocabulary"),
    _row("shuffle", "03", "So the reducer gets one bucket per key instead of getting scattered pairs from different machines -- it needs the whole set for that key to do its job.", "correct", "correct but different vocabulary than the card (adversarial: vocabulary mismatch)"),
    _row("shuffle", "04", "It's like sorting mail into pigeonholes by recipient name before anyone reads it, so the same key's values aren't split across different piles.", "correct", "correct via analogy, no card vocabulary at all (adversarial: vocabulary mismatch)"),
    _row("shuffle", "05", "Because keys need to be grouped so the reducer can process them.", "partial", "restates the idea without explaining why grouping matters or how it works"),
    _row("shuffle", "06", "The shuffle groups values by key so they end up in a list together.", "partial", "gets idea_2 but doesn't mention it's across all mappers, no explanation of why reduction needs this"),
    _row("shuffle", "07", "Because the shuffle phase sorts all the keys so the reducer knows what order to work in.", "incorrect", "conflates grouping with sorting -- close to shuffle_is_sort_only misconception but not verbatim"),
    _row("shuffle", "08", "The shuffle phase actually does the reduction -- it adds up all the values for each key before the reducer even runs.", "incorrect", "matches known misconception shuffle_is_reduce"),
    _row("shuffle", "09", "I'm confident the shuffle phase groups keys by which mapper produced them, not by the key itself, so each mapper's output stays separate.", "incorrect", "confidently wrong, inverted the actual grouping criterion (adversarial: confidently wrong)"),
    _row("shuffle", "10", "Umm, I think it has something to do with sorting? Or maybe combining files? I'm not really sure how the key thing works.", "confused", "no coherent understanding of grouping or why it matters"),
    _row("shuffle", "11", "Keys and values and reducers and mappers all talk to each other somehow to make the output.", "confused", "word salad, no real claim about grouping"),
    _row("shuffle", "12", "I don't know.", "dont_know", "explicit don't-know"),
    _row("shuffle", "13", "not sure", "dont_know", "explicit uncertainty, minimal effort"),
    _row("shuffle", "14", "grouping", "partial", "one-word answer restating the term itself with no explanation (adversarial: one-word answer)"),
    # --- TCP three-way handshake (13 rows) ---------------------------------
    _row("handshake", "01", "The client sends a SYN with its starting sequence number, the server replies with SYN-ACK acknowledging that and sending its own sequence number, and then the client ACKs the server's number -- that way both sides have confirmed they can send and receive before any data flows.", "correct", "complete, covers all three ideas"),
    _row("handshake", "02", "Three segments let each side prove it both received the other's initial sequence number and can respond, which is why a lone SYN or just SYN+SYN-ACK wouldn't be enough to confirm both directions work.", "correct", "correct, different vocabulary than the card (adversarial: vocabulary mismatch)"),
    _row("handshake", "03", "It's a two-way handshake for confirming, you say hi, they say hi back and here's my number too, then you say got it -- both ends need to hear back from each other once each.", "correct", "correct via plain-language paraphrase (adversarial: vocabulary mismatch)"),
    _row("handshake", "04", "The client sends a SYN and the server sends back a SYN-ACK.", "partial", "covers idea_1 and idea_2 but omits the final client ACK (idea_3)"),
    _row("handshake", "05", "Because both sides need to agree on sequence numbers before sending data.", "partial", "true but vague, doesn't explain the three-step mechanism"),
    _row("handshake", "06", "The three-way handshake is what encrypts the connection so nobody can read the data in between, that's why you need three trips.", "incorrect", "matches known misconception handshake_is_encryption"),
    _row("handshake", "07", "Two messages would actually be enough -- the server's SYN-ACK already proves both sides are reachable, the last ACK is basically pointless.", "incorrect", "matches known misconception two_way_is_enough"),
    _row("handshake", "08", "I'm sure it's because TCP needs to negotiate the port numbers three separate times, once per segment.", "incorrect", "confidently wrong, invents an unrelated mechanism (adversarial: confidently wrong)"),
    _row("handshake", "09", "It's something about packets going back and forth I think, maybe checking the connection is fast enough?", "confused", "no coherent claim about the handshake's purpose"),
    _row("handshake", "10", "SYN ACK FIN RST, they're all TCP flags used somewhere in there.", "confused", "lists unrelated terminology without connecting it to why three steps are needed"),
    _row("handshake", "11", "No idea, we didn't really cover this part.", "dont_know", "explicit don't-know"),
    _row("handshake", "12", "idk", "dont_know", "minimal-effort non-answer (adversarial: one-word answer)"),
    _row("handshake", "13", "reliability", "partial", "one-word answer naming the general goal with zero mechanism (adversarial: one-word answer)"),
    # --- Photosynthesis light-dependent reactions (13 rows) ----------------
    _row("photosynthesis", "01", "Photosystem II loses electrons after absorbing light, and those electrons get replaced by splitting water molecules, which is also where the released oxygen gas comes from.", "correct", "complete, covers all three ideas"),
    _row("photosynthesis", "02", "Water gets split apart to donate electrons back to chlorophyll after it fires off its own electrons from catching light, and oxygen just comes out as a leftover of splitting that water.", "correct", "correct, different vocabulary than the card (adversarial: vocabulary mismatch)"),
    _row("photosynthesis", "03", "H2O is broken down to refill the electrons that got knocked loose, and that breakdown is also the source of the O2 that gets released.", "correct", "correct, terser phrasing (adversarial: vocabulary mismatch)"),
    _row("photosynthesis", "04", "The electrons come from splitting water.", "partial", "covers idea_1 only, omits the oxygen byproduct and the chlorophyll replacement link"),
    _row("photosynthesis", "05", "Water gets split during photosynthesis and oxygen comes out of that.", "partial", "covers idea_1 and idea_2 but never connects it to replacing chlorophyll's lost electrons"),
    _row("photosynthesis", "06", "The electrons come from splitting carbon dioxide molecules, and that's also where the oxygen that's released comes from.", "incorrect", "matches known misconceptions electrons_from_co2 and oxygen_from_co2"),
    _row("photosynthesis", "07", "I'm certain the electrons come directly from sunlight itself -- the photons themselves become the electrons that move down the transport chain.", "incorrect", "confidently wrong, physically incoherent claim (adversarial: confidently wrong)"),
    _row("photosynthesis", "08", "The electrons are produced by the mitochondria and sent over to the chloroplast for the light reactions.", "incorrect", "wrong organelle, but a substantive attempt"),
    _row("photosynthesis", "09", "Something about light hitting chlorophyll and then electrons moving but I don't really get where they come from originally.", "confused", "admits confusion about the core mechanism"),
    _row("photosynthesis", "10", "Photosystem two, chlorophyll, ATP, NADPH -- it's all connected somehow in the light reactions.", "confused", "term list with no coherent claim about electron origin"),
    _row("photosynthesis", "11", "I don't remember this part of the lecture.", "dont_know", "explicit don't-know"),
    _row("photosynthesis", "12", "no clue", "dont_know", "minimal-effort non-answer (adversarial: one-word answer)"),
    _row("photosynthesis", "13", "water", "correct", "one-word answer, but it is the single correct core fact for this specific question (adversarial: one-word answer, correct despite brevity)"),
]


def main() -> None:
    assert len(ROWS) == 40, f"expected exactly 40 rows, got {len(ROWS)}"
    with _OUT_PATH.open("w", encoding="utf-8") as f:
        for row in ROWS:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(ROWS)} rows to {_OUT_PATH}")


if __name__ == "__main__":
    main()
