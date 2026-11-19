"""Offline adapter for the pinned NUS token-classification checkpoint."""

from privapii import Span

CHECKPOINT_BYTES = 2_235_612_716


def checkpoint_ready(model_dir):
    weights = model_dir / "model.safetensors"
    return weights.is_file() and weights.stat().st_size == CHECKPOINT_BYTES


class NusDetector:
    def __init__(self, model_dir):
        if not checkpoint_ready(model_dir):
            raise ValueError("The pinned NUS checkpoint is missing or incomplete.")
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

        torch.set_num_threads(min(torch.get_num_threads(), 6))
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_dir), local_files_only=True, trust_remote_code=False
        )
        model = AutoModelForTokenClassification.from_pretrained(
            str(model_dir), local_files_only=True, trust_remote_code=False,
            use_safetensors=True
        )
        self.predict = pipeline(
            "token-classification", model=model, tokenizer=tokenizer,
            aggregation_strategy="first", stride=128, device=-1
        )

    def __call__(self, text):
        if not text.strip():
            return []
        spans = set()
        for item in self.predict(text):
            start, end = item["start"], item["end"]
            while start < end and text[start].isspace():
                start += 1
            while start < end and text[end - 1].isspace():
                end -= 1
            if start < end:
                spans.add(Span(start, end, item["entity_group"]))
        return sorted(spans)
