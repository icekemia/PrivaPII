"""Offline adapter for the pinned NUS token-classification checkpoint."""

from privapii import Span

CHECKPOINT_BYTES = 2_235_612_716
STRIDE = 128


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
        self.tokenizer, self.model, self.torch = tokenizer, model.eval(), torch
        self.predict = pipeline(
            "token-classification", model=model, tokenizer=tokenizer,
            aggregation_strategy="first", stride=STRIDE, device=-1
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
                spans.add(Span(start, end, item["entity_group"], "nus", float(item["score"])))
        return sorted(spans)

    def centered(self, text):
        """Decode BIO tags once across centered, overlapping token windows."""
        if not text.strip():
            return []
        batch = self.tokenizer(
            text, truncation=True, max_length=512, stride=STRIDE,
            return_offsets_mapping=True, return_overflowing_tokens=True,
        )
        words = {}
        for index, encoding in enumerate(batch.encodings):
            positions = [position for position, word in enumerate(encoding.word_ids)
                         if word is not None]
            if not positions:
                continue
            fields = {key: self.torch.tensor([batch[key][index]]) for key in self.tokenizer.model_input_names
                      if key in batch}
            with self.torch.inference_mode():
                confidence, labels = self.model(**fields).logits[0].softmax(-1).max(-1)
            for position in positions:
                word = encoding.word_ids[position]
                start, end = encoding.offsets[position]
                edge_distance = min(position - positions[0], positions[-1] - position)
                label = self.model.config.id2label[int(labels[position])]
                row = (start, end, label, float(confidence[position]), edge_distance)
                words.setdefault(word, {}).setdefault((start, end), []).append(row)
        return decode_centered(text, words)


def decode_centered(text, words):
    spans = []
    current = None
    for offsets in words.values():
        tokens = sorted(max(candidates, key=lambda row: row[4]) for candidates in offsets.values())
        start, _, tag, score, _ = tokens[0]
        end = max(token[1] for token in tokens)
        prefix, _, label = tag.partition("-")
        if prefix == "I" and current and current.label == label:
            current = Span(current.start, max(current.end, end), label, "nus",
                           min(current.confidence, score))
            continue
        if current:
            spans.append(current)
        current = Span(start, end, label, "nus", score) if prefix in {"B", "I"} and label else None
    if current:
        spans.append(current)
    trimmed = []
    for span in spans:
        value = text[span.start:span.end]
        if value.strip():
            trimmed.append(Span(span.start + len(value) - len(value.lstrip()),
                                span.start + len(value.rstrip()), span.label, span.source, span.confidence))
    return sorted(set(trimmed))
