from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path(os.getenv("EVIDENCETRACE_DB_PATH", "data/evidencetrace-v0.2.db"))
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

    @property
    def generation_enabled(self) -> bool:
        return bool(self.openai_api_key or (os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_MODEL")))

    @property
    def operator_key(self) -> str | None:
        return os.getenv("EVIDENCETRACE_OPERATOR_KEY")

    @property
    def local_mode(self) -> bool:
        return os.getenv("EVIDENCETRACE_LOCAL_MODE", "false").lower() == "true" and not os.getenv("AWS_LAMBDA_FUNCTION_NAME")


settings = Settings()
