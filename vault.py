"""Passphrase-protected SQLite workspaces for local document review."""

import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import asdict
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from privapii import TOKEN, Span, canonical_token, merged_ranges, restore_references, token_prefix


def new_id():
    return uuid4().hex


class Workspace:
    """Encrypt the complete workspace snapshot before committing it to SQLite."""

    def __init__(self, path, passphrase, *, create=False):
        self.path = path.resolve()
        if not passphrase:
            raise ValueError("A workspace passphrase is required.")
        if create:
            if len(passphrase) < 12:
                raise ValueError("Choose a passphrase of at least 12 characters.")
            salt = secrets.token_bytes(16)
            self.id = new_id()
            self.documents, self.references, self.profiles = {}, {}, {}
            self.active_profile = "Standard"
            self.revision = 0
            self.cipher = self.derive(passphrase, salt)
            with self.path.open("xb"):
                pass
            with closing(self.connect()) as db, db:
                db.execute("CREATE TABLE vault (id TEXT PRIMARY KEY, salt BLOB, revision INTEGER, payload BLOB)")
                db.execute("INSERT INTO vault VALUES (?, ?, ?, ?)",
                           (self.id, salt, 0, self.encrypt(0)))
            return
        with closing(self.connect()) as db:
            row = db.execute("SELECT id, salt, revision, payload FROM vault").fetchone()
        if row is None:
            raise ValueError("The workspace vault is empty.")
        self.id, salt, self.revision, payload = row
        self.cipher = self.derive(passphrase, salt)
        try:
            clear = self.cipher.decrypt(payload[:12], payload[12:], self.aad(self.revision))
        except InvalidTag:
            raise ValueError("Unable to unlock the workspace. Check the passphrase or vault integrity.") from None
        state = json.loads(clear)
        self.documents = state["documents"]
        self.references = state["references"]
        self.profiles = state["profiles"]
        self.active_profile = state.get("active_profile", "Standard")

    def connect(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)

    @staticmethod
    def derive(passphrase, salt):
        key = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(passphrase.encode("utf-8"))
        return AESGCM(key)

    def aad(self, revision):
        return f"PrivaPII/vault/1/{self.id}/{revision}".encode("ascii")

    def encrypt(self, revision):
        nonce = secrets.token_bytes(12)
        clear = json.dumps({
            "documents": self.documents, "references": self.references, "profiles": self.profiles,
            "active_profile": self.active_profile,
        }, ensure_ascii=False).encode("utf-8")
        return nonce + self.cipher.encrypt(nonce, clear, self.aad(revision))

    def save(self):
        revision = self.revision + 1
        with closing(self.connect()) as db, db:
            result = db.execute(
                "UPDATE vault SET revision=?, payload=? WHERE id=? AND revision=?",
                (revision, self.encrypt(revision), self.id, self.revision),
            )
            if result.rowcount != 1:
                raise ValueError("Workspace changed in another window. Reopen it before saving.")
        self.revision = revision

    def review(self, document_id, name, text, spans, excluded=()):
        previous = self.documents.get(document_id)
        existing = previous["occurrences"] if previous and previous["text"] == text else []
        by_span = {(item["start"], item["end"], item["label"]): item for item in existing}
        occurrences = []
        for span in spans:
            item = dict(by_span.get((span.start, span.end, span.label), {}))
            if not item:
                item.update(id=new_id(), entity=new_id())
            item.update(asdict(span))
            occurrences.append(item)
        self.documents[document_id] = {
            "name": name, "text": text, "occurrences": occurrences, "excluded": list(excluded),
        }
        if previous and previous["text"] == text and "ocr" in previous:
            self.documents[document_id]["ocr"] = previous["ocr"]

    def link(self, document_id, index, entity):
        item = self.documents[document_id]["occurrences"][index]
        candidates = self.entity_choices(item["label"])
        if entity not in candidates:
            raise ValueError("Choose an entity of the same category in this workspace.")
        item["entity"] = entity

    def entity_choices(self, label):
        result = {}
        for document in self.documents.values():
            for item in document["occurrences"]:
                if item["label"] == label:
                    value = document["text"][item["start"]:item["end"]]
                    result.setdefault(item["entity"], f'{value} · {document["name"]}')
        return result

    def link_people(self, selected, target):
        """Apply explicit identity decisions to selected person occurrences."""
        people = {item["id"]: item for document in self.documents.values()
                  for item in document["occurrences"] if item["label"] == "PER"}
        selected = set(selected)
        if target not in people or not selected or not selected <= people.keys():
            raise ValueError("Choose saved person mentions within this workspace.")
        entity = people[target]["entity"]
        previous = {key: people[key]["entity"] for key in selected if people[key]["entity"] != entity}
        if not previous:
            return 0
        for key in previous:
            people[key]["entity"] = entity
        try:
            self.save()
        except Exception:
            for key, original in previous.items():
                people[key]["entity"] = original
            raise
        return len(previous)

    def transform(self, document_id, selected, *, redact=False, link_person_forms=False):
        output, pending = self.plan_transform(document_id, selected, redact=redact,
                                              link_person_forms=link_person_forms)
        self.commit_references(pending)
        return output

    def plan_transform(self, document_id, selected, *, redact=False, link_person_forms=False,
                       staged=None):
        references = self.references | (staged or {})
        document = self.documents[document_id]
        text = document["text"]
        items = [document["occurrences"][index] for index in selected]
        spans = [Span(item["start"], item["end"], item["label"]) for item in items]
        parts, cursor = [], 0
        pending = {}
        for start, end in merged_ranges(text, spans):
            parts.append(text[cursor:start])
            token = "[REDACTED]"
            if not redact:
                exact = [item for item in items if (item["start"], item["end"]) == (start, end)]
                entities = {item["entity"] for item in exact}
                provenance = [item["id"] for item in items
                              if start <= item["start"] and item["end"] <= end]
                entity = next(iter(entities)) if len(entities) == 1 else None
                value = text[start:end]
                key = [entity, value] if entity else [document_id, provenance, value]
                prefix = token_prefix(spans, start, end)
                if (link_person_forms and entity and prefix == "PRIVAPII_V2_PER_"
                        and all(item["entity"] == entity for item in items if item["id"] in provenance)):
                    prefix = f"PRIVAPII_V3_PER_{entity.upper()}_"
                for binding, record in (references | pending).items():
                    if binding.startswith("[" + prefix) and record["key"] == key:
                        token = binding
                        break
                else:
                    token = canonical_token(prefix + secrets.token_hex(16).upper())
                    while token in references or token in pending:
                        token = canonical_token(prefix + secrets.token_hex(16).upper())
                record = pending.get(token, references.get(token, {}))
                sources = record.get("sources", [])
                origin = [document_id, provenance]
                pending[token] = {"key": key, "value": value, "sources": sources if origin in sources else sources + [origin]}
            parts.append(token)
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts), pending

    def commit_references(self, pending):
        previous = self.references
        self.references = previous | pending
        try:
            self.save()
        except Exception:
            self.references = previous
            raise

    def current_person_entity(self, record):
        key = record["key"]
        sources = record.get("sources", [])
        if len(key) != 2 or not sources:
            return None
        entity, _ = key
        for document_id, identifiers in sources:
            occurrences = self.documents.get(document_id, {}).get("occurrences", [])
            by_id = {item["id"]: item for item in occurrences}
            if not identifiers or any(
                occurrence not in by_id or by_id[occurrence]["label"] != "PER"
                or by_id[occurrence]["entity"] != entity for occurrence in identifiers
            ):
                return None
        return entity

    def forms_by_occurrence(self, text):
        references = {token: item["value"] for token, item in self.references.items()}
        restore_references(text, references)
        identities = {token: self.current_person_entity(record) for token, record in self.references.items()}
        groups = {}
        for token, entity in identities.items():
            if entity:
                groups.setdefault(entity, set()).add(references[token])
        choices = {}
        for index, match in enumerate(TOKEN.finditer(text)):
            token = match.group()
            original = references[token]
            alternative = sorted(groups.get(identities[token], set()) - {original})
            if alternative:
                choices[index] = (original, *alternative)
        return choices

    def restore(self, text, overrides=None):
        if overrides:
            allowed = self.forms_by_occurrence(text)
            if any(index not in allowed or value not in allowed[index] for index, value in overrides.items()):
                raise ValueError("An alternate form is no longer authorized for this occurrence.")
        return restore_references(text, {token: item["value"] for token, item in self.references.items()}, overrides)
