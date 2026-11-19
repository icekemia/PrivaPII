# PrivaPII meeting demo

## What to show

1. Launch `python app.py` from the project directory. Use the local NUS checkpoint when available. Keep the application and case open until restoration is complete.
2. Paste the first example below, detect findings and manually mark any missed names. Review the findings list and choose **Pseudonymize**. Copy the preview to a local text editor.
3. Repeat for the second example in the same case. Copy its preview above the first preview and duplicate one reference inside Markdown bold. Paste the combined text into **Restore derived text**. Confirm that the references resolve in the new order and that the original inflected forms are preserved.
4. Change one character in a token and preview again. Restoration should stop and the restored preview should be cleared. Repeat with an intact token after opening a new case to demonstrate case isolation.
5. Present the [aggregate NUS evaluation](NUS_Evaluation.md) alongside the workflow. In a paired comparison, show the same gold categories for the checkpoint and hybrid runs, the number of documents with uncovered gold, and any rule-only findings outside the annotation taxonomy. Limit claims to the NUS upstream evaluation split and the measured processing path.

## Synthetic workflow examples

**Document A**

> Eglė Noreikaitė pateikė paraišką. Kontaktinis el. paštas: egles.demo@example.org.

**Document B**

> Eglės Noreikaitės paraiška peržiūrėta. Apie sprendimą bus pranešta el. paštu.

The examples demonstrate the restoration workflow. Quantitative results come from the annotated NUS evaluation split. Use a local editor for the combined output and show aggregate corpus results during the meeting.

## Questions for Lithuanian reviewers

- Which document types and identifying details are most important for a professional pilot?
- In the export preview, can a reviewer quickly find missed values, inspect retained details and correct the selected spans?
- In a derived summary or translation, when should the reviewer choose a different Lithuanian grammatical case for a restored name?
- Which workflow matters first for a pilot: a persistent case vault, organized review of larger document batches, or scanned PDF support?
