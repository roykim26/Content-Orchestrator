from pathlib import Path


class PromptEngine:
    def __init__(self) -> None:
        self.prompt_root = Path(__file__).resolve().parents[1] / "prompts"

    def get_prompt(self, platform: str) -> tuple[str, str]:
        prompt_file = self.prompt_root / platform / "system.md"
        if not prompt_file.exists():
            return "v0", f"Default prompt for {platform}"
        return "v1", prompt_file.read_text(encoding="utf-8").strip()
