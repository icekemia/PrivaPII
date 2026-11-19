# PrivaPII workflow validation

## What to show

1. Launch PrivaPII using the [setup instructions](../README.md). Create a persistent workspace and use the local NUS checkpoint when available.
2. Paste the first example below, detect findings and manually mark any missed names. Review the findings list and choose **Pseudonymize**. Copy the preview to a local text editor.
3. Repeat for the second example in the same workspace. Confirm a manual identity link if the two mentions refer to the same person. Copy the second preview above the first preview and duplicate one reference inside Markdown bold. Close and reopen the workspace, then paste the combined text into **Restore derived text**. Confirm the new order and original inflected forms.
4. Change one character in a token and preview again. Restoration should stop and clear the restored preview. Repeat with an intact token after opening another workspace to check isolation.
5. Present the [aggregate NUS evaluation](NUS_Evaluation.md) alongside the workflow. In a paired comparison, show the same gold categories for the checkpoint and hybrid runs, the number of documents with uncovered gold, and any rule-only findings outside the annotation taxonomy. Limit claims to the NUS upstream evaluation split and the measured processing path.

## Synthetic workflow examples

**Document A**

> Eglė Noreikaitė pateikė paraišką. Kontaktinis el. paštas: egles.demo@example.org.

**Document B**

> Eglės Noreikaitės paraiška peržiūrėta. Apie sprendimą bus pranešta el. paštu.

The examples exercise restoration. Quantitative detection results use the annotated NUS evaluation split. Use a local editor for the combined output.
