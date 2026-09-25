"""Source catalog and explicit snapshot comparisons."""
from difflib import SequenceMatcher
from app.database import Database


def compare_sources(db: Database, before_id: int, after_id: int) -> dict:
    sources = {source["id"]: source for source in db.catalog()}
    if before_id not in sources or after_id not in sources:
        raise KeyError("Source snapshot not found")
    if sources[before_id]["source_uri"] != sources[after_id]["source_uri"]:
        raise ValueError("Choose two snapshots of the same source")
    with db.connection() as conn:
        texts = []
        for document_id in (before_id, after_id):
            texts.append([row["text"] for row in conn.execute(
                "SELECT text FROM chunks WHERE document_id = ? ORDER BY ordinal", (document_id,))])
    matcher = SequenceMatcher(a=texts[0], b=texts[1], autojunk=False)
    changes = [{"kind": tag, "before_chunks": texts[0][a:b], "after_chunks": texts[1][c:d]}
               for tag, a, b, c, d in matcher.get_opcodes() if tag != "equal"]
    return {"before": sources[before_id], "after": sources[after_id],
            "changes": changes, "identical_extracted_chunks": not changes,
            "note": "Text comparison only. A wording change is not an assessed change in obligations."}
