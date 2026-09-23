from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv("EVIDENCETRACE_DB_PATH", "data/evidencetrace.db"))
    top_k: int = int(os.getenv("EVIDENCETRACE_TOP_K", "6"))
    min_retrieval_score: float = float(os.getenv("EVIDENCETRACE_MIN_RETRIEVAL_SCORE", "0.05"))
    min_term_coverage: float = float(os.getenv("EVIDENCETRACE_MIN_TERM_COVERAGE", "0.50"))
    semantic_enabled: bool = os.getenv("EVIDENCETRACE_SEMANTIC_ENABLED", "false").lower() == "true"
    semantic_model: str = os.getenv("EVIDENCETRACE_SEMANTIC_MODEL", "all-MiniLM-L6-v2")
    semantic_rrf_weight: float = float(os.getenv("EVIDENCETRACE_SEMANTIC_RRF_WEIGHT", "0.70"))
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5")

    @property
    def openai_api_key(self) -> str | None:
        return os.getenv("OPENAI_API_KEY")


settings = Settings()
