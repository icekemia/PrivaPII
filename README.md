# PrivaPII

PrivaPII is a Windows desktop tool for preparing Lithuanian documents for external analysis. You choose which details to protect, review the exact export, and restore protected values locally when the result comes back. The encrypted workspace stays on your device.

**First time?** Set up the app and try the [two-document walkthrough](docs/Demo_Guide.md) with fictional data. It works in Rules only mode and takes you from import to restoration.

## 1. Set up on Windows

1. Install **Python 3.11 x64 with Tk** on Windows. Select **Add python.exe to PATH** in the installer so setup can find it. [Official Windows installer](https://www.python.org/downloads/release/python-3119/)
2. If you received a ZIP, extract the whole archive to a writable folder. To verify the download, compare the SHA-256 in the adjacent file with `Get-FileHash -Algorithm SHA256 <path-to-zip>` in PowerShell.
3. Double-click **Setup-PrivaPII.cmd**, then open **Start-PrivaPII.cmd**. Setup uses the included wheelhouse. If setup cannot find Python, check that `python --version` in a new PowerShell window reports Python 3.11.

| Mode | When to use it |
| --- | --- |
| **Rules only** | Try the workflow. Detects supported structured values such as emails, phone numbers and Lithuanian identifiers. Mark names and other details manually when needed. |
| **NUS + rules** | Review name and other category suggestions alongside the structured rules. Requires the local NUS checkpoint and its dependencies. |
| **Review scan** | Inspect scans, images and visual regions of mixed PDFs. Requires the local NUS, PP-OCRv6 and Lithuanian Tesseract models and their dependencies. |

The application ZIP keeps model files separate. If you received model assets for testing, follow the [local model setup](docs/Development_Setup.md) or [OCR setup](docs/OCR.md#setup). Use the [source checkout instructions](docs/Development_Setup.md) if you are running from Git.

## 2. Decide what belongs in one workspace

Think of a **workspace as one case or one job you intend to analyse together**. It can contain several documents and several people.

- **Same case, same person across files.** Import the application, annexes and correspondence into one workspace if you want to analyse them together. Each file remains a separate document. You can link that person's mentions across them.
- **Several people in the same case.** Keep the relevant documents together and review the identities separately. The same spelling can belong to different people.
- **Same person in unrelated cases.** Use separate workspaces if the people receiving each export should be able to analyse only that case. Restoration uses the workspace that created the tokens.

Select **Create workspace**, choose a new `.sqlite` file and set a passphrase. Reopen it later with **Open workspace**. One practical folder layout is:

```text
case-014/
  originals/       Source files, kept locally
  vault/           Encrypted workspace and backup, kept locally
  outbound/        Reviewed pseudonymized exports
  returned/        Results received from the external tool
  restored/        Restored files with original values, kept locally
```

Use neutral names for files you share. **Export workspace ZIP** names members automatically. The SQLite file and backup contain the mappings needed to restore values. Keep them local and store the passphrase separately. Temporary mode retains mappings only until you close the app.

### Link the same person across documents

1. Import and review each document. Categorize the full name as `PER` so that it appears under **Review people**.
2. In **Review people**, search by name fragment or document name. Use **Show candidate matches** for same-spelling and possible Lithuanian inflection matches. Compare the source context.
3. Select one confirmed mention and choose **Set selected mention as target**. Select the other mentions of that person, then choose **Link selected mentions to target** and confirm. If you linked the wrong mentions, use **Show entity mentions** and **Split selected mentions**.
4. If the recipient needs to group the same person across the selected documents, turn on **Expose linked person IDs** before producing their exports. This makes the association visible to the recipient. Different recorded forms still have distinct tokens, so each can be restored as originally written.

Regenerate exports after changing a link. Previously generated tokens remain restorable to the values they originally represented.

## 3. Choose what to protect and what to keep visible

1. Select **Import document** for TXT, TSV, Markdown, DOCX or a PDF with selectable text. Paste into a new document if you already have text. For a scan or image, choose **Review scan → Document lines**. PDF import flags pages that contain both a text layer and images. Inspect the visual portion or use OCR when it matters. DOCX import covers body text, common lists and table text. Review headers, footers and images separately when they matter.
2. Select **Detect** and inspect the findings next to the source. To add a missed span, select the entire value in the source and choose **Mark selected text**. Select its finding and use **Edit category**, for example `PER` for a full personal name, `DOB` for a birth date, or `EMAIL` for an email address.
3. Open **Categories and profiles**. Select a profile and press **Load profile** to load its checkboxes, then adjust them and confirm. A checked category is selected for protection. An unchecked category stays visible unless you explicitly protect a verified OCR region. Enter a new name to save a custom profile for this workspace.
4. For a **single exception**, select the finding and choose **Toggle exclusion**. The finding's action changes to **keep**. This is useful when you want to preserve one public organization name while protecting other organization mentions. Review the action shown for the exact occurrence.
5. Choose **Pseudonymize** to create restorable tokens. Use **Redact irreversibly** only when you want permanent removal in that output. Reapply the export after changing the policy or a finding. Category changes use saved findings and take effect without rerunning detection.

| Profile or choice | When to use it |
| --- | --- |
| **Standard** | Start here for document analysis. It protects detected identifiers and keeps ordinary dates, times, durations and quantities visible. An explicit birth date is its own protected category. |
| **Identity only** | Start here if you need a narrower set of identity and contact categories. Inspect the categories that would remain visible. |
| **Strict** | Starts with every listed category selected. Review the effect on dates, amounts and contextual facts needed for the analysis. |
| **Custom** | Use a named profile for a recurring task. For a timeline, keep `DATE` visible and `DOB` selected. If a specific date identifies someone in context, mark and categorize that finding appropriately or select the date category. |

Check that full names, financial identifiers and relevant addresses are covered. Confirm that useful details such as date of issue and numbered clause references remain readable. The export preview flags supported structured values that are still visible. Review names, locations and indirect clues against the source as well.

## 4. Choose the export format

Choose **Save reviewed export**, select a format and inspect the exact outbound content before clicking **Save reviewed file**.

| Format | Choose it when you need | Restore later? |
| --- | --- | --- |
| **TXT** | Simple copy/paste, API input or plain-text analysis. | Yes |
| **Markdown** | A readable document with headings, numbered references and structure for an LLM. | Yes |
| **CSV** | A verified table for spreadsheet or data analysis. This option appears for a complete supported table. | Yes, cell by cell |
| **Word (.docx)** | A fresh editable document or verified Word table built from the reviewed content. | Yes, from a returned DOCX |
| **PDF with pixel masks** | A layout-preserving visual copy for human reading. From scan review, choose **Review PDF masks** and confirm each page. | Permanent obscuring in this PDF |
| **Workspace ZIP** | Several reviewed TXT or Markdown files for the same job. Choose **Export workspace ZIP**, prepare previews and confirm each file. | Yes, after extracting returned files |

For a digital PDF or Word table, choose **Import table** and review the extracted grid. For scans, borderless tables or merged cells, use **Review scan → Table cells**. See the [table and PDF workflows](docs/OCR.md).

Give the external tool the reviewed outbound files for the job. An example instruction:

> Analyse the documents and prepare a timeline. Copy each relevant PRIVAPII token exactly, including its brackets. Preserve dates and clause references where relevant.

Pseudonymized documents can still contain identifying context. Match the scope of the export to what the recipient needs.

## 5. Restore the result

1. Open the original workspace and switch to **Restore derived text**. Paste the returned text or use **Import derived text**. For a return ZIP, extract the returned files first. Import one CSV at a time.
2. Use **Compare tokens** and select the original pseudonymized exports. Review missing, unknown or possibly damaged tokens. A summary can legitimately omit a reference. The original value can be restored wherever its intact token appears.
3. Select **Preview local restoration**. Check who is being referred to and whether the Lithuanian grammar still fits. If the sentence changed, **Choose verified person form** lets you select another recorded form for a single occurrence.
4. Use **Save restored file** and put the result in your local `restored/` folder. **Backup** creates a separate encrypted workspace copy. Test that you can open it with the same passphrase before relying on it.

## Process standard forms in batches

Use **Document models** in an unlocked workspace when each client has the same set of standard PDFs. Open a sample PDF with selectable text. Select a heading that identifies the form version, then select each printed field label before its colon. Choose **Protect** or **Keep visible** and mark a field as optional only if it can legitimately be blank. For example, protect the value on the line starting with “Gimimo data:” and keep the value on the line starting with “Dokumento data:”.

Choose **Test on another PDF** and verify the highlighted fields against that PDF. Approve the model after checking the matches. Changing an approved model creates a new version. The encrypted workspace stores labels and rules. Use generic field labels and a non-personal heading and model name.

In **Process client folders**, choose a parent directory containing one folder per client and select the required models. Include one PDF per model. PrivaPII reports unknown forms, duplicate documents and missing, repeated or empty required fields. By default any such issue excludes the entire client folder. The partial option includes only the documents that passed the checks and can change which records contribute to a KPI.

Choose CSV and select the fields needed for the analysis to create one “fields.csv” in the ZIP. Each row holds a document ID, field name and value. For full reviewed text, choose TXT or Markdown. Review the output of each included document before saving. To let a downstream tool associate documents from one client, enable temporary grouping. This adds a neutral client column in CSV or neutral client folders such as “client-001” in a text ZIP. Results are reversible in the same vault. Review information outside the modeled fields before exporting full text.

This workflow supports a single inline “Label: value” field per line in native-text PDFs. It flags pages with images or missing text for separate review. Use a distinct printed heading for each form version you intend to distinguish. Scanned PDFs and tables can be reviewed with the existing scan and table tools.

## Testing and reference

- [First-use walkthrough and feedback checklist](docs/Demo_Guide.md)
- [Scanning, tables and PDF masking](docs/OCR.md)
- [Source setup, model verification and benchmarks](docs/Development_Setup.md)
- [Pilot readiness and known limits](docs/Pilot_Readiness.md)
